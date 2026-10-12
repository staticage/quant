"""真实 PostgreSQL 的行情语义验证；不把这些检查称为策略回测。

QUANT_TEST_POSTGRES=1 显式启用集成测试。数据写入测试交易对且在事务结束回滚，
不会污染正式行情；默认单元测试无需数据库服务。
"""
from datetime import datetime, timedelta, timezone
from contextlib import nullcontext
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from market_store import MarketStore, prepare_market_data
from postgres_service import connect


@unittest.skipUnless(os.environ.get("QUANT_TEST_POSTGRES") == "1", "需要显式启用 PostgreSQL 集成测试")
class MarketStoreTests(unittest.TestCase):
    def test_explicit_skip_policy_keeps_raw_data_and_audits_gaps(self):
        self.store.ingest(self.exchange,"BTC/USDT",self.frame.drop(index=[10]))
        self.store.ingest(self.exchange,"ETH/USDT",self.frame.drop(index=[10]))
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            with patch("market_store.connect",return_value=nullcontext(self.conn)), patch("market_store.subprocess.run"):
                audit=prepare_market_data(self.exchange,{('BTC/USDT','1h'):0,('ETH/USDT','1h'):0,('ETH/USDT','5m'):0},
                    self.start.date(),self.end.date(),output/'config.json',output,output/'data',skip_gaps=True)
            self.assertEqual(audit['gap_policy'],'skip_orders')
            self.assertEqual(audit['pairs']['ETH/USDT']['missing'],1)
            self.assertEqual(audit['pairs']['ETH/USDT']['partial_buckets']['1h'],1)
            self.assertEqual(len(pd.read_feather(output/'data/BTC_USDT-1h.feather')),47)
            self.assertEqual(len(pd.read_feather(output/'data/ETH_USDT-1h.feather')),48)
            self.assertEqual(len(pd.read_feather(output/'data/ETH_USDT-5m.feather')),575)
            self.assertEqual(self.store.gaps(self.exchange,'ETH/USDT',self.start,self.end),
                [(self.start+timedelta(minutes=50),self.start+timedelta(minutes=55))])

    def setUp(self):
        self.conn = connect()
        self.store = MarketStore(self.conn)
        self.transaction = self.conn.transaction(force_rollback=True)
        self.transaction.__enter__()
        self.exchange = "test_" + uuid4().hex
        self.start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        self.end = self.start + timedelta(days=2)
        self.frame = pd.DataFrame({"date": pd.date_range(self.start, self.end, freq="5min", inclusive="left"),
            "open": [100+i for i in range(576)], "high": [103+i for i in range(576)],
            "low": [99+i for i in range(576)], "close": [102+i for i in range(576)], "volume": 2.0})

    def tearDown(self):
        self.transaction.__exit__(None, None, None)
        self.conn.close()

    def test_sql_ohlcv_and_utc_boundaries(self):
        self.assertEqual(self.store.ingest(self.exchange,"BTC/USDT",self.frame),576)
        day = self.store.aggregate(self.exchange,"BTC/USDT","1d",self.start,self.end)
        self.assertEqual(len(day),2)
        self.assertEqual(day.iloc[0][["open","high","low","close","volume"]].tolist(), [100,390,99,389,576])
        hour = self.store.aggregate(self.exchange,"BTC/USDT","1h",self.start,self.end)
        self.assertEqual(len(hour),48)
        self.assertEqual(hour.iloc[0][["open","high","low","close","volume"]].tolist(), [100,114,99,113,24])
        self.assertEqual(hour.iloc[-1].date, self.end-timedelta(hours=1))
        self.assertEqual(self.store.gaps(self.exchange,"BTC/USDT",self.start,self.end),[])

    def test_internal_gaps_and_incomplete_buckets(self):
        self.store.ingest(self.exchange,"BTC/USDT",self.frame.drop(index=[10,11,300]))
        gaps = self.store.gaps(self.exchange,"BTC/USDT",self.start,self.end)
        self.assertEqual(gaps, [(self.start+timedelta(minutes=50),self.start+timedelta(hours=1)),
                               (self.start+timedelta(minutes=1500),self.start+timedelta(minutes=1505))])
        self.assertEqual(len(self.store.aggregate(self.exchange,"BTC/USDT","1h",self.start,self.end)),46)
        self.assertTrue(self.store.aggregate(self.exchange,"BTC/USDT","1d",self.start,self.end).empty)
        self.store.ingest(self.exchange,"BTC/USDT",self.frame.iloc[[10,11,300]])
        self.assertEqual(self.store.gaps(self.exchange,"BTC/USDT",self.start,self.end),[])

    def test_idempotency_exchange_pair_isolation_and_unclosed_candles(self):
        # Freqtrade 原生 Feather 时间列通常为毫秒精度，入库需统一后校验5m边界。
        self.frame["date"] = self.frame.date.dt.as_unit("ms")
        self.store.ingest(self.exchange,"BTC/USDT",self.frame)
        self.assertEqual(self.store.ingest(self.exchange,"BTC/USDT",self.frame),0)
        self.assertEqual(self.store.gaps(self.exchange,"ETH/USDT",self.start,self.end),[(self.start,self.end)])
        self.assertEqual(self.store.gaps(self.exchange+"other","BTC/USDT",self.start,self.end),[(self.start,self.end)])
        self.assertEqual(self.store.ingest(self.exchange,"ETH/USDT",self.frame,now=self.start+timedelta(minutes=7)),1)
        self.assertEqual(len(self.store.aggregate(self.exchange,"ETH/USDT","5m",self.start,self.end)),1)

    def test_reject_invalid_ohlcv_and_unaligned_timestamp(self):
        for column,value in [("volume",-1),("high",1),("low",10000),("close",float('nan')),
                             ("date", self.start+timedelta(seconds=1))]:
            frame = self.frame.iloc[:1].copy()
            frame[column]=value
            with self.assertRaises(ValueError):
                self.store.ingest(self.exchange,"BTC/USDT",frame)

    def test_automatic_gap_download_then_cache_hit_and_native_export(self):
        """真实数据库 + 模拟下载返回，验证仅补内部缺口和第二次零下载的调度契约。"""
        from freqtrade.configuration import TimeRange
        from freqtrade.data.history.datahandlers import get_datahandler
        from freqtrade.enums import CandleType
        self.store.ingest(self.exchange,"BTC/USDT",self.frame.drop(index=[10,11,300]))
        def download(argv, **kwargs):
            self.assertEqual(argv[argv.index("--timeframes")+1],"5m")
            period = TimeRange.parse_timerange(argv[argv.index("--timerange")+1])
            data = self.frame[(self.frame.date >= period.startdt) & (self.frame.date < period.stopdt)]
            directory = Path(argv[argv.index("--datadir")+1])
            get_datahandler(directory,"feather").ohlcv_store("BTC/USDT","5m",data,CandleType.SPOT)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            args = (self.exchange,{("BTC/USDT","1h"):0,("BTC/USDT","1d"):0},
                    self.start.date(),self.end.date(),output/"config.json",output,output/"data")
            with patch("market_store.connect",return_value=nullcontext(self.conn)), patch("market_store.subprocess.run",side_effect=download) as run:
                audit = prepare_market_data(*args)
                self.assertEqual(run.call_count,2)
                self.assertFalse(audit["pairs"]["BTC/USDT"]["cache_hit"])
                audit = prepare_market_data(*args)
                self.assertEqual(run.call_count,2)
                self.assertTrue(audit["pairs"]["BTC/USDT"]["cache_hit"])
            native = get_datahandler(output/"data","feather").ohlcv_load("BTC/USDT","1d",
                       fill_missing=False,drop_incomplete=False,candle_type=CandleType.SPOT)
            self.assertEqual(len(native),2)
            self.assertEqual(native.iloc[0].close,389)

"""PostgreSQL 5m 行情仓库：覆盖检查、缺口补齐、SQL 聚合与原生文件导出。

这里只处理 OHLCV，不实现回测或撮合。下载及最终回测均由 Freqtrade 完成。
UTC K线开盘时间为主键，数据库只保存已经结束的现货 5m K线。
高周期使用 date_bin 对齐 UTC，首开/最高/最低/末收/成交量求和；
默认只有包含全部5m子K线的桶才导出。用户授权S09缺口跳过时，ETH执行桶可聚合现有
真实子K线，依靠5m撮合及缺口禁单，BTC方向桶仍必须完整；所有缺口必须审计。
"""
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import subprocess
import tempfile

import numpy as np
import pandas as pd
from freqtrade.data.history.datahandlers import get_datahandler
from freqtrade.enums import CandleType
import psycopg

from postgres_service import connect

ROOT = Path(__file__).resolve().parents[1]
MINUTES = {"5m": 5, "1h": 60, "4h": 240, "1d": 1440}
COLUMNS = ["date", "open", "high", "low", "close", "volume"]
SCHEMA = """
CREATE TABLE IF NOT EXISTS quant_candles_5m (
 exchange text NOT NULL, pair text NOT NULL, date timestamptz NOT NULL,
 open double precision NOT NULL CHECK(open > 0),
 high double precision NOT NULL CHECK(high >= open AND high >= close),
 low double precision NOT NULL CHECK(low > 0 AND low <= open AND low <= close),
 close double precision NOT NULL CHECK(close > 0),
 volume double precision NOT NULL CHECK(volume >= 0),
 PRIMARY KEY(exchange, pair, date),
 CHECK(mod(extract(epoch FROM date)::numeric,300) = 0)
);
CREATE INDEX IF NOT EXISTS quant_candles_date_brin ON quant_candles_5m USING brin(date);
CREATE TABLE IF NOT EXISTS quant_market_imports (
 exchange text NOT NULL, pair text NOT NULL, path text NOT NULL, sha256 text NOT NULL,
 imported_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(exchange,pair,path)
);
"""


class MarketStore:
    def __init__(self, conn):
        self.conn = conn
        if conn.info.server_version < 140000:
            raise RuntimeError("行情聚合需要 PostgreSQL 14 或更新版本")
        # 防止并行首次初始化造成系统目录唯一键冲突。
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(584213790)")
            conn.execute(SCHEMA)

    def ingest(self, exchange, pair, frame, now=None):
        """COPY 后按主键去重；不覆盖已确认历史，剔除尚未结束的当前 K线。"""
        data = frame[COLUMNS].copy()
        data["date"] = pd.to_datetime(data["date"], utc=True).dt.as_unit("ns")
        now = pd.Timestamp(now or datetime.now(timezone.utc))
        data = data[data.date + pd.Timedelta(minutes=5) <= now]
        values = data[COLUMNS[1:]].to_numpy(dtype=float)
        if (data.date.isna().any() or (data.date.astype("int64") % (300 * 10**9)).any()
                or not np.isfinite(values).all() or (data.low <= 0).any()
                or (data.volume < 0).any() or (data.high < data[["open", "close"]].max(axis=1)).any()
                or (data.low > data[["open", "close"]].min(axis=1)).any()):
            raise ValueError(f"{exchange} {pair} 5m 行情含无效时间或 OHLCV")
        data = data.drop_duplicates("date").sort_values("date")
        with self.conn.transaction():
            self.conn.execute("CREATE TEMP TABLE IF NOT EXISTS quant_ingest (LIKE quant_candles_5m) ON COMMIT DROP")
            self.conn.execute("TRUNCATE quant_ingest")
            with self.conn.cursor().copy("COPY quant_ingest (exchange,pair,date,open,high,low,close,volume) FROM STDIN") as writer:
                for row in data.itertuples(index=False, name=None):
                    writer.write_row((exchange, pair, row[0].to_pydatetime(), *map(float, row[1:])))
            added = self.conn.execute("""INSERT INTO quant_candles_5m SELECT * FROM quant_ingest
                ON CONFLICT (exchange,pair,date) DO NOTHING""").rowcount
        return added

    def import_existing(self, exchange, pair):
        """一次性迁移旧 5m 文件，其他周期绝不入库；内容未变不重复读取。"""
        path = ROOT / "user_data/data" / exchange / f"{pair.replace('/', '_')}-5m.feather"
        if not path.exists():
            return 0
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        key = (exchange, pair, str(path))
        previous = self.conn.execute("SELECT sha256 FROM quant_market_imports WHERE exchange=%s AND pair=%s AND path=%s", key).fetchone()
        if previous and previous[0] == digest:
            return 0
        count = self.ingest(exchange, pair, pd.read_feather(path))
        self.conn.execute("""INSERT INTO quant_market_imports(exchange,pair,path,sha256) VALUES(%s,%s,%s,%s)
            ON CONFLICT(exchange,pair,path) DO UPDATE SET sha256=excluded.sha256, imported_at=now()""", (*key, digest))
        return count

    def gaps(self, exchange, pair, start, end):
        """逐根检查而非仅比较 MIN/MAX，返回连续缺口的 [起点,终点) 区间。"""
        return self.conn.execute("""
          WITH missing AS (
            SELECT t FROM generate_series(%s::timestamptz, %s::timestamptz - interval '5 minutes', interval '5 minutes') t
            WHERE NOT EXISTS (SELECT 1 FROM quant_candles_5m c WHERE c.exchange=%s AND c.pair=%s AND c.date=t)
          ), grouped AS (SELECT t, t - row_number() OVER(ORDER BY t) * interval '5 minutes' AS grp FROM missing)
          SELECT min(t), max(t)+interval '5 minutes' FROM grouped GROUP BY grp ORDER BY min(t)
        """, (start, end, exchange, pair)).fetchall()

    def aggregate(self, exchange, pair, timeframe, start, end, allow_partial=False):
        """默认只聚合完整桶；授权的ETH执行桶可用实际子K线，必须配合5m撮合和缺口禁单。"""
        minutes = MINUTES[timeframe]
        rows = self.conn.execute("""
          SELECT date_bin(%s::interval,date,timestamptz '1970-01-01 00:00:00+00') AS bucket,
            (array_agg(open ORDER BY date))[1], max(high), min(low),
            (array_agg(close ORDER BY date DESC))[1], sum(volume)
          FROM quant_candles_5m WHERE exchange=%s AND pair=%s AND date >= %s AND date < %s
          GROUP BY bucket HAVING count(*)=%s OR %s ORDER BY bucket
        """, (f"{minutes} minutes", exchange, pair, start, end, minutes // 5, allow_partial)).fetchall()
        frame = pd.DataFrame(rows, columns=COLUMNS)
        frame["date"] = pd.to_datetime(frame["date"], utc=True)
        for column in COLUMNS[1:]:
            frame[column] = frame[column].astype(float)
        return frame


def prepare_market_data(exchange, plan, start, end, config_path, runtime_dir, data_dir, skip_gaps=False):
    """按交易对串行持锁补齐，共享数据库不会因并行 CLI 重复下载同一范围。"""
    first = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    last = datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc)
    if last > datetime.now(timezone.utc).replace(second=0, microsecond=0):
        raise ValueError("回测终点包含尚未结束的行情，请选择不晚于今天 UTC 的日期")
    ranges = {(pair, tf): first - timedelta(minutes=count * MINUTES[tf]) for (pair, tf), count in plan.items()}
    data_dir.mkdir(parents=True, exist_ok=True)
    (ROOT / ".cache").mkdir(exist_ok=True)
    audit = {"backend": "postgresql", "stored_timeframe": "5m", "aggregation": "UTC / complete buckets", "pairs": {}}
    try:
        with connect() as conn:
            store = MarketStore(conn)
            for pair in sorted({pair for pair, _ in plan}):
                key = f"quant-market:{exchange}:{pair}"
                conn.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", (key,))
                try:
                    imported = store.import_existing(exchange, pair)
                    earliest = min(value for (p, _), value in ranges.items() if p == pair)
                    missing = store.gaps(exchange, pair, earliest, last)
                    print(f"{pair} PostgreSQL：导入旧5m {imported}根，缺少 {len(missing)} 段", flush=True)
                    downloads = []
                    for gap_start, gap_end in missing:
                        # 全新临时目录避免原生下载器只追加而漏掉内部缺口。
                        # 下载严格限于缺失范围，代理沿用运行配置中的 CCXT 参数。
                        with tempfile.TemporaryDirectory(prefix="market-", dir=ROOT / ".cache") as directory:
                            subprocess.run(["uv", "run", "--no-sync", "freqtrade", "download-data",
                                "--config", str(config_path), "--userdir", str(runtime_dir),
                                "--datadir", directory, "--pairs", pair, "--timeframes", "5m",
                                "--timerange", f"{gap_start:%Y%m%dT%H%M}-{gap_end:%Y%m%dT%H%M}"], cwd=ROOT, check=True)
                            file = Path(directory) / f"{pair.replace('/', '_')}-5m.feather"
                            if not file.exists():
                                if skip_gaps:
                                    downloads.append({"start":gap_start.isoformat(),"end_exclusive":gap_end.isoformat(),"inserted":0})
                                    continue
                                raise ValueError(f"{pair} 下载没有返回5m文件")
                            candles = pd.read_feather(file)
                            candles = candles[(candles.date >= gap_start) & (candles.date < gap_end)]
                            added = store.ingest(exchange, pair, candles)
                            downloads.append({"start": gap_start.isoformat(), "end_exclusive": gap_end.isoformat(), "inserted": added})
                    remaining = store.gaps(exchange, pair, earliest, last)
                    if remaining and not skip_gaps:
                        raise ValueError(f"{pair} 5m 行情仍有 {len(remaining)} 段缺口，首段 {remaining[0]}；停止回测，不能静默填补")
                    audit["pairs"][pair] = {"required_start": earliest.isoformat(), "end_exclusive": last.isoformat(),
                        "imported": imported, "downloaded_ranges": downloads, "cache_hit": not missing, "missing": sum(int((b-a).total_seconds()/300) for a,b in remaining),
                        "skipped_ranges": [{"start":a.isoformat(),"end_exclusive":b.isoformat()} for a,b in remaining]}
                    audit["pairs"][pair]["partial_buckets"] = {}
                    for (p, tf), required_start in ranges.items():
                        if p != pair:
                            continue
                        frame = store.aggregate(exchange, pair, tf, required_start, last, allow_partial=skip_gaps and pair == "ETH/USDT")
                        expected = pd.date_range(required_start, last, freq=f"{MINUTES[tf]}min", inclusive="left")
                        if frame.empty:
                            raise ValueError(f"{pair} {tf}整个区间没有可用行情")
                        if not skip_gaps and not expected.equals(pd.DatetimeIndex(frame.date)):
                            raise ValueError(f"{pair} {tf} SQL 聚合后的K线不完整")
                        if skip_gaps and pair == "ETH/USDT" and tf != "5m":
                            touched = {pd.Timestamp(t).floor(f"{MINUTES[tf]}min") for a,b in remaining
                                       for t in pd.date_range(a,b,freq="5min",inclusive="left")}
                            audit["pairs"][pair]["partial_buckets"][tf] = len(touched.intersection(set(frame.date)))
                        if skip_gaps and pair == "ETH/USDT" and tf == "5m" and frame.date.iloc[-1] < last - timedelta(minutes=5):
                            raise ValueError("ETH回测终点位于行情缺口中，无法可靠结算，请调整终点")
                        get_datahandler(data_dir, "feather").ohlcv_store(pair, tf, frame, CandleType.SPOT)
                finally:
                    conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,))
    except psycopg.Error:
        raise RuntimeError("PostgreSQL 行情仓库操作失败，请检查数据库权限和服务日志") from None
    audit["gap_policy"] = "skip_orders" if skip_gaps else "strict"
    return audit

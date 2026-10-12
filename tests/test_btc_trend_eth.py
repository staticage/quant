"""S09跨资产信号与时间边界检查，不模拟撮合，不声称真实行情收益。"""
import unittest
from types import SimpleNamespace
import pandas as pd
from test_freqtrade_strategies import isolated_strategy, frame


class BtcTrendEthTests(unittest.TestCase):
    def test_btc_signals_are_only_entry_and_exit_source(self):
        s=isolated_strategy('S09BtcTrendEth')
        d=frame([100]*6)
        d['btc_entry_signal']=[False,True,False,False,True,False]
        d['btc_exit_signal']=[False,False,True,False,False,True]
        result=s.populate_exit_trend(s.populate_entry_trend(d.copy(),{}),{})
        self.assertEqual(result.enter_long.tolist(),[0,1,0,0,1,0])
        self.assertEqual(result.exit_long.tolist(),[0,0,1,0,0,1])
        self.assertFalse(((result.enter_long==1)&(result.exit_long==1)).any())
        # 即使ETH方向指标反向，信号也不变。
        d['dif'],d['dea']=[-1,1,-1,1,-1,1],[0]*6
        changed=s.populate_exit_trend(s.populate_entry_trend(d.copy(),{}),{})
        self.assertEqual(result.enter_long.tolist(),changed.enter_long.tolist())
        self.assertEqual(result.exit_long.tolist(),changed.exit_long.tolist())

    def test_cross_asset_alignment_and_future_btc_exclusion(self):
        s=isolated_strategy('S09BtcTrendEth')
        s.btc_fast.value,s.btc_slow.value,s.btc_signal.value=2,3,2
        eth=frame([2000+i%13 for i in range(100)])
        eth['date']=pd.date_range('2020-01-10',periods=100,freq='h',tz='UTC')
        btc=frame([100+i%7 for i in range(40)])
        calls=[]
        def provider(**kwargs):calls.append(kwargs);return btc
        s.dp=SimpleNamespace(get_pair_dataframe=provider)
        def analyze(d):
            result=s.populate_indicators(d.copy(),{'pair':'ETH/USDT'})
            return s.populate_exit_trend(s.populate_entry_trend(result,{}),{})
        full=analyze(eth)
        self.assertEqual(s.informative_pairs(),[('BTC/USDT','1d')])
        self.assertTrue(all(c=={'pair':'BTC/USDT','timeframe':'1d'} for c in calls))
        self.assertEqual(full.date_1d.iloc[22],pd.Timestamp('2020-01-09',tz='UTC'))
        self.assertEqual(full.date_1d.iloc[23],pd.Timestamp('2020-01-10',tz='UTC'))
        for end in (23,24,60):pd.testing.assert_frame_equal(full.iloc[:end],analyze(eth.iloc[:end]))
        # ETH价格完全改变，不改变BTC进出场信号；没有ETH MACD列。
        changed_eth=eth.copy();changed_eth['close']=5000-changed_eth['close']
        eth_result=analyze(changed_eth)
        self.assertEqual(full.enter_long.tolist(),eth_result.enter_long.tolist())
        self.assertEqual(full.exit_long.tolist(),eth_result.exit_long.tolist())
        self.assertNotIn('dif',full.columns)
        events=full[full.enter_long.eq(1)|full.exit_long.eq(1)]
        self.assertGreater(len(events),0)
        self.assertFalse(events.date_1d.duplicated().any())
        modified=btc.copy();modified.loc[modified.date>=pd.Timestamp('2020-01-10',tz='UTC'),'close']=10000
        s.dp.get_pair_dataframe=lambda **kwargs:modified
        changed=analyze(eth)
        pd.testing.assert_frame_equal(full.iloc[:23],changed.iloc[:23])
        self.assertNotEqual(full.btc_dif_1d.iloc[23],changed.btc_dif_1d.iloc[23])

    def test_reject_wrong_pair_missing_data_and_faster_reference(self):
        s=isolated_strategy('S09BtcTrendEth');d=frame([100]*100)
        with self.assertRaises(ValueError):s.populate_indicators(d,{'pair':'BTC/USDT'})
        s.timeframe='1d';s.btc_timeframe.value='4h'
        with self.assertRaises(ValueError):s.informative_pairs()
        s.timeframe='1h';s.btc_timeframe.value='1d'
        s.dp=SimpleNamespace(get_pair_dataframe=lambda **kwargs:pd.DataFrame())
        with self.assertRaises(ValueError):s.populate_indicators(d,{'pair':'ETH/USDT'})


if __name__=='__main__':unittest.main()

"""S09跨资产信号与时间边界检查，不模拟撮合，不声称真实行情收益。"""
import unittest
from types import SimpleNamespace
import pandas as pd
from test_freqtrade_strategies import isolated_strategy, frame


class BtcTrendEthTests(unittest.TestCase):
    def test_atr_tags_stake_bounds_and_unchanged_exits(self):
        s=isolated_strategy('S09BtcTrendEth');s.btc_atr_enabled.value=True
        d=frame([100]*5)
        d['btc_entry_signal']=[True]*5;d['btc_exit_signal']=[False,True,False,True,False]
        d['btc_atr_deviation_1d']=[1,2,2.01,-1,float('nan')]
        result=s.populate_exit_trend(s.populate_entry_trend(d.copy(),{}),{})
        self.assertEqual(result.enter_long.tolist(),[1,1,1,1,0])
        self.assertEqual(result.exit_long.tolist(),[0,1,0,1,0])
        self.assertEqual(result.enter_tag.iloc[1],'btc_macd_golden_cross')
        self.assertEqual(result.enter_tag.iloc[2],'btc_macd_golden_cross_atr_reduced')
        def stake(tag,minimum=5,maximum=1000):
            return s.custom_stake_amount('ETH/USDT',None,2000,1000,minimum,maximum,1,tag,'long')
        self.assertEqual(stake(result.enter_tag.iloc[2]),300)
        self.assertEqual(stake(result.enter_tag.iloc[1]),1000)
        self.assertEqual(stake(result.enter_tag.iloc[2],maximum=200),200)
        self.assertEqual(stake(result.enter_tag.iloc[2],minimum=350),0)
        s.btc_atr_enabled.value=False
        self.assertEqual(stake(result.enter_tag.iloc[2]),1000)
        self.assertEqual(s.populate_entry_trend(d.copy(),{}).enter_long.tolist(),[1]*5)

    def test_atr_closed_candle_alignment_and_future_prefix(self):
        import talib.abstract as ta
        s=isolated_strategy('S09BtcTrendEth');s.btc_atr_enabled.value=True
        s.btc_fast.value,s.btc_slow.value,s.btc_signal.value=2,3,2
        s.btc_atr_period.value,s.btc_atr_ema_period.value=3,4
        btc=frame([100+i%7 for i in range(40)])
        eth=frame([2000]*100);eth['date']=pd.date_range('2020-01-10',periods=100,freq='h',tz='UTC')
        s.dp=SimpleNamespace(get_pair_dataframe=lambda **kwargs:btc)
        def analyze(d):
            result=s.populate_indicators(d.copy(),{'pair':'ETH/USDT'})
            return s.populate_exit_trend(s.populate_entry_trend(result,{}),{})
        full=analyze(eth)
        expected=(btc.close-ta.EMA(btc,timeperiod=4))/ta.ATR(btc,timeperiod=3)
        self.assertAlmostEqual(full.btc_atr_deviation_1d.iloc[22],expected.iloc[8])
        self.assertAlmostEqual(full.btc_atr_deviation_1d.iloc[23],expected.iloc[9])
        for end in [23,24,60]:pd.testing.assert_frame_equal(full.iloc[:end],analyze(eth.iloc[:end]))
        changed=btc.copy();changed.loc[changed.date>=pd.Timestamp('2020-01-10',tz='UTC'),'close']=10000
        s.dp.get_pair_dataframe=lambda **kwargs:changed
        pd.testing.assert_frame_equal(full.iloc[:23],analyze(eth).iloc[:23])
        self.assertNotEqual(full.btc_atr_deviation_1d.iloc[23],analyze(eth).btc_atr_deviation_1d.iloc[23])

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

    def test_btc_sma_matches_s01_relation_and_publishes_once_per_candle(self):
        s=isolated_strategy('S09BtcTrendEth');s.btc_strategy.value='sma'
        s.btc_ma_fast.value,s.btc_ma_slow.value=2,3
        btc=frame([10,10,11,12,9,8,10,12,11,9])
        eth=frame([2000]*192);eth['date']=pd.date_range('2020-01-02',periods=192,freq='h',tz='UTC')
        s.dp=SimpleNamespace(get_pair_dataframe=lambda **kwargs:btc)
        def analyze(d):
            result=s.populate_indicators(d.copy(),{'pair':'ETH/USDT'})
            return s.populate_exit_trend(s.populate_entry_trend(result,{}),{})
        result=analyze(eth)
        self.assertNotIn('btc_dif_1d',result.columns)
        self.assertNotIn('dif',result.columns)
        # 1月3日的完整SMA2/3多头关系在1月3日23:00执行K线收盘才可见。
        row=result[result.date.eq(pd.Timestamp('2020-01-03 23:00',tz='UTC'))].iloc[0]
        self.assertEqual(row.btc_sma_fast_1d,10.5)
        self.assertAlmostEqual(row.btc_sma_slow_1d,31/3)
        self.assertEqual(row.enter_long,1)
        for _,day in result.groupby('date_1d'):
            self.assertLessEqual(int(day.enter_long.sum()),1)
            self.assertLessEqual(int(day.exit_long.sum()),1)
        self.assertGreater(result.exit_long.sum(),0)
        self.assertFalse(((result.enter_long==1)&(result.exit_long==1)).any())
        for end in [23,24,60,120]:pd.testing.assert_frame_equal(result.iloc[:end],analyze(eth.iloc[:end]))
        other=eth.copy();other['close']=100
        self.assertEqual(result.enter_long.tolist(),analyze(other).enter_long.tolist())

    def test_reject_wrong_pair_missing_data_and_faster_reference(self):
        s=isolated_strategy('S09BtcTrendEth');d=frame([100]*100)
        with self.assertRaises(ValueError):s.populate_indicators(d,{'pair':'BTC/USDT'})
        s.timeframe='1d';s.btc_timeframe.value='4h'
        with self.assertRaises(ValueError):s.informative_pairs()
        s.timeframe='1h';s.btc_timeframe.value='1d'
        s.dp=SimpleNamespace(get_pair_dataframe=lambda **kwargs:pd.DataFrame())
        with self.assertRaises(ValueError):s.populate_indicators(d,{'pair':'ETH/USDT'})


if __name__=='__main__':unittest.main()

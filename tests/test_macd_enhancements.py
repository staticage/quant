"""合成路径验证MACD增强规则和长周期收盘可见性，不作为真实行情回测。"""
import unittest
from types import SimpleNamespace
import pandas as pd
from test_freqtrade_strategies import isolated_strategy, frame, analyze


class MacdEnhancements(unittest.TestCase):
    def strategy(self):
        return isolated_strategy('S08MacdCross')

    def signal_frame(self):
        """在第2/4根设置金叉、第3根设置死叉，过滤指标刻意覆盖边界。"""
        d=frame([100]*4)
        d['dif'],d['dea']=[-1,1,-1,1],[0]*4
        d['filter_rsi']=[50,70,100,29]
        d['filter_ma']=[99,100,200,99]
        d['prior_volume_mean']=[1,1,100,1]
        d['volume']=[1,1.2,1,1.1]
        d['trend_dif_1d'],d['trend_dea_1d']=[1,-1,-1,1],[0,-2,0,2]
        return d

    def test_each_filter_and_combination_gate_entry_not_exit(self):
        scenarios=[({},[0,1,0,1]),({'rsi_enabled':True},[0,1,0,0]),
                   ({'ma_enabled':True},[0,0,0,1]),({'volume_enabled':True},[0,1,0,0]),
                   ({'mtf_enabled':True},[0,1,0,0]),
                   ({'mtf_enabled':True,'trend_mode':'zero'},[0,0,0,1]),
                   ({'mtf_enabled':True,'trend_mode':'both'},[0,0,0,0]),
                   ({'rsi_enabled':True,'ma_enabled':True,'volume_enabled':True},[0,0,0,0])]
        for settings,expected in scenarios:
            with self.subTest(settings=settings):
                s=self.strategy()
                for key,value in settings.items():getattr(s,key).value=value
                result=s.populate_entry_trend(self.signal_frame(),{})
                result=s.populate_exit_trend(result,{})
                self.assertEqual(result.enter_long.tolist(),expected)
                self.assertEqual(result.exit_long.tolist(),[0,0,1,0])

    def test_volume_average_excludes_current_spike(self):
        s=self.strategy();s.volume_enabled.value=True;s.volume_window.value=2
        d=frame([100]*5);d['volume']=[2,4,100,6,8]
        result=s.populate_indicators(d,{})
        self.assertEqual(result.prior_volume_mean.iloc[2],3)
        self.assertEqual(result.prior_volume_mean.iloc[3],52)

    def test_all_local_filters_preserve_prefix_and_nan_blocks_entry(self):
        s=self.strategy()
        s.rsi_enabled.value=s.ma_enabled.value=s.volume_enabled.value=True
        s.ma_period.value=20
        d=frame([100+i%17 for i in range(430)])
        full=analyze(s,d)
        for end in [40,120,400]:
            pd.testing.assert_frame_equal(full.iloc[:end],analyze(s,d.iloc[:end]))
        d=self.signal_frame();d.loc[1,'filter_rsi']=float('nan')
        self.assertEqual(s.populate_entry_trend(d,{}).enter_long.iloc[1],0)

    def test_informative_close_boundary_and_future_daily_changes(self):
        s=self.strategy();s.timeframe='1h';s.mtf_enabled.value=True
        s.trend_fast.value,s.trend_slow.value,s.trend_signal.value=2,3,2
        hourly=frame([100+i%11 for i in range(120)])
        hourly['date']=pd.date_range('2020-01-10',periods=120,freq='h',tz='UTC')
        daily=frame([100+i%7 for i in range(40)])
        s.dp=SimpleNamespace(current_whitelist=lambda:['TEST/USDT'],get_pair_dataframe=lambda **kwargs:daily)
        full=analyze(s,hourly)
        self.assertEqual(s.informative_pairs(),[('TEST/USDT','1d')])
        self.assertEqual(full.date_1d.iloc[0],pd.Timestamp('2020-01-09',tz='UTC'))
        self.assertEqual(full.date_1d.iloc[22],pd.Timestamp('2020-01-09',tz='UTC'))
        self.assertEqual(full.date_1d.iloc[23],pd.Timestamp('2020-01-10',tz='UTC'))
        # 改变尚未收盘的1月10日K线，不得影响1月10日22:00这根小时线的长周期指标。
        altered=daily.copy();altered.loc[altered.date>=pd.Timestamp('2020-01-10',tz='UTC'),'close']=10000
        s.dp.get_pair_dataframe=lambda **kwargs:altered
        changed=analyze(s,hourly)
        pd.testing.assert_frame_equal(full.iloc[:23],changed.iloc[:23])
        self.assertNotEqual(full.trend_dif_1d.iloc[23],changed.trend_dif_1d.iloc[23])
        s.dp.get_pair_dataframe=lambda **kwargs:daily
        for end in [23,24,60,100]:
            pd.testing.assert_frame_equal(full.iloc[:end],analyze(s,hourly.iloc[:end]))

    def test_invalid_timeframe_and_missing_informative_fail(self):
        s=self.strategy();s.mtf_enabled.value=True
        with self.assertRaises(ValueError):s.informative_pairs()
        s.timeframe='1h';s.dp=SimpleNamespace(current_whitelist=lambda:['TEST/USDT'],get_pair_dataframe=lambda **kwargs:pd.DataFrame())
        with self.assertRaises(ValueError):s.populate_indicators(frame([100]*100),{'pair':'TEST/USDT'})


if __name__=='__main__':unittest.main()

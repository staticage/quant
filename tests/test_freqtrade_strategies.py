"""隔离指标/信号检查；不是Freqtrade回测或完整策略加载验证。

缺少Freqtrade时，明确移除源码中的框架导入，只运行依赖pandas的策略方法。
IStrategy用object替代仅为实例化算法；不伪造订单、Trade状态或撮合结果。
原生导入测试在环境缺失时显式skip，避免把隔离检查当成框架兼容验证。
"""

import ast
import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


ROOT = Path(__file__).resolve().parents[1] / "repo"
NAMES = ["S01SmaTrend", "S02DonchianBreakout", "S03BollingerReversion",
         "S04RsiPullback", "S05TimeSeriesMomentum", "S08MacdCross"]


def isolated_strategy(name):
    """仅为算法检查提取方法，不注册Freqtrade模块，也不调用框架撮合。"""
    tree = ast.parse((ROOT / f"{name}.py").read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body if not
                 (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("freqtrade"))]
    from freqtrade.strategy import (IntParameter, DecimalParameter, BooleanParameter, CategoricalParameter,
                                    merge_informative_pair, timeframe_to_minutes)
    namespace = {"IStrategy": object, "Trade": object, "IntParameter": IntParameter,
                 "timeframe_to_minutes": timeframe_to_minutes, "DecimalParameter": DecimalParameter,
                 "BooleanParameter": BooleanParameter, "CategoricalParameter": CategoricalParameter,
                 "merge_informative_pair": merge_informative_pair}
    exec(compile(tree, str(ROOT / f"{name}.py"), "exec"), namespace)
    return namespace[name]()


def frame(prices, start="2020-01-01"):
    """合成日K线只验证公式与条件，不评估策略收益。"""
    return pd.DataFrame({"date": pd.date_range(start, periods=len(prices), tz="UTC"),
                         "open": prices, "high": prices, "low": prices,
                         "close": prices, "volume": 1.0})


def analyze(strategy, dataframe):
    metadata = {"pair": "TEST/USDT"}
    result = strategy.populate_indicators(dataframe.copy(), metadata)
    result = strategy.populate_entry_trend(result, metadata)
    return strategy.populate_exit_trend(result, metadata)


class SignalTests(unittest.TestCase):
    def test_sma_and_warmup(self):
        strategy = isolated_strategy(NAMES[0])
        strategy.fast_window.value, strategy.slow_window.value = 2, 3
        result = analyze(strategy, frame([1, 2, 3, 1]))
        self.assertEqual(result.enter_long.tolist(), [0, 0, 1, 0])
        self.assertEqual(result.exit_long.tolist(), [0, 0, 0, 1])

    def test_donchian_prior_window(self):
        strategy = isolated_strategy(NAMES[1])
        strategy.entry_window.value, strategy.exit_window.value = 2, 1
        result = analyze(strategy, frame([10, 10, 11, 9]))
        self.assertEqual(result.enter_long.tolist(), [0, 0, 1, 0])
        self.assertEqual(result.exit_long.tolist(), [0, 0, 0, 1])

    def test_bollinger_population_std(self):
        strategy = isolated_strategy(NAMES[2])
        strategy.band_window, strategy.band_width = 5, 1
        result = analyze(strategy, frame([100] * 5 + [90, 100]))
        self.assertEqual(result.enter_long.iloc[-2], 1)
        self.assertEqual(result.exit_long.iloc[-1], 1)
        self.assertAlmostEqual(result.bb_std.iloc[-2], 4)

    def test_rsi_initialization_and_recursion(self):
        strategy = isolated_strategy(NAMES[3])
        strategy.trend_window = 1
        result = analyze(strategy, frame([10, 12, 11, 13]))
        self.assertTrue(pd.isna(result.rsi.iloc[1]))
        self.assertAlmostEqual(result.rsi.iloc[2], 100 * 2 / 3)
        self.assertAlmostEqual(result.rsi.iloc[3], 100 * 6 / 7)
        flat = analyze(strategy, frame([10] * 5))
        self.assertEqual(flat.rsi.iloc[-1], 50)

    def test_rsi_entry_and_exit(self):
        strategy = isolated_strategy(NAMES[3])
        strategy.rsi_period, strategy.trend_window = 1, 4
        result = analyze(strategy, frame([1, 100, 99, 98, 110]))
        self.assertEqual(result.enter_long.iloc[3], 1)
        self.assertEqual(result.exit_long.iloc[4], 1)

    def test_momentum_updates_only_at_month_end(self):
        strategy = isolated_strategy(NAMES[4])
        strategy.lookback = 1
        result = analyze(strategy, frame([10, 12, 5, 4], start="2020-01-30"))
        self.assertEqual(result.enter_long.tolist(), [0, 1, 1, 1])
        self.assertTrue(pd.isna(result.monthly_momentum.iloc[0]))
        self.assertAlmostEqual(result.monthly_momentum.iloc[-1], 0.2)

    def test_prefix_invariance_and_no_collisions(self):
        history = frame([100 + i % 11 - i % 3 for i in range(430)] + [200, 5, 300])
        for name in NAMES:
            strategy = isolated_strategy(name)
            full = analyze(strategy, history)
            for end in (40, 210, 400, 431):
                with self.subTest(strategy=name, end=end):
                    prefix = analyze(strategy, history.iloc[:end])
                    pd.testing.assert_frame_equal(full.iloc[:end], prefix)
            self.assertFalse(((full.enter_long == 1) & (full.exit_long == 1)).any())
            no_volume = history.copy()
            no_volume["volume"] = 0
            inactive = analyze(strategy, no_volume)
            self.assertTrue((inactive.enter_long == 0).all())

    def test_macd_cross_and_parameter_effect(self):
        """验证交叉只触发一次、等号边界和参数变化，而非模拟收益。"""
        strategy = isolated_strategy("S08MacdCross")
        data = frame([10] * 6)
        data["dif"], data["dea"] = [-1, 0, 1, 2, 0, -1], [0] * 6
        result = strategy.populate_entry_trend(data, {})
        result = strategy.populate_exit_trend(result, {})
        self.assertEqual(result.enter_long.tolist(), [0, 0, 1, 0, 0, 0])
        self.assertEqual(result.exit_long.tolist(), [0, 0, 0, 0, 0, 1])
        history = frame([100 + i % 17 for i in range(300)])
        standard = strategy.populate_indicators(history.copy(), {})
        pd.testing.assert_series_equal(standard.macd_hist, 2 * (standard.dif-standard.dea), check_names=False)
        strategy.macd_fast.value, strategy.macd_slow.value = 6, 12
        changed = strategy.populate_indicators(history.copy(), {})
        self.assertFalse(standard.dif.equals(changed.dif))
        strategy.macd_fast.value, strategy.macd_slow.value = 12, 26

    def test_timeout_uses_trade_open_time(self):
        opened = datetime(2020, 1, 1, tzinfo=timezone.utc)
        trade = SimpleNamespace(open_date_utc=opened)
        for name, days in ((NAMES[2], 20), (NAMES[3], 10)):
            strategy = isolated_strategy(name)
            self.assertIsNone(strategy.custom_exit("TEST/USDT", trade,
                              opened + timedelta(days=days, seconds=-1), 100, 0))
            self.assertEqual(strategy.custom_exit("TEST/USDT", trade,
                             opened + timedelta(days=days), 100, 0), "hold_timeout")

    @unittest.skipUnless(importlib.util.find_spec("freqtrade"), "未安装Freqtrade，原生导入未验证")
    def test_native_import(self):
        """即使原生导入成功，也仍需list-strategies检查真实配置下的加载。"""
        from freqtrade.strategy import IStrategy
        for name in NAMES:
            spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertTrue(issubclass(getattr(module, name), IStrategy))


if __name__ == "__main__":
    unittest.main()

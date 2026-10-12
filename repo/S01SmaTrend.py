"""S01 双均线趋势，Freqtrade interface v3，数字货币现货做多。

逻辑：20根简单均线高于60根均线时允许入场，反之（含相等）退出。
默认1d，20/60是K线数，不是股票交易日。适合持续上行，横盘易反复亏损。
资金大小由Freqtrade配置的stake_amount/max_open_trades决定，不是满仓承诺。
不设ROI止盈；框架固定止损-10%，这是额外风控，并非原始均线指标规则。
跳空/滑点可使实际损失超过止损；配置可能覆盖类内参数，运行前须核查。
来源：https://www.fidelity.com/webcontent/ap130058-research-experience-content/23.01/chartGuide/indicators.pdf
指标是基础均线，自定义进出场和止损；未经真实行情验证，不保证盈利。
"""

from pandas import DataFrame
from freqtrade.strategy import IStrategy, IntParameter


class S01SmaTrend(IStrategy):
    """以均线关系持续给出条件，持仓与成交由Freqtrade管理。"""

    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 60
    minimal_roi = {}  # 禁用独立ROI退出，保留策略退出及固定止损。
    stoploss = -0.10
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False  # 允许亏损时按趋势退出。
    # Freqtrade原生参数：同名JSON文件加载；范围2~400，不自动进行参数优化。
    fast_window = IntParameter(2, 400, default=20, space="buy", optimize=False)
    slow_window = IntParameter(3, 400, default=60, space="buy", optimize=False)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """含当根已结束收盘；完整窗口前为NaN，不前填未来值。"""
        if self.fast_window.value >= self.slow_window.value:
            raise ValueError("短均线窗口必须小于长均线窗口")
        dataframe["sma_fast"] = dataframe["close"].rolling(self.fast_window.value).mean()
        dataframe["sma_slow"] = dataframe["close"].rolling(self.slow_window.value).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """短均线高于长均线且有成交量时入场；不要求先观察金叉。"""
        dataframe["enter_long"] = 0
        dataframe.loc[(dataframe["sma_fast"] > dataframe["sma_slow"]) &
                      (dataframe["volume"] > 0), ["enter_long", "enter_tag"]] = (1, "sma_up")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """短均线不高于长均线时退出；与入场互斥，避免信号冲突。"""
        dataframe["exit_long"] = 0
        dataframe.loc[(dataframe["sma_fast"] <= dataframe["sma_slow"]) &
                      (dataframe["volume"] > 0), ["exit_long", "exit_tag"]] = (1, "sma_down")
        return dataframe

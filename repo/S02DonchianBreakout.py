"""S02 唐奇安通道突破，Freqtrade现货做多，默认日线20/10窗口。

此前20根最高high被当根close突破时入场；跌破此前10根最低low时退出。
通道必须shift(1)排除当根，否则high>=close会让突破条件无法正常成立。
来源：https://www.fidelity.com/webcontent/ap130058-research-experience-content/23.01/chartGuide/indicators.pdf
20/10交易规则为研究模板，不是包含ATR头寸和加仓的完整海龟系统。
另设框架固定-10%止损、禁用ROI止盈；仓位由Freqtrade配置决定。
风险：假突破、跳空和手续费；止损不保证损失封顶，未经收益验证。
"""

from pandas import DataFrame
from freqtrade.strategy import IStrategy, IntParameter


class S02DonchianBreakout(IStrategy):
    """区间突破入场，持仓状态交由Freqtrade，指标不保存跨币状态。"""

    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 21
    minimal_roi = {}
    stoploss = -0.10  # 本库额外风控，配置覆盖时需记录。
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    # 同名JSON文件提供Freqtrade原生参数；窗口单位为K线，不启用自动优化。
    entry_window = IntParameter(2, 400, default=20, space="buy", optimize=False)
    exit_window = IntParameter(1, 400, default=10, space="sell", optimize=False)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """滚动high/low后移一根；全样本批处理也只能使用历史窗口。"""
        if self.exit_window.value > self.entry_window.value:
            raise ValueError("退出窗口不能大于入场窗口")
        dataframe["channel_high"] = dataframe["high"].rolling(self.entry_window.value).max().shift(1)
        dataframe["channel_low"] = dataframe["low"].rolling(self.exit_window.value).min().shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """收盘严格突破上轨且有成交量；相等不入场。"""
        dataframe["enter_long"] = 0
        dataframe.loc[(dataframe["close"] > dataframe["channel_high"]) &
                      (dataframe["volume"] > 0), ["enter_long", "enter_tag"]] = (1, "channel_breakout")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """收盘严格跌破下轨退出；盘中触碰不属于此信号条件。"""
        dataframe["exit_long"] = 0
        dataframe.loc[(dataframe["close"] < dataframe["channel_low"]) &
                      (dataframe["volume"] > 0), ["exit_long", "exit_tag"]] = (1, "channel_exit")
        return dataframe

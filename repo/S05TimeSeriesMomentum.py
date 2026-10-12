"""S05 数字货币时间序列动量，Freqtrade现货做多，默认日线。

以365根日线价格收益代表约一年，而非沿用股票市场252交易日。
仅在UTC自然月最后一根日K线收盘更新方向，随后保持，最早次根成交。
M=close[t]/close[t-365]-1；M>0允许做多，M<=0退出；没有相对排名。
来源：https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum
本实现是价格收益、只做多、月末决策，未复现原论文的多空期货/波动配置。
另加固定-10%止损，止损后若月内方向仍正，可在后续信号重新入场。
风险：反转响应慢，月内重入可重复止损，滑点及成本；仓位由配置管理。
"""

from pandas import DataFrame, to_datetime
from freqtrade.strategy import IStrategy


class S05TimeSeriesMomentum(IStrategy):
    """月末判断自身历史收益，日期使用Freqtrade的UTC日线起始时间。"""

    INTERFACE_VERSION = 3
    timeframe = "1d"  # 月末定义依赖日线，不应直接用--timeframe换成小时线。
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 400  # 365根历史及等待首次有效月末的余量。
    minimal_roi = {}
    stoploss = -0.10
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    lookback = 365

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """月末采样再ffill，只传播过去决策；不按行号调仓以避免窗口相位漂移。"""
        dataframe["momentum"] = dataframe["close"] / dataframe["close"].shift(self.lookback) - 1
        dates = to_datetime(dataframe["date"], utc=True)
        dataframe["monthly_momentum"] = dataframe["momentum"].where(dates.dt.is_month_end).ffill()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """上次有效月末动量为正即允许开仓；持仓数量由框架决定。"""
        dataframe["enter_long"] = 0
        dataframe.loc[(dataframe["monthly_momentum"] > 0) & (dataframe["volume"] > 0),
                      ["enter_long", "enter_tag"]] = (1, "positive_monthly_momentum")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """上次有效月末动量非正退出；首次有效月末之前不发交易信号。"""
        dataframe["exit_long"] = 0
        dataframe.loc[(dataframe["monthly_momentum"] <= 0) & (dataframe["volume"] > 0),
                      ["exit_long", "exit_tag"]] = (1, "nonpositive_monthly_momentum")
        return dataframe

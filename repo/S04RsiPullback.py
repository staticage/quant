"""S04 RSI(2)超卖＋SMA200趋势过滤，Freqtrade现货做多。

入场：RSI<10且close>SMA200；退出：RSI>=50或close<=SMA200，
开仓满10个周期也退出；另加框架默认固定-10%止损，禁用ROI止盈。
来源：https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/RSI
这里使用Wilder平滑，但2/10/50和趋势过滤为自定义，非传统14/30/70参数。
风险：趋势反转、持续超卖、交易成本；仓位由配置管理，未验证收益。
预热400根给递推RSI留余量，更改参数后须用recursive-analysis再检查。
"""

from datetime import datetime, timedelta
from pandas import DataFrame, Series
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, timeframe_to_minutes


class S04RsiPullback(IStrategy):
    """采用显式Wilder初始化，避免把普通EMA的初值误称为Wilder均值。"""

    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 400
    minimal_roi = {}
    stoploss = -0.10  # 默认固定止损10%，回测配置stoploss可覆盖；执行由Freqtrade负责。
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    rsi_period = 2
    trend_window = 200
    buy_below = 10.0
    sell_above = 50.0
    max_hold_candles = 10

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """前period次变化均值初始化，随后按alpha=1/period递推。

        逐行只读当根及之前数据，输出顺序不依赖交易对处理顺序。
        平盘RSI=50，纯上涨RSI=100；未预热部分为NaN。
        """
        changes = dataframe["close"].diff()
        gains = changes.clip(lower=0).tolist()
        losses = (-changes.clip(upper=0)).tolist()
        period = self.rsi_period
        result = [float("nan")] * len(dataframe)
        if len(dataframe) > period:
            gain = sum(gains[1:period + 1]) / period
            loss = sum(losses[1:period + 1]) / period
            for i in range(period, len(dataframe)):
                if i > period:
                    gain = (gain * (period - 1) + gains[i]) / period
                    loss = (loss * (period - 1) + losses[i]) / period
                result[i] = (50.0 if gain == loss == 0 else
                             100.0 if loss == 0 else 100 - 100 / (1 + gain / loss))
        dataframe["rsi"] = Series(result, index=dataframe.index)
        dataframe["trend_sma"] = dataframe["close"].rolling(self.trend_window).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """只在长期均线之上的超卖回调买入，不做下跌趋势抄底。"""
        dataframe["enter_long"] = 0
        dataframe.loc[(dataframe["rsi"] < self.buy_below) &
                      (dataframe["close"] > dataframe["trend_sma"]) & (dataframe["volume"] > 0),
                      ["enter_long", "enter_tag"]] = (1, "rsi_pullback")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """反弹恢复RSI或跌破趋势均线均退出，允许亏损退出。"""
        dataframe["exit_long"] = 0
        dataframe.loc[((dataframe["rsi"] >= self.sell_above) |
                       (dataframe["close"] <= dataframe["trend_sma"])) & (dataframe["volume"] > 0),
                      ["exit_long", "exit_tag"]] = (1, "rsi_or_trend_exit")
        return dataframe

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs):
        """按框架记录的开仓时间计算10周期上限；不用于价格止损。"""
        duration = timedelta(minutes=self.max_hold_candles * timeframe_to_minutes(self.timeframe))
        if current_time - trade.open_date_utc >= duration:
            return "hold_timeout"
        return None

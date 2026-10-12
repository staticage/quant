"""S03 布林带反弹，Freqtrade现货做多，默认20根/2倍总体标准差。

close跌破下轨时入场；close回到中轨退出；开仓20个日线周期后时间退出。
固定stoploss默认-0.05、可由运行配置覆盖，由Freqtrade基于实际开仓管理，不再用信号收盘作参考价。
止损执行与日线高低价撮合遵循Freqtrade；滑点可能导致损失超过5%。
禁用ROI和移动止损；仓位配置不在策略里。下轨跌破可能预示持续下跌，
并不保证反弹。参考：https://www.bollingerbands.com/bollinger-bands
反向交易、20周期退出及5%止损为本库自定义，不是官方完整交易系统。
"""

from datetime import datetime, timedelta
from pandas import DataFrame
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, timeframe_to_minutes


class S03BollingerReversion(IStrategy):
    """指标退出用向量信号，持仓年龄退出用custom_exit。"""

    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 20
    minimal_roi = {}
    stoploss = -0.05  # 默认固定止损5%，回测配置stoploss可覆盖；执行由Freqtrade负责。
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    band_window = 20
    band_width = 2.0
    max_hold_candles = 20

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """总体标准差ddof=0；窗口含已结束的当前K线，零波动不入场。"""
        window = dataframe["close"].rolling(self.band_window)
        dataframe["bb_middle"] = window.mean()
        dataframe["bb_std"] = window.std(ddof=0)
        dataframe["bb_lower"] = dataframe["bb_middle"] - self.band_width * dataframe["bb_std"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """下轨外尝试反弹；有成交量且标准差>0，完整预热由框架处理。"""
        dataframe["enter_long"] = 0
        dataframe.loc[(dataframe["close"] < dataframe["bb_lower"]) &
                      (dataframe["bb_std"] > 0) & (dataframe["volume"] > 0),
                      ["enter_long", "enter_tag"]] = (1, "below_lower_band")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """回到或越过动态中轨即退出；固定止损独立于这个信号。"""
        dataframe["exit_long"] = 0
        dataframe.loc[(dataframe["close"] >= dataframe["bb_middle"]) &
                      (dataframe["volume"] > 0), ["exit_long", "exit_tag"]] = (1, "return_to_mean")
        return dataframe

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs):
        """从trade.open_date_utc计时，20周期后退出；不依赖信号日价格。

        实际检查频率由框架控制；时间退出不是保证在精确时刻成交。
        回调不读取整份历史的末行，避免回测读取未来K线。
        """
        duration = timedelta(minutes=self.max_hold_candles * timeframe_to_minutes(self.timeframe))
        if current_time - trade.open_date_utc >= duration:
            return "hold_timeout"
        return None

"""S09 BTC趋势过滤ETH交易，Freqtrade interface v3，现货只做多。

这是本项目的跨资产方向过滤研究规则，不是配对套利、轮动或BTC领先ETH的保证。
BTC/USDT只作为同交易所参考行情，唯一交易对象为ETH/USDT，BTC不产生订单。
默认BTC日线MACD(12,26,9)：DIF>DEA且DIF>0时允许买ETH；可选只检查其中一项。
ETH默认小时线MACD(12,26,9)：DIF上穿DEA发出买入信号，且BTC趋势必须同时允许。
DIF=EMA(close,fast)-EMA(close,slow)，DEA=EMA(DIF,signal)，柱体=2*(DIF-DEA)。
两个资产各自用TA-Lib计算，不把BTC价格当作ETH价格；EMA采用TA-Lib初始化。
预热由运行脚本按两套MACD的5*(slow+signal)最大值安排，两个资产都检查覆盖。
BTC周期必须不短于ETH信号周期；merge_informative_pair按K线结束可用时间合并，
只能使用已结束的BTC K线，不能提前读取当日未收盘的BTC日线。
ETH死叉退出；默认同时开启BTC趋势转弱退出，可关闭该额外退出，只保留ETH死叉。
固定10%框架止损为额外风控，不设ROI与移动止盈；信号成交按Freqtrade后续K线语义。
BTC缺失/预热无效时不入场；趋势退出也不凭NaN发出。缺失完整行情由脚本拒绝回测。
ETH金叉被过滤后等待下一次金叉，不因BTC后来转强就补买；持仓由框架管理。
适用于研究大盘趋势与ETH动量的关系。BTC/ETH可能解耦，ETH有独立风险，
震荡假交叉、趋势滞后、跳空、滑点及手续费可能造成亏损，止损不能保证损失封顶。
未完成真实行情绩效回测，不声称收益或胜率提高；不支持其他交易对或实盘授权。
"""
import talib.abstract as ta
from pandas import DataFrame, Timedelta
from freqtrade.strategy import (IStrategy, IntParameter, CategoricalParameter, BooleanParameter,
                                merge_informative_pair, timeframe_to_minutes)


class S09BtcTrendEth(IStrategy):
    """BTC作为informative pair，所有进出场信号仅供ETH现货使用。"""
    INTERFACE_VERSION = 3
    timeframe = "1h"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 175
    minimal_roi = {}  # 不设独立止盈，死叉/趋势反转/框架止损退出。
    stoploss = -0.10
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    macd_fast = IntParameter(2, 399, default=12, space="buy", optimize=False)
    macd_slow = IntParameter(3, 400, default=26, space="buy", optimize=False)
    macd_signal = IntParameter(2, 100, default=9, space="buy", optimize=False)
    btc_timeframe = CategoricalParameter(["4h", "1d"], default="1d", space="buy", optimize=False)
    btc_mode = CategoricalParameter(["dif_dea", "zero", "both"], default="both", space="buy", optimize=False)
    btc_fast = IntParameter(2, 399, default=12, space="buy", optimize=False)
    btc_slow = IntParameter(3, 400, default=26, space="buy", optimize=False)
    btc_signal = IntParameter(2, 100, default=9, space="buy", optimize=False)
    btc_exit = BooleanParameter(default=True, space="sell", optimize=False)

    def informative_pairs(self):
        """声明BTC参考行情，同一交易所，周期不短于ETH信号周期。"""
        if timeframe_to_minutes(self.btc_timeframe.value) < timeframe_to_minutes(self.timeframe):
            raise ValueError("BTC趋势周期不能短于ETH入场周期")
        return [("BTC/USDT", self.btc_timeframe.value)]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """分别计算ETH与BTC指标，按已发布的BTC收盘时间对齐ETH。"""
        if metadata["pair"] != "ETH/USDT":
            raise ValueError("S09只允许交易ETH/USDT，BTC仅为参考行情")
        self.informative_pairs()
        if self.macd_fast.value >= self.macd_slow.value or self.btc_fast.value >= self.btc_slow.value:
            raise ValueError("两套MACD快线周期均须小于慢线")
        eth = ta.MACD(dataframe, fastperiod=self.macd_fast.value,
                       slowperiod=self.macd_slow.value, signalperiod=self.macd_signal.value)
        dataframe["dif"], dataframe["dea"] = eth["macd"], eth["macdsignal"]
        dataframe["macd_hist"] = 2 * eth["macdhist"]
        if not self.dp:
            raise ValueError("S09需要Freqtrade DataProvider提供BTC行情")
        tf = self.btc_timeframe.value
        btc = self.dp.get_pair_dataframe(pair="BTC/USDT", timeframe=tf).copy()
        if btc.empty:
            raise ValueError("缺少BTC/USDT参考行情")
        trend = ta.MACD(btc, fastperiod=self.btc_fast.value,
                       slowperiod=self.btc_slow.value, signalperiod=self.btc_signal.value)
        btc["btc_dif"], btc["btc_dea"] = trend["macd"], trend["macdsignal"]
        # 加上volume，暂停/零量参考K线不能作为有效趋势。
        dataframe = merge_informative_pair(dataframe, btc[["date", "btc_dif", "btc_dea", "volume"]],
                                           self.timeframe, tf, ffill=True)
        if not dataframe.empty:
            # 只取首根ETH结束前已发布的最后一根BTC；保持短前缀与完整历史一致。
            first_close = dataframe["date"].iloc[0] + Timedelta(minutes=timeframe_to_minutes(self.timeframe))
            published = btc[btc["date"] + Timedelta(minutes=timeframe_to_minutes(tf)) <= first_close]
            if not published.empty:
                seed = published.iloc[-1]
                missing = dataframe[f"date_{tf}"].isna()
                for col in ("date", "btc_dif", "btc_dea", "volume"):
                    dataframe.loc[missing, f"{col}_{tf}"] = seed[col]
        dif, dea = dataframe[f"btc_dif_{tf}"], dataframe[f"btc_dea_{tf}"]
        dataframe["btc_valid"] = dif.notna() & dea.notna() & (dataframe[f"volume_{tf}"] > 0)
        up = dataframe["btc_valid"].copy()
        if self.btc_mode.value in ("dif_dea", "both"):
            up &= dif > dea
        if self.btc_mode.value in ("zero", "both"):
            up &= dif > 0
        dataframe["btc_trend_up"] = up
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """ETH金叉与BTC允许做多同时满足才入场，交易对象由前置校验限制。"""
        dataframe["enter_long"] = 0
        allowed = ((dataframe["dif"] > dataframe["dea"]) &
                   (dataframe["dif"].shift(1) <= dataframe["dea"].shift(1)) &
                   dataframe["btc_trend_up"] & (dataframe["volume"] > 0))
        dataframe.loc[allowed, ["enter_long", "enter_tag"]] = (1, "eth_macd_btc_up")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """ETH死叉始终退出；可选BTC有效趋势转弱退出，NaN不伪造趋势反转。"""
        dataframe["exit_long"] = 0
        if self.btc_exit.value:
            dataframe.loc[dataframe["btc_valid"] & ~dataframe["btc_trend_up"] & (dataframe["volume"] > 0),
                          ["exit_long", "exit_tag"]] = (1, "btc_trend_lost")
        death = ((dataframe["dif"] < dataframe["dea"]) &
                 (dataframe["dif"].shift(1) >= dataframe["dea"].shift(1)) & (dataframe["volume"] > 0))
        dataframe.loc[death, ["exit_long", "exit_tag"]] = (1, "eth_macd_death_cross")
        return dataframe

"""S09 BTC信号交易ETH，Freqtrade interface v3，现货只做多。

BTC/USDT为唯一信号来源，ETH/USDT为唯一交易对象；BTC不产生订单。
默认BTC日线MACD(12,26,9)：DIF上穿DEA买入ETH，下穿DEA卖出ETH。
DIF=EMA(BTC.close,fast)-EMA(BTC.close,slow)，DEA=EMA(DIF,signal)，柱体=2*(DIF-DEA)。
使用TA-Lib初始化，MACD预热5*(slow+signal)根；ETH不计算MACD或其他方向指标。
BTC周期可选1h/4h/1d，ETH执行周期不得长于BTC信号周期；默认1h执行、5m成交细化。
在BTC原周期先计算交叉事件，再按BTC K线结束时间合并到ETH执行K线。
一个BTC事件只在其首次可见的ETH执行K线上触发一次，不能在填充后的小时线重复买入。
ETH仅提供成交价格及有成交量保护，不需要ETH金叉，也不以ETH死叉卖出。
仅使用已结束BTC K线；信号之后由Freqtrade处理ETH成交，不按BTC价格撮合ETH。
固定10%ETH止损是额外风控，仍可在BTC死叉前止损；不设ROI与移动止盈。
止损退出后等待下一次BTC金叉，不因BTC仍处于多头状态而重新入场。
缺失BTC行情直接报错；指标NaN不发信号；BTC/ETH完整行情与预热由运行脚本审计。
这不是套利或BTC领先ETH的保证，两个资产可能解耦，ETH独立下跌时BTC信号可能滞后。
震荡交叉、手续费、滑点、跳空均可造成亏损；固定止损不能保证损失封顶。
末尾可能按Freqtrade force_exit处理；未完成真实行情绩效回测，不声称提高收益。
旧S09 BTC过滤+ETH金叉版本的历史记录保留原参数，不解释成此版本的绩效。
"""
import talib.abstract as ta
from pandas import DataFrame, Timedelta
from freqtrade.strategy import (IStrategy, IntParameter, CategoricalParameter,
                                merge_informative_pair, timeframe_to_minutes)


class S09BtcTrendEth(IStrategy):
    """BTC作为informative pair提供进出场事件，框架只交易ETH现货。"""
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
    btc_timeframe = CategoricalParameter(["1h", "4h", "1d"], default="1d", space="buy", optimize=False)
    btc_fast = IntParameter(2, 399, default=12, space="buy", optimize=False)
    btc_slow = IntParameter(3, 400, default=26, space="buy", optimize=False)
    btc_signal = IntParameter(2, 100, default=9, space="buy", optimize=False)

    def informative_pairs(self):
        """声明BTC参考行情，同一交易所，周期不短于ETH信号周期。"""
        if timeframe_to_minutes(self.btc_timeframe.value) < timeframe_to_minutes(self.timeframe):
            raise ValueError("BTC趋势周期不能短于ETH入场周期")
        return [("BTC/USDT", self.btc_timeframe.value)]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """只在BTC原周期计算指标/交叉，ETH仅提供执行时间与成交数据。"""
        if metadata["pair"] != "ETH/USDT":
            raise ValueError("S09只允许交易ETH/USDT，BTC仅为参考行情")
        self.informative_pairs()
        if self.btc_fast.value >= self.btc_slow.value:
            raise ValueError("BTC MACD快线周期须小于慢线")
        if not self.dp:
            raise ValueError("S09需要Freqtrade DataProvider提供BTC行情")
        tf = self.btc_timeframe.value
        btc = self.dp.get_pair_dataframe(pair="BTC/USDT", timeframe=tf).copy()
        if btc.empty:
            raise ValueError("缺少BTC/USDT参考行情")
        trend = ta.MACD(btc, fastperiod=self.btc_fast.value,
                       slowperiod=self.btc_slow.value, signalperiod=self.btc_signal.value)
        btc["btc_dif"], btc["btc_dea"] = trend["macd"], trend["macdsignal"]
        # 在BTC原始周期计算交叉，避免把填充后的长周期状态误作持续入场条件。
        dif, dea = btc["btc_dif"], btc["btc_dea"]
        valid = dif.notna() & dea.notna() & (btc["volume"] > 0)
        btc["btc_buy_event"] = valid & (dif > dea) & (dif.shift(1) <= dea.shift(1))
        btc["btc_sell_event"] = valid & (dif < dea) & (dif.shift(1) >= dea.shift(1))
        dataframe = merge_informative_pair(dataframe, btc[["date", "btc_dif", "btc_dea", "volume", "btc_buy_event", "btc_sell_event"]],
                                           self.timeframe, tf, ffill=True)
        if not dataframe.empty:
            # 只取首根ETH结束前已发布的最后一根BTC；保持短前缀与完整历史一致。
            first_close = dataframe["date"].iloc[0] + Timedelta(minutes=timeframe_to_minutes(self.timeframe))
            published = btc[btc["date"] + Timedelta(minutes=timeframe_to_minutes(tf)) <= first_close]
            if not published.empty:
                seed = published.iloc[-1]
                missing = dataframe[f"date_{tf}"].isna()
                for col in ("date", "btc_dif", "btc_dea", "volume", "btc_buy_event", "btc_sell_event"):
                    dataframe.loc[missing, f"{col}_{tf}"] = seed[col]
        # 历史数据首行不重放更早已发生的BTC信号；仅新的BTC收盘发布时执行。
        published_date = dataframe[f"date_{tf}"]
        new_btc = published_date.notna() & published_date.shift(1).notna() & published_date.ne(published_date.shift(1))
        dataframe["btc_entry_signal"] = new_btc & dataframe[f"btc_buy_event_{tf}"].eq(True)
        dataframe["btc_exit_signal"] = new_btc & dataframe[f"btc_sell_event_{tf}"].eq(True)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """BTC新金叉买ETH，仅触发一次；ETH成交量>0是执行保护，不是方向信号。"""
        dataframe["enter_long"] = 0
        dataframe.loc[dataframe["btc_entry_signal"] & (dataframe["volume"] > 0),
                      ["enter_long", "enter_tag"]] = (1, "btc_macd_golden_cross")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """BTC新死叉卖ETH，不依赖ETH的价格趋势或MACD。"""
        dataframe["exit_long"] = 0
        dataframe.loc[dataframe["btc_exit_signal"] & (dataframe["volume"] > 0),
                      ["exit_long", "exit_tag"]] = (1, "btc_macd_death_cross")
        return dataframe

"""S09 BTC信号交易ETH，Freqtrade interface v3，现货只做多。

BTC/USDT为唯一信号来源，ETH/USDT为唯一交易对象；BTC不产生订单。
BTC信号来源单选：MACD（默认）或双SMA均线。
MACD默认12/26/9：DIF上穿DEA买入ETH，下穿DEA卖出ETH。
双均线默认SMA20/60：短均线>长均线时买ETH，短均线<=长均线时卖ETH，沿用S01关系规则。
SMA为含当根收盘的N根算术均值，未满窗口为NaN；预热取长均线窗口。
双均线在每根新BTC K线上判断一次，止损后BTC仍多头时，下一根BTC K线可能再次买入；
这与MACD只等待下一个金叉的事件规则不同，界面和历史需记录所选策略。
DIF=EMA(BTC.close,fast)-EMA(BTC.close,slow)，DEA=EMA(DIF,signal)，柱体=2*(DIF-DEA)。
使用TA-Lib初始化，MACD预热5*(slow+signal)根；ETH不计算MACD或其他方向指标。
可选ATR偏离控制默认关闭：在BTC信号周期计算EMA(默认20)、ATR(默认14)，
偏离=(BTC.close-EMA)/ATR，超过默认2倍阈值时仍入场，但仅投入计划金额的默认30%。
ATR使用TA-Lib的Wilder平滑，TR=max(high-low,abs(high-prev_close),abs(low-prev_close))。
开启时EMA/ATR未就绪或ATR<=0不入场；预热至少5*max(EMA周期,ATR周期)+1。
偏离只改变初始仓位，不新增趋势过滤、回落等待、加仓或ATR止损；退出/固定止损不变。
减仓标签在已结束BTC信号K线上确定，通过原生custom_stake_amount执行，避免读取未来行情。
小额仓位低于交易所最小下单金额时跳过，不能自动放大仓位；框架仍可按精度调整实际投入。
该选项降低追高金额，但不能识别顶部或保证盈利，也不能识别ETH自身过热。
BTC周期可选1h/4h/1d，ETH执行周期不得长于BTC信号周期；默认1h执行、5m成交细化。
在BTC原周期先计算交叉事件，再按BTC K线结束时间合并到ETH执行K线。
一个BTC事件只在其首次可见的ETH执行K线上触发一次，不能在填充后的小时线重复买入。
ETH仅提供成交价格及有成交量保护，不需要ETH金叉，也不以ETH死叉卖出。
仅使用已结束BTC K线；信号之后由Freqtrade处理ETH成交，不按BTC价格撮合ETH。
默认10%ETH固定止损是额外风控，仍可在BTC死叉前止损；不设ROI与移动止盈。
MACD止损后等待新金叉；双均线可在下一根BTC多头K线重入，均由框架管理持仓。
缺失BTC行情直接报错；指标NaN不发信号；BTC/ETH完整行情与预热由运行脚本审计。
这不是套利或BTC领先ETH的保证，两个资产可能解耦，ETH独立下跌时BTC信号可能滞后。
震荡交叉、手续费、滑点、跳空均可造成亏损；固定止损不能保证损失封顶。
末尾可能按Freqtrade force_exit处理；已有默认MACD报告，新增SMA未做绩效回测，不声称提高收益。
旧S09 BTC过滤+ETH金叉版本的历史记录保留原参数，不解释成此版本的绩效。
"""
import talib.abstract as ta
from pandas import DataFrame, Timedelta
from freqtrade.strategy import (IStrategy, IntParameter, CategoricalParameter, BooleanParameter, DecimalParameter,
                                merge_informative_pair, timeframe_to_minutes)


class S09BtcTrendEth(IStrategy):
    """BTC作为informative pair提供进出场事件，框架只交易ETH现货。"""
    INTERFACE_VERSION = 3
    timeframe = "1h"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 175
    minimal_roi = {}  # 不设独立止盈，死叉/趋势反转/框架止损退出。
    stoploss = -0.10  # 默认固定止损10%，回测配置stoploss可覆盖；执行由Freqtrade负责。
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    btc_strategy = CategoricalParameter(["macd", "sma"], default="macd", space="buy", optimize=False)
    btc_ma_fast = IntParameter(2, 399, default=20, space="buy", optimize=False)
    btc_ma_slow = IntParameter(3, 400, default=60, space="buy", optimize=False)
    btc_timeframe = CategoricalParameter(["1h", "4h", "1d"], default="1d", space="buy", optimize=False)
    btc_fast = IntParameter(2, 399, default=12, space="buy", optimize=False)
    btc_slow = IntParameter(3, 400, default=26, space="buy", optimize=False)
    btc_signal = IntParameter(2, 100, default=9, space="buy", optimize=False)
    btc_atr_enabled = BooleanParameter(default=False, space="buy", optimize=False)
    btc_atr_period = IntParameter(2, 100, default=14, space="buy", optimize=False)
    btc_atr_ema_period = IntParameter(2, 400, default=20, space="buy", optimize=False)
    btc_atr_threshold = DecimalParameter(0.1, 20, default=2.0, decimals=2, space="buy", optimize=False)
    btc_atr_stake_percent = DecimalParameter(1, 100, default=30, decimals=2, space="buy", optimize=False)

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
        if self.btc_strategy.value == "macd" and self.btc_fast.value >= self.btc_slow.value:
            raise ValueError("BTC MACD快线周期须小于慢线")
        if not self.dp:
            raise ValueError("S09需要Freqtrade DataProvider提供BTC行情")
        tf = self.btc_timeframe.value
        btc = self.dp.get_pair_dataframe(pair="BTC/USDT", timeframe=tf).copy()
        if btc.empty:
            raise ValueError("缺少BTC/USDT参考行情")
        if self.btc_strategy.value == "macd":
            trend = ta.MACD(btc, fastperiod=self.btc_fast.value,
                           slowperiod=self.btc_slow.value, signalperiod=self.btc_signal.value)
            btc["btc_dif"], btc["btc_dea"] = trend["macd"], trend["macdsignal"]
            dif, dea = btc["btc_dif"], btc["btc_dea"]
            valid = dif.notna() & dea.notna() & (btc["volume"] > 0)
            btc["btc_buy_event"] = valid & (dif > dea) & (dif.shift(1) <= dea.shift(1))
            btc["btc_sell_event"] = valid & (dif < dea) & (dif.shift(1) >= dea.shift(1))
            indicator_columns = ["btc_dif", "btc_dea"]
        elif self.btc_strategy.value == "sma":
            if self.btc_ma_fast.value >= self.btc_ma_slow.value:
                raise ValueError("BTC短均线窗口须小于长均线")
            btc["btc_sma_fast"] = btc["close"].rolling(self.btc_ma_fast.value).mean()
            btc["btc_sma_slow"] = btc["close"].rolling(self.btc_ma_slow.value).mean()
            fast, slow = btc["btc_sma_fast"], btc["btc_sma_slow"]
            valid = fast.notna() & slow.notna() & (btc["volume"] > 0)
            # 沿用S01关系规则，不冒充只在均线首次交叉买入。
            btc["btc_buy_event"] = valid & (fast > slow)
            btc["btc_sell_event"] = valid & (fast <= slow)
            indicator_columns = ["btc_sma_fast", "btc_sma_slow"]
        else:
            raise ValueError("BTC信号策略只支持macd或sma")
        if self.btc_atr_enabled.value:
            # 仅在BTC原周期计算，以同一已收盘K线上的偏离确定本次ETH入场金额。
            btc["btc_atr"] = ta.ATR(btc, timeperiod=self.btc_atr_period.value)
            btc["btc_atr_ema"] = ta.EMA(btc, timeperiod=self.btc_atr_ema_period.value)
            btc["btc_atr_deviation"] = (btc["close"] - btc["btc_atr_ema"]) / btc["btc_atr"].where(btc["btc_atr"] > 0)
            indicator_columns += ["btc_atr", "btc_atr_ema", "btc_atr_deviation"]
        merge_columns = ["date", *indicator_columns, "volume", "btc_buy_event", "btc_sell_event"]
        dataframe = merge_informative_pair(dataframe, btc[merge_columns],
                                           self.timeframe, tf, ffill=True)
        if not dataframe.empty:
            # 只取首根ETH结束前已发布的最后一根BTC；保持短前缀与完整历史一致。
            first_close = dataframe["date"].iloc[0] + Timedelta(minutes=timeframe_to_minutes(self.timeframe))
            published = btc[btc["date"] + Timedelta(minutes=timeframe_to_minutes(tf)) <= first_close]
            if not published.empty:
                seed = published.iloc[-1]
                missing = dataframe[f"date_{tf}"].isna()
                for col in merge_columns:
                    dataframe.loc[missing, f"{col}_{tf}"] = seed[col]
        # 历史数据首行不重放更早已发生的BTC信号；仅新的BTC收盘发布时执行。
        published_date = dataframe[f"date_{tf}"]
        new_btc = published_date.notna() & published_date.shift(1).notna() & published_date.ne(published_date.shift(1))
        dataframe["btc_entry_signal"] = new_btc & dataframe[f"btc_buy_event_{tf}"].eq(True)
        dataframe["btc_exit_signal"] = new_btc & dataframe[f"btc_sell_event_{tf}"].eq(True)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """BTC选定策略的买入条件在每根新BTC K线判断一次；ETH成交量>0是执行保护，不是方向信号。"""
        dataframe["enter_long"] = 0
        entry = dataframe["btc_entry_signal"] & (dataframe["volume"] > 0)
        tag = "btc_macd_golden_cross" if self.btc_strategy.value == "macd" else "btc_sma_up"
        if self.btc_atr_enabled.value:
            deviation = dataframe[f"btc_atr_deviation_{self.btc_timeframe.value}"]
            entry = entry & deviation.notna()
            dataframe.loc[entry & (deviation > self.btc_atr_threshold.value),
                          ["enter_long", "enter_tag"]] = (1, tag + "_atr_reduced")
            entry = entry & (deviation <= self.btc_atr_threshold.value)
        dataframe.loc[entry, ["enter_long", "enter_tag"]] = (1, tag)
        return dataframe

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake,
                            min_stake, max_stake, leverage, entry_tag, side, **kwargs):
        """原生初始仓位回调：只按已生成的入场标签减仓，绝不按当前/未来价格重判信号。"""
        if not self.btc_atr_enabled.value or not (entry_tag or "").endswith("_atr_reduced"):
            return proposed_stake
        stake = min(proposed_stake * float(self.btc_atr_stake_percent.value) / 100, max_stake)
        # 返回0让Freqtrade跳过，防止原生最小金额钳制把试探仓位放大。
        return 0 if min_stake is not None and stake < min_stake else stake

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """BTC选定策略的退出条件卖ETH，不依赖ETH方向指标。"""
        dataframe["exit_long"] = 0
        dataframe.loc[dataframe["btc_exit_signal"] & (dataframe["volume"] > 0),
                      ["exit_long", "exit_tag"]] = (1, "btc_macd_death_cross" if self.btc_strategy.value == "macd" else "btc_sma_down")
        return dataframe

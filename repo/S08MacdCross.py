"""S08 MACD金叉死叉及可选过滤，Freqtrade interface v3，现货只做多。

来源：https://www.myinvestpilot.com/docs/strategies/macd-strategy
基础规则：DIF上穿DEA买入，下穿卖出；默认12/26/9，全部增强默认关闭。
DIF=EMA(close, fast)-EMA(close, slow)，DEA=EMA(DIF, signal)，柱体=2*(DIF-DEA)。
EMA及RSI由TA-Lib计算，保留其初始化语义；MACD预热5*(slow+signal)根。
可选增强是本项目对来源建议的量化定义，并非来源提供的完整交易系统：
1. 多时间框架：短周期MACD金叉入场，长周期已结束K线的MACD方向过滤。
   长周期可选DIF>DEA、DIF>0、或两者同时满足；两套MACD窗口各自可调。
   使用Freqtrade merge_informative_pair对齐收盘可用时间，不能提前读取长K线。
2. RSI区间：入场时RSI在[下限,上限]（默认30~70），可调周期，排除区间外信号。
   RSI=100-100/(1+平均上涨/平均下跌)，TA-Lib采用Wilder平滑，预热5*period+1。
   这不是单独的RSI超卖反弹策略，也不新增RSI止盈。
3. 均线：入场收盘价严格高于所选EMA/SMA（默认EMA200），单位为入场周期K线数。
   EMA预热5*period，SMA预热period；EMA有初始化递归误差，需分析稳定性。
4. 成交量：当前已结束K线volume >= 此前N根平均volume * 倍数（默认20/1.2）。
   历史均量先rolling再shift(1)，不把当根放大成交量混入基准，基准须>0。
所有开启的过滤器与本根金叉同时满足才买入；错过被过滤金叉后等下一次金叉。
过滤器只限制入场，不拦截死叉退出；默认10%固定止损为额外研究风控，不设ROI。
仓位由框架配置决定；不做空、不加仓、不实现未定义的背离或支撑位判断。
5分钟成交细化不是短周期信号，它仅用于Freqtrade盘中撮合及止损评估。
适用趋势市场，横盘可能反复亏损；增加过滤可能错过机会，不能保证提高胜率。
仅使用已结束K线，框架在信号之后处理成交，不假设信号当根收盘成交。
跳空/滑点可能突破止损，末尾持仓可能按框架force_exit处理；禁止实盘启动。
"""

import talib.abstract as ta
from pandas import DataFrame, Timedelta
from freqtrade.strategy import (IStrategy, IntParameter, DecimalParameter, BooleanParameter,
                                CategoricalParameter, merge_informative_pair, timeframe_to_minutes)


class S08MacdCross(IStrategy):
    """所有窗口/开关通过Freqtrade原生参数JSON加载，配置及资金由框架管理。"""

    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 175
    minimal_roi = {}  # 退出使用死叉与框架固定止损，不加独立ROI止盈。
    stoploss = -0.10  # 默认固定止损10%，回测配置stoploss可覆盖；执行由Freqtrade负责。
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    macd_fast = IntParameter(2, 399, default=12, space="buy", optimize=False)
    macd_slow = IntParameter(3, 400, default=26, space="buy", optimize=False)
    macd_signal = IntParameter(2, 100, default=9, space="buy", optimize=False)
    mtf_enabled = BooleanParameter(default=False, space="buy", optimize=False)
    trend_timeframe = CategoricalParameter(["4h", "1d"], default="1d", space="buy", optimize=False)
    trend_mode = CategoricalParameter(["dif_dea", "zero", "both"], default="dif_dea", space="buy", optimize=False)
    trend_fast = IntParameter(2, 399, default=12, space="buy", optimize=False)
    trend_slow = IntParameter(3, 400, default=26, space="buy", optimize=False)
    trend_signal = IntParameter(2, 100, default=9, space="buy", optimize=False)
    rsi_enabled = BooleanParameter(default=False, space="buy", optimize=False)
    rsi_period = IntParameter(2, 100, default=14, space="buy", optimize=False)
    rsi_min = IntParameter(0, 99, default=30, space="buy", optimize=False)
    rsi_max = IntParameter(1, 100, default=70, space="buy", optimize=False)
    ma_enabled = BooleanParameter(default=False, space="buy", optimize=False)
    ma_type = CategoricalParameter(["ema", "sma"], default="ema", space="buy", optimize=False)
    ma_period = IntParameter(2, 400, default=200, space="buy", optimize=False)
    volume_enabled = BooleanParameter(default=False, space="buy", optimize=False)
    volume_window = IntParameter(2, 400, default=20, space="buy", optimize=False)
    volume_multiplier = DecimalParameter(0.1, 10.0, default=1.2, decimals=2, space="buy", optimize=False)

    def informative_pairs(self):
        """只有开启多周期才向框架请求长周期行情，避免关闭状态改变原始口径。"""
        if not self.mtf_enabled.value:
            return []
        if timeframe_to_minutes(self.trend_timeframe.value) <= timeframe_to_minutes(self.timeframe):
            raise ValueError("趋势周期必须长于入场信号周期")
        if not self.dp:
            raise ValueError("多时间框架需要Freqtrade DataProvider")
        return [(pair, self.trend_timeframe.value) for pair in self.dp.current_whitelist()]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """历史指标保留NaN；长周期指标计算后按结束时间安全合并，不能向前补值。"""
        if self.macd_fast.value >= self.macd_slow.value:
            raise ValueError("MACD快线周期必须小于慢线周期")
        result = ta.MACD(dataframe, fastperiod=self.macd_fast.value,
                         slowperiod=self.macd_slow.value, signalperiod=self.macd_signal.value)
        dataframe["dif"], dataframe["dea"] = result["macd"], result["macdsignal"]
        dataframe["macd_hist"] = 2 * result["macdhist"]
        if self.rsi_enabled.value:
            if self.rsi_min.value >= self.rsi_max.value:
                raise ValueError("RSI下限必须小于上限")
            dataframe["filter_rsi"] = ta.RSI(dataframe, timeperiod=self.rsi_period.value)
        if self.ma_enabled.value:
            function = ta.EMA if self.ma_type.value == "ema" else ta.SMA
            dataframe["filter_ma"] = function(dataframe, timeperiod=self.ma_period.value)
        if self.volume_enabled.value:
            dataframe["prior_volume_mean"] = dataframe["volume"].rolling(self.volume_window.value).mean().shift(1)
        if self.mtf_enabled.value:
            self.informative_pairs()  # 再次校验周期关系，直接调用也不能绕过。
            if self.trend_fast.value >= self.trend_slow.value:
                raise ValueError("长周期MACD快线必须小于慢线")
            tf = self.trend_timeframe.value
            informative = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe=tf).copy()
            if informative.empty:
                raise ValueError(f"缺少{metadata['pair']} {tf}长周期行情")
            trend = ta.MACD(informative, fastperiod=self.trend_fast.value,
                           slowperiod=self.trend_slow.value, signalperiod=self.trend_signal.value)
            informative["trend_dif"], informative["trend_dea"] = trend["macd"], trend["macdsignal"]
            dataframe = merge_informative_pair(dataframe, informative[["date", "trend_dif", "trend_dea"]],
                                               self.timeframe, tf, ffill=True)
            # 当前框架helper在短历史前缀尚无长K线对齐行时，不会填入此前已结束的长K线。
            # 用首根短K线结束前已经发布的最后一根长K线确定性补齐初始缺失，
            # 不依赖将来是否出现首个对齐行；先按收盘可用时间筛选再取最后一根。
            if not dataframe.empty:
                first_close = dataframe["date"].iloc[0] + Timedelta(minutes=timeframe_to_minutes(self.timeframe))
                published = informative[informative["date"] + Timedelta(minutes=timeframe_to_minutes(tf)) <= first_close]
                if not published.empty:
                    seed = published.iloc[-1]
                    initial_missing = dataframe[f"date_{tf}"].isna()
                    for col in ("date", "trend_dif", "trend_dea"):
                        dataframe.loc[initial_missing, f"{col}_{tf}"] = seed[col]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """金叉为必要触发；启用的过滤器逐项AND，全部关闭即原始金叉规则。"""
        dataframe["enter_long"] = 0
        allowed = ((dataframe["dif"] > dataframe["dea"]) &
                   (dataframe["dif"].shift(1) <= dataframe["dea"].shift(1)) & (dataframe["volume"] > 0))
        if self.mtf_enabled.value:
            tf = self.trend_timeframe.value
            dif, dea = dataframe[f"trend_dif_{tf}"], dataframe[f"trend_dea_{tf}"]
            allowed &= dif.notna() & dea.notna()
            if self.trend_mode.value in ("dif_dea", "both"):
                allowed &= dif > dea
            if self.trend_mode.value in ("zero", "both"):
                allowed &= dif > 0
        if self.rsi_enabled.value:
            allowed &= dataframe["filter_rsi"].between(self.rsi_min.value, self.rsi_max.value)
        if self.ma_enabled.value:
            allowed &= dataframe["close"] > dataframe["filter_ma"]
        if self.volume_enabled.value:
            allowed &= (dataframe["prior_volume_mean"] > 0) & (dataframe["volume"] >=
                        dataframe["prior_volume_mean"] * self.volume_multiplier.value)
        dataframe.loc[allowed, ["enter_long", "enter_tag"]] = (1, "macd_golden_cross")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """所有过滤器只作用于入场；上一根DIF>=DEA且本根DIF<DEA时仍死叉退出。"""
        dataframe["exit_long"] = 0
        dataframe.loc[(dataframe["dif"] < dataframe["dea"]) &
                      (dataframe["dif"].shift(1) >= dataframe["dea"].shift(1)) &
                      (dataframe["volume"] > 0), ["exit_long", "exit_tag"]] = (1, "macd_death_cross")
        return dataframe

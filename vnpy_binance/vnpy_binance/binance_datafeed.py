from datetime import datetime, timedelta
from typing import List, Optional, Callable
from decimal import Decimal

import logging
from weakref import proxy
logging.basicConfig(level=logging.INFO)

from binance.spot import Spot
import pandas as pd
from pandas import DataFrame, Timestamp
from vnpy.trader.datafeed import BaseDatafeed
from vnpy.trader.setting import SETTINGS
from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData, HistoryRequest
from vnpy.trader.utility import ZoneInfo

INTERVAL_VT2BINANCE: dict = {
    Interval.MINUTE: "1m",
    Interval.HOUR: "1h",
    Interval.DAILY: "1d",
    Interval.WEEKLY: "1w",
}

CHINA_TZ = ZoneInfo("Asia/Shanghai")
UTC_TZ = ZoneInfo("UTC")

class BinanceDatafeed(BaseDatafeed):
    print('BTCUSDT.BINANCE')
    """币安数据服务接口"""

    def __init__(self):
        """构造函数"""
        self.api_key: str = SETTINGS.get("datafeed.api_key", "77VqyxrjpGfX0F6QSVj9BfM6RgpCTekVOGPSYHr2IqAGQ5B7xf6XV1W90w9QRKyD")
        self.api_secret: str = SETTINGS.get("datafeed.api_secret", "4VJ2iJYbAqutncrtGtucFdoAPb6b5AmI8Ibe1K9R8kZvUsYySKUmxiNGctPxmsSU")
        
        # 初始化API对象
        self.client = Spot(
            api_key=self.api_key,
            api_secret=self.api_secret,
            proxies={"https": SETTINGS.get("datafeed.proxy", "http://127.0.0.1:7890")}
        )

    def query_bar_history(
        self, 
        req: HistoryRequest, 
        output: Callable = print
    ) -> Optional[List[BarData]]:
        """查询K线数据"""
        logging.info('Binance data feed has started.' + str(req))
        
        # 检查时间周期是否支持
        interval = INTERVAL_VT2BINANCE.get(req.interval)
        if not interval:
            output(f"Binance数据服务不支持该时间周期：{req.interval.value}")
            return []

        # 获取币对名称
        symbol = f"{req.symbol}".upper()
        
        try:
            # 转换时间格式
            start_time = int(req.start.timestamp() * 1000)
            end_time = int(req.end.timestamp() * 1000)
            
            all_data = []
            current_start = start_time
            
            while current_start < end_time:
                # 从币安接口获取数据
                data = self.client.klines(
                    symbol=symbol,
                    interval=interval,
                    startTime=current_start,
                    endTime=end_time,
                    limit=1000
                )
                
                # 如果没有数据，则退出循环
                if not data:
                    break
                    
                all_data.extend(data)
                
                # 更新开始时间为最后一条数据的时间+1
                current_start = int(data[-1][0]) + 1
                
                # 如果返回的数据少于1000条，说明已经是最后的数据了
                if len(data) < 1000:
                    break

            # 如果没有数据，则返回空列表
            if not all_data:
                output(f"未获取到币安数据：{symbol}, {interval}")
                return []

            # 创建DataFrame
            df = DataFrame(
                all_data,
                columns=[
                    "open_time",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "close_time",
                    "quote_volume",
                    "count",
                    "taker_buy_volume",
                    "taker_buy_quote_volume",
                    "ignore",
                ]
            )

            # 转换数据类型
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
            
            # 生成BarData列表
            bars: List[BarData] = []
            for row in df.itertuples():
                dt: Timestamp = Timestamp(row.open_time).to_pydatetime() + timedelta(hours=8)
                bar = BarData(
                    symbol=req.symbol,
                    exchange=Exchange.BINANCE,
                    interval=req.interval,
                    datetime=dt.replace(tzinfo=CHINA_TZ),
                    # row.open_time.replace(tzinfo=UTC_TZ),
                    open_price=float(row.open),
                    high_price=float(row.high),
                    low_price=float(row.low),
                    volume=float(row.volume),
                    close_price=float(row.close),
                    gateway_name="BINANCE"
                )
                bars.append(bar)

            return bars

        except Exception as e:
            output(f"查询币安K线数据失败：{str(e)}")
            return []

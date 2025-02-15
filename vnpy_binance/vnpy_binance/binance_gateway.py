"""
币安交易接口
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Tuple
import json
from copy import copy
import logging
import time

from binance.spot import Spot
from binance.websocket.spot.websocket_stream import SpotWebsocketStreamClient
from binance.error import ClientError

from vnpy.event import EventEngine
from vnpy.trader.constant import (
    Direction,
    Exchange,
    OrderType,
    Product,
    Status,
    Interval
)
from vnpy.trader.gateway import BaseGateway
from vnpy.trader.object import (
    TickData,
    OrderData,
    TradeData,
    AccountData,
    ContractData,
    PositionData,
    BarData,
    OrderRequest,
    CancelRequest,
    SubscribeRequest,
)
from vnpy.trader.utility import round_to
from vnpy.trader.event import EVENT_TIMER


# 常量定义
EXCHANGE_BINANCE = {Exchange.BINANCE}

STATUS_BINANCE2VT = {
    "NEW": Status.NOTTRADED,
    "PARTIALLY_FILLED": Status.PARTTRADED,
    "FILLED": Status.ALLTRADED,
    "CANCELED": Status.CANCELLED,
    "REJECTED": Status.REJECTED,
}

ORDERTYPE_VT2BINANCE = {
    OrderType.LIMIT: "LIMIT",
    OrderType.MARKET: "MARKET",
}

DIRECTION_VT2BINANCE = {
    Direction.LONG: "BUY",
    Direction.SHORT: "SELL",
}

DIRECTION_BINANCE2VT = {
    "BUY": Direction.LONG,
    "SELL": Direction.SHORT,
}


class BinanceGateway(BaseGateway):
    """
    VN Trader Gateway for Binance connection.
    """

    exchanges = list(EXCHANGE_BINANCE)

    def __init__(self, event_engine: EventEngine, gateway_name: str = "BINANCE") -> None:
        """构造函数"""
        super().__init__(event_engine, gateway_name)

        self.trade_ws_api = None
        self.market_ws_api = None
        self.client = None
        self.ticks: Dict[str, TickData] = {}
        self.order_count = 0

    def connect(self, setting: dict) -> None:
        """连接交易接口"""
        api_key = setting.get("key", "77VqyxrjpGfX0F6QSVj9BfM6RgpCTekVOGPSYHr2IqAGQ5B7xf6XV1W90w9QRKyD")
        api_secret = setting.get("secret", "4VJ2iJYbAqutncrtGtucFdoAPb6b5AmI8Ibe1K9R8kZvUsYySKUmxiNGctPxmsSU")
        proxy_host = setting.get("proxy_host", "127.0.0.1")
        proxy_port = setting.get("proxy_port", "7890")
        server = setting.get("server", "TESTNET")

        proxies = None
        if proxy_host and proxy_port:
            proxy_url = f"http://{proxy_host}:{proxy_port}"
            proxies = {"http": proxy_url, "https": proxy_url}

        # 初始化REST API
        self.client = Spot(
            api_key=api_key,
            api_secret=api_secret,
            base_url="https://testnet.binance.vision" if server == "TESTNET" else None,
            proxies=proxies
        )

        # 初始化WebSocket API
        if proxies:
            ws_proxies = {"http": proxy_url}
        else:
            ws_proxies = None

        self.market_ws_api = SpotWebsocketStreamClient(
            proxies=ws_proxies,
            on_message=self._handle_market_ws_data,
            # on_close=self._handle_ws_closed,
            # on_error=self._handle_ws_error
        )

        self.write_log("交易接口连接成功")

        # 初始化交易规则
        self.query_contract()

    def subscribe(self, req: SubscribeRequest) -> None:
        """订阅行情"""
        if not self.market_ws_api:
            self.write_log(f"行情接口未连接，无法订阅：{req.symbol}")
            return 


        
        symbol = req.symbol.lower()
        
        # 构建订阅请求

        try:
            self.market_ws_api.ticker(symbol=symbol)
            self.write_log(f"行情订阅请求发送成功：{symbol}")
        except Exception as e:
            self.write_log(f"行情订阅异常：{str(e)}")

    def _handle_market_ws_data(self, _, message: str) -> None:
        """处理WebSocket市场数据"""
        try:
            if isinstance(message, str):
                message = json.loads(message)

            # 处理订阅响应
            if "result" in message:
                if message["result"] is None:
                    self.write_log(f"订阅请求成功，ID：{message['id']}")
                return
            
            # 处理错误消息
            if "error" in message:
                self.write_log(f"WebSocket错误：{message['error']}")
                return
            

            self._handle_ticker_data(message)
            # elif "depth" in stream:  # 处理深度数据
            #     self._handle_depth_data(data)
            # elif "ticker" in stream:  # 处理Ticker数据
            #     self._handle_ticker_data(data)
                
        except Exception as e:
            self.write_log(f"处理行情数据异常：{str(e)}")
            
    def _handle_agg_trade_data(self, data: dict) -> None:
        """处理归集交易数据"""
        symbol = data["s"].lower()
        tick = self._get_tick(symbol)
        
        tick.last_price = float(data["p"])
        tick.last_volume = float(data["q"])
        tick.datetime = datetime.fromtimestamp(data["T"] / 1000)
        tick.aggregate_trade_id = int(data["a"])
        tick.first_trade_id = int(data["f"])
        tick.last_trade_id = int(data["l"])
        tick.is_market_maker = data["m"]
        
        self.on_tick(copy(tick))

    def _handle_trade_data(self, data: dict) -> None:
        """处理逐笔成交数据"""
        symbol = data["s"].lower()
        tick = self._get_tick(symbol)
        
        tick.last_price = float(data["p"])
        tick.last_volume = float(data["q"])
        tick.datetime = datetime.fromtimestamp(data["T"] / 1000)
        
        self.on_tick(copy(tick))
        
    def _handle_depth_data(self, data: dict) -> None:
        """处理深度数据"""
        symbol = data["s"].lower()
        tick = self._get_tick(symbol)
        
        # 更新买卖深度
        for i in range(min(5, len(data["bids"]))):
            price, volume = data["bids"][i]
            tick.__setattr__(f"bid_price_{i+1}", float(price))
            tick.__setattr__(f"bid_volume_{i+1}", float(volume))
            
        for i in range(min(5, len(data["asks"]))):
            price, volume = data["asks"][i]
            tick.__setattr__(f"ask_price_{i+1}", float(price))
            tick.__setattr__(f"ask_volume_{i+1}", float(volume))
            
        tick.datetime = datetime.now()
        self.on_tick(copy(tick))
        
    def _handle_ticker_data(self, data: dict) -> None:
        """处理Ticker数据"""
        # 获取交易对信息
        symbol = data["s"]
        

        # 解析行情数据
        tick = TickData(
            symbol=symbol,
            exchange=Exchange.BINANCE,
            datetime=datetime.fromtimestamp(data["E"] / 1000),
            name="BTCUSDT",
            volume=float(data["v"]),         # 成交量
            turnover=float(data["q"]),       # 成交额
            last_price=float(data["c"]),     # 最新成交价
            last_volume=float(data["Q"]),    # 最新成交量
            open_price=float(data["o"]),     # 开盘价
            high_price=float(data["h"]),     # 最高价
            low_price=float(data["l"]),      # 最低价
            bid_price_1=float(data["b"]),    # 买一价
            bid_volume_1=float(data["B"]),   # 买一量
            ask_price_1=float(data["a"]),    # 卖一价
            ask_volume_1=float(data["A"]),   # 卖一量
            gateway_name=self.gateway_name
        )
        self.on_tick(tick)

    def _handle_kline_data(self, data: dict) -> None:
        """处理K线数据"""
        symbol = data["s"].lower()
        tick = self._get_tick(symbol)
        
        kline = data["k"]
        tick.open_price = float(kline["o"])
        tick.close_price = float(kline["c"])
        tick.high_price = float(kline["h"])
        tick.low_price = float(kline["l"])
        tick.volume = float(kline["v"])
        tick.datetime = datetime.fromtimestamp(kline["T"] / 1000)
        tick.first_trade_id = int(kline["f"])
        tick.last_trade_id = int(kline["L"])
        tick.is_kline_closed = kline["x"]
        
        self.on_tick(copy(tick))

    def _handle_ws_closed(self) -> None:
        """处理WebSocket断开"""
        self.write_log("WebSocket连接断开")
        
    def _handle_ws_error(self, exception_type: type, exception_value: Exception, tb) -> None:
        """处理WebSocket异常"""
        self.write_log(f"WebSocket异常：{exception_type.__name__}: {exception_value}")
        
    def _get_tick(self, symbol: str) -> TickData:
        """获取或创建Tick对象"""
        tick = self.ticks.get(symbol)
        if not tick:
            tick = TickData(
                symbol=symbol.upper(),
                exchange=Exchange.BINANCE,
                name=symbol.upper(),
                datetime=datetime.now(),
                gateway_name=self.gateway_name,
            )
            self.ticks[symbol] = tick
            self.write_log(f"创建Tick对象：{symbol}")
        return tick

    def send_order(self, req: OrderRequest) -> str:
        """委托下单"""
        # 生成本地委托号
        self.order_count += 1
        orderid = f"{self.gateway_name}.{self.order_count}"

        try:
            # 生成委托请求
            params = {
                "symbol": req.symbol,
                "side": DIRECTION_VT2BINANCE[req.direction],
                "type": ORDERTYPE_VT2BINANCE[req.type],
                "quantity": float(req.volume)
            }

            if req.type == OrderType.LIMIT:
                params["price"] = float(req.price)
                params["timeInForce"] = "GTC"

            # 发送委托请求
            response = self.client.new_order(**params)

            # 推送委托数据
            order = OrderData(
                symbol=req.symbol,
                exchange=req.exchange,
                orderid=orderid,
                type=req.type,
                direction=req.direction,
                price=req.price,
                volume=req.volume,
                status=STATUS_BINANCE2VT[response["status"]],
                gateway_name=self.gateway_name,
            )
            self.on_order(order)

            return order.vt_orderid
        except ClientError as e:
            self.write_log(f"委托失败：{e.error_message}")
            return ""

    def cancel_order(self, req: CancelRequest) -> None:
        """委托撤单"""
        try:
            self.client.cancel_order(
                symbol=req.symbol,
                orderId=req.orderid
            )
        except ClientError as e:
            self.write_log(f"撤单失败：{e.error_message}")

    def query_account(self) -> None:
        """查询资金"""
        try:
            account = self.client.account()
            
            for balance in account["balances"]:
                asset = balance["asset"]
                free = float(balance["free"])
                locked = float(balance["locked"])
                
                if free or locked:
                    account_data = AccountData(
                        accountid=asset,
                        balance=free + locked,
                        frozen=locked,
                        gateway_name=self.gateway_name
                    )
                    self.on_account(account_data)
        except ClientError as e:
            self.write_log(f"查询资金失败：{e.error_message}")

    def query_position(self) -> None:
        """查询持仓"""
        try:
            account = self.client.account()
            
            for balance in account["balances"]:
                asset = balance["asset"]
                free = float(balance["free"])
                locked = float(balance["locked"])
                
                if free or locked:
                    position = PositionData(
                        symbol=f"{asset}USDT",
                        exchange=Exchange.BINANCE,
                        direction=Direction.NET,
                        volume=free + locked,
                        frozen=locked,
                        price=0,
                        pnl=0,
                        gateway_name=self.gateway_name,
                    )
                    self.on_position(position)
        except ClientError as e:
            self.write_log(f"查询持仓失败：{e.error_message}")

    def close(self) -> None:
        """关闭连接"""
        if self.market_ws_api:
            self.market_ws_api.stop()
        self.market_ws_api = None

    def init_trading(self) -> None:
        """初始化交易"""
        try:
            # 查询交易规则和合约信息
            exchange_info = self.client.exchange_info()
            
            for symbol_data in exchange_info["symbols"]:
                if symbol_data.get("status", "") != "TRADING":
                    continue
                
                symbol = symbol_data["symbol"]
                
                contract = ContractData(
                    symbol=symbol,
                    exchange=Exchange.BINANCE,
                    name=symbol,
                    product=Product.SPOT,
                    size=1,
                    pricetick=float(symbol_data["filters"][0]["tickSize"]),
                    min_volume=float(symbol_data["filters"][1]["minQty"]),
                    gateway_name=self.gateway_name
                )
                self.on_contract(contract)
                
        except Exception as e:
            self.write_log(f"初始化交易失败：{str(e)}")

    def init_query(self) -> None:
        """初始化查询"""
        self.query_account()
        self.query_position()

    def query_contract(self) -> None:
        """查询合约"""
        try:
            # 查询交易规则和合约信息
            exchange_info = self.client.exchange_info()
            
            for symbol_data in exchange_info["symbols"]:
                if symbol_data.get("status", "") != "TRADING":
                    continue
                
                symbol = symbol_data["symbol"]
                
                contract = ContractData(
                    symbol=symbol,
                    exchange=Exchange.BINANCE,
                    name=symbol,
                    product=Product.SPOT,
                    size=1,
                    pricetick=float(symbol_data["filters"][0]["tickSize"]),
                    min_volume=float(symbol_data["filters"][1]["minQty"]),
                    gateway_name=self.gateway_name
                )
                self.on_contract(contract)
                
        except Exception as e:
            self.write_log(f"初始化交易失败：{str(e)}")

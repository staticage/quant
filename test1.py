from binance import ThreadedWebsocketManager
from binance.client import Client
from binance.exceptions import BinanceAPIException

twm = ThreadedWebsocketManager(
    api_key="77VqyxrjpGfX0F6QSVj9BfM6RgpCTekVOGPSYHr2IqAGQ5B7xf6XV1W90w9QRKyD",
    api_secret="4VJ2iJYbAqutncrtGtucFdoAPb6b5AmI8Ibe1K9R8kZvUsYySKUmxiNGctPxmsSU",
    https_proxy="socks5://127.0.0.1:7890"
)
twm.start()


def handle_trade_data(trade_data):
    print(trade_data)

twm.start_trade_socket(
    callback=handle_trade_data,
    symbol="BTCUSDT"
)



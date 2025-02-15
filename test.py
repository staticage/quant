from binance.client import Client
from vnpy.trader.object import (
    ContractData,
    Exchange,
    Product,
)

api_key = "77VqyxrjpGfX0F6QSVj9BfM6RgpCTekVOGPSYHr2IqAGQ5B7xf6XV1W90w9QRKyD"
api_secret = "4VJ2iJYbAqutncrtGtucFdoAPb6b5AmI8Ibe1K9R8kZvUsYySKUmxiNGctPxmsSU"
server = "TESTNET"

client = Client(
    api_key=api_key,
    api_secret=api_secret,
    testnet=(server == "TESTNET")
)

exchange_info = client.get_exchange_info()

print(exchange_info["symbols"])

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
        pricetick=float(next(filter for filter in symbol_data["filters"] if filter["filterType"] == "PRICE_FILTER")["tickSize"]),
        min_volume=float(next(filter for filter in symbol_data["filters"] if filter["filterType"] == "LOT_SIZE")["minQty"]),
        gateway_name='test'
    )
print(exchange_info["symbols"])
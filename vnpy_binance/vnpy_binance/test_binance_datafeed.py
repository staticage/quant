import unittest
from datetime import datetime, timedelta
from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import HistoryRequest
from vnpy.trader.setting import SETTINGS
from vnpy_binance.binance_datafeed import BinanceDatafeed

class TestBinanceDatafeed(unittest.TestCase):
    """币安数据服务接口测试"""

    def setUp(self):
        """测试前准备工作"""
        # 设置API密钥，实际使用时请替换成您的密钥
        SETTINGS["datafeed.api_key"] = ""        # 填入您的API Key
        SETTINGS["datafeed.api_secret"] = ""     # 填入您的API Secret
        
        self.datafeed = BinanceDatafeed()
        
    def test_query_bar_history(self):
        """测试K线数据查询"""
        # 创建历史数据查询请求
        end = datetime.utcnow()
        start = end - timedelta(days=1)
        
        req = HistoryRequest(
            symbol="BTCUSDT",
            exchange=Exchange.BINANCE,
            interval=Interval.MINUTE,
            start=start,
            end=end
        )
        
        # 获取历史数据
        data = self.datafeed.query_bar_history(req)
        print(data)
        # 验证返回的数据
        self.assertIsNotNone(data)
        self.assertGreater(len(data), 0)

if __name__ == "__main__":
    unittest.main()

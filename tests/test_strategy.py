from trader.app.app import App
from trader.common.config import Config
from trader.utils.trend import TrendType


# MACD + RSI + BollingerBand from ShiHun only in the upward trend
def test_ShihunMacdRsiBollingerBand_UP():
    cfg = Config("ShihunMACDRISBB")
    cfg.mode=TrendType.UP
    app = App()
    if app.start(cfg):
        app.stop()
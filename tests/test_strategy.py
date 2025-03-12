from trader.app.app import App
from trader.common.config import Config
from trader.strategy.strategy import parseStrategy, parse_strategys
from trader.utils.trend import TrendType

def test_ShihunMACD():
    app = App(Config("ShihunMACD"))
    if app.start():
        app.stop()

# MACD + RSI + BollingerBand from ShiHun only in the upward trend
def test_ShihunMacdRsiBollingerBand_UP():
    cfg = Config("ShihunMACDRISBB")
    cfg.mode=TrendType.UP
    app = App(cfg)
    if app.start():
        app.stop()

def test_parse_strategy():
    sy=parseStrategy("ShihunMACD")
    print(sy)

def test_parse_strategys():
    sy=parse_strategys(["ShihunMACD","ShihunMACD2"])
    print(sy)
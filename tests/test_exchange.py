from trader.binance.exchange import BinanceExchange
from trader.common.config import Config
from trader.common.logger import Logger


def test_get_klines():
    cfg = Config()
    exchange = BinanceExchange(cfg,Logger("trader").log())
    exchange.start()
    ret=exchange.get_klines(cfg.get_symbol_interval_list()[0])
    print(f"get latest klines total:{len(ret)}")
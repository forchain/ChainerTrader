from trader.binance.exchange import BinanceExchange, get_oldest_time
from trader.common.config import Config
from trader.common.logger import Logger


def test_get_klines():
    cfg = Config()
    exchange = BinanceExchange(cfg,Logger("trader").log())
    exchange.start()
    ret=exchange.get_klines(cfg.get_symbol_interval_list()[0],None,None,3)
    print(f"get latest klines total:{len(ret)}")
    print(ret)

def test_oldest_time():
    assert 946656000 == int(get_oldest_time().timestamp())
from trader.binance.exchange import BinanceExchange, get_oldest_time
from trader.common.config import Config
from trader.common.logger import Logger
from trader.utils.symbol_interval import Interval, get_time_duration


def test_get_latest_klines():
    cfg = Config()
    exchange = BinanceExchange(cfg,Logger("trader").log())
    exchange.start()
    ret=exchange.get_latest_klines(cfg.get_symbol_interval_list()[0],3)
    assert ret is not None
    print(f"get latest klines total:{len(ret)}")
    for kl in ret:
        print(kl.to_json())

def test_get_klines():
    cfg = Config()
    exchange = BinanceExchange(cfg,Logger("trader").log())
    exchange.start()
    start_time = 1503446400 # 2017-08-23 08:00:00
    end_time = 1504051200 # 2017-08-30 08:00:00

    ret=exchange.get_klines(cfg.get_symbol_interval_list()[0],start_time,end_time)
    assert ret is not None
    print(f"get klines total:{len(ret)}")
    for kl in ret:
        print(kl.to_json())

def test_get_klines_limit():
    cfg = Config()
    exchange = BinanceExchange(cfg,Logger("trader").log())
    exchange.start()
    start_time = 1503446400 # 2017-08-23 08:00:00
    end_time = 1504051200 # 2017-08-30 08:00:00

    ret=exchange.get_klines(cfg.get_symbol_interval_list()[0],start_time,end_time,3)
    assert ret is not None
    print(f"get klines total:{len(ret)}")
    for kl in ret:
        print(kl.to_json())

def test_get_klines_by_start():
    cfg = Config()
    exchange = BinanceExchange(cfg,Logger("trader").log())
    exchange.start()
    ret=exchange.get_klines_by_start(cfg.get_symbol_interval_list()[0],None,1)
    assert ret is not None

    print(f"get start kline:{len(ret)}")
    for kl in ret:
        print(kl.to_json())

def test_oldest_time():
    assert 946656000 == int(get_oldest_time().timestamp())

def test_interval_seconds():
    list:[Interval]=[
        Interval.INTERVAL_1s,
        Interval.INTERVAL_1m,
        Interval.INTERVAL_3m,
        Interval.INTERVAL_5m,
        Interval.INTERVAL_15m,
        Interval.INTERVAL_30m,
        Interval.INTERVAL_1h,
        Interval.INTERVAL_2h,
        Interval.INTERVAL_4h,
        Interval.INTERVAL_6h,
        Interval.INTERVAL_8h,
        Interval.INTERVAL_12h,
        Interval.INTERVAL_1d,
        Interval.INTERVAL_3d,
        Interval.INTERVAL_1w,
        Interval.INTERVAL_1M]

    for inte in list:
        print(f"{inte.value} = {get_time_duration(inte)} seconds")
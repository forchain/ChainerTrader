from trader.exchange.binance.exchange import BinanceExchange, get_oldest_time
from trader.exchange.exchange_config import ExchangeConfig
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import Interval, get_time_duration


def get_exchange():
    exchange = BinanceExchange(ExchangeConfig())
    exchange.start()
    return exchange, TaskConfig(TaskType.TRADER)


def test_get_latest_klines():
    exchange, cfg = get_exchange()
    ret = exchange.get_latest_klines(cfg.symbol_interval, 3)
    assert ret is not None
    print(f"get latest klines total:{len(ret)}")
    for kl in ret:
        print(kl.to_json())


def test_get_klines():
    exchange, cfg = get_exchange()
    start_time = 1503446400  # 2017-08-23 08:00:00
    end_time = 1504051200  # 2017-08-30 08:00:00

    ret = exchange.get_klines(cfg.symbol_interval, start_time, end_time)
    assert ret is not None
    print(f"get klines total:{len(ret)}")
    for kl in ret:
        print(kl.to_json())


def test_get_klines_limit():
    exchange, cfg = get_exchange()
    start_time = 1503446400  # 2017-08-23 08:00:00
    end_time = 1504051200  # 2017-08-30 08:00:00

    ret = exchange.get_klines(cfg.symbol_interval, start_time, end_time, 3)
    assert ret is not None
    print(f"get klines total:{len(ret)}")
    for kl in ret:
        print(kl.to_json())


def test_get_klines_by_start():
    exchange, cfg = get_exchange()
    ret = exchange.get_klines_by_start(cfg.symbol_interval, None, 1)
    assert ret is not None

    print(f"get start kline:{len(ret)}")
    for kl in ret:
        print(kl.to_json())


def test_oldest_time():
    assert 946656000 == int(get_oldest_time().timestamp())


def test_interval_seconds():
    list: [Interval] = [
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
        Interval.INTERVAL_1M,
    ]

    for inte in list:
        print(f"{inte.value} = {get_time_duration(inte)} seconds")

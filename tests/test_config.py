from trader.common.config import Config


def test_config():
    cfg = Config()
    print(cfg.to_dict())

def test_symbols():
    cfg = Config()
    cfg.symbols="BTCUSDT,ETHUSDT"
    print(cfg.symbols_list())

def test_check_symbols_intervals():
    cfg = Config()
    print(cfg.check_symbols_intervals())

def test_symbols_intervals():
    cfg = Config()
    for si in cfg.get_symbol_interval_list():
        print(si.name())
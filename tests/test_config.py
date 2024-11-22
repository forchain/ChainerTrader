from trader.common.config import Config


def test_config():
    cfg = Config()
    print(cfg.to_dict())

def test_symbols():
    cfg = Config()
    cfg.symbols="BTCUSDT,ETHUSDT"
    print(cfg.symbols_list())
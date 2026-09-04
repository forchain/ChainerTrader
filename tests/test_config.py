import argparse
import os

from trader.common.config import Config, new_and_env
from trader.common.path import GetConfigsDir
from trader.exchange.exchange_config import ExchangeConfig, parse_exchange_config
from trader.exchange.exchange_type import parse_ex_type
from trader.task.task_config import TaskConfig, get_symbols, parse_task_config
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import Interval, SymbolInterval


def test_config():
    cfg = Config()
    print(cfg.to_dict())


def test_config_defaults_use_10_minute_dataset_prepare_timeout():
    cfg = Config()
    assert cfg.optimization_dataset_prepare_timeout_seconds == 600.0


def test_symbols():
    cfgs = [
        TaskConfig(0, TaskType.TRADER, SymbolInterval("BTC-USDT", Interval.INTERVAL_1d)),
        TaskConfig(0, TaskType.TRADER, SymbolInterval("ETH-USDT", Interval.INTERVAL_1d)),
    ]
    print(get_symbols(cfgs))


def test_symbols_intervals():
    cfgs = [
        TaskConfig(0, TaskType.TRADER, SymbolInterval("BTC-USDT", Interval.INTERVAL_1d)),
        TaskConfig(0, TaskType.TRADER, SymbolInterval("ETH-USDT", Interval.INTERVAL_1d)),
    ]
    for si in cfgs:
        print(si.symbol_interval.name())


def test_taskconfig():
    file = os.path.join(GetConfigsDir(), "tasks", "backtests", "multi_backtrader.json")
    tcfgs = parse_task_config(file)
    for tcfg in tcfgs:
        print(tcfg.to_dict())


def test_taskconfig_uk():
    file = os.path.join(GetConfigsDir(), "tasks", "downloads", "update_klines.json")
    tcfgs = parse_task_config(file)
    for tcfg in tcfgs:
        print(tcfg.to_dict())


def test_taskconfig_ckn():
    file = os.path.join(GetConfigsDir(), "tasks", "downloads", "check_klines_num.json")
    tcfgs = parse_task_config(file)
    for tcfg in tcfgs:
        print(tcfg.to_dict())


def test_config_from_env():
    cfg = Config()
    cfg.export_env()
    ncfg = new_and_env()
    print(ncfg.to_dict())


def test_new_and_env_cli_overrides_env(monkeypatch):
    monkeypatch.setenv("TRADER_COMMISSION", "0.002")
    monkeypatch.setenv("TRADER_TASKS", "env_tasks.json")
    ns = argparse.Namespace(commission=0.005, tasks="cli_tasks.json")
    cfg = new_and_env(ns)
    assert cfg.commission == 0.005
    assert cfg.tasks == "cli_tasks.json"


def test_new_and_env_env_when_cli_absent(monkeypatch):
    monkeypatch.setenv("TRADER_COMMISSION", "0.003")
    cfg = new_and_env()
    assert cfg.commission == 0.003


def test_new_and_env_protected_paths_cli_overrides_env(monkeypatch):
    monkeypatch.setenv("TRADER_PROTECTED_PATHS", "/from-env")
    ns = argparse.Namespace(protected_paths="/from-cli,/other")
    cfg = new_and_env(ns)
    assert cfg.protected_paths == ["/from-cli", "/other"]


def test_ex_config():
    cfg_data = '{"ty": "BINANCE", "api_key": "abc","api_secret":"123"}'
    except_ret = ExchangeConfig(ty=parse_ex_type("BINANCE"), api_key="abc", api_secret="123")
    ex_cfg = parse_exchange_config(cfg_data)
    assert ex_cfg is not None
    assert ex_cfg.ty == except_ret.ty and ex_cfg.api_key == except_ret.api_key and ex_cfg.api_secret == except_ret.api_secret


def test_ex_config_legacy():
    cfg_data = "BINANCE"
    except_ret = ExchangeConfig()
    ex_cfg = parse_exchange_config(cfg_data)
    assert ex_cfg is not None
    assert ex_cfg.ty == except_ret.ty and ex_cfg.api_key == except_ret.api_key and ex_cfg.api_secret == except_ret.api_secret

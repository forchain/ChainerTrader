import argparse
import logging
import os

from trader.common.config import Config, new_and_env
from trader.common.logger import Logger
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


def test_parse_symbols_trims_whitespace_after_commas():
    cfg = (
        '[{"task_type":"BACK_TRADER","symbols":"BTC-USDT, ZEC-USDT, XLM-USDT",'
        '"interval":"1d","strategy":"macd_triple_divergence"}]'
    )

    tcfgs = parse_task_config(cfg)

    assert [tcfg.symbol_interval.symbol() for tcfg in tcfgs] == ["BTCUSDT", "ZECUSDT", "XLMUSDT"]


def test_parse_task_config_accepts_margin_borrow_controls():
    cfg = (
        '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m","strategy":"macd_triple_divergence",'
        '"live_short_execution":"margin_cross","live_margin_borrow_block_policy":"repay_all",'
        '"live_margin_borrow_precheck":true,"live_margin_auto_repay_max_total":100,'
        '"live_margin_auto_repay_max_per_asset":50,"live_margin_auto_repay_min_amount":0.000001,'
        '"live_margin_auto_repay_excluded_assets":["BNB"]}]'
    )

    task = parse_task_config(cfg)[0]

    assert task.live_margin_borrow_block_policy == "repay_all"
    assert task.live_margin_borrow_precheck is True
    assert task.live_margin_auto_repay_max_total == 100.0
    assert task.live_margin_auto_repay_max_per_asset == 50.0
    assert task.live_margin_auto_repay_excluded_assets == ["BNB"]


def test_parse_task_config_keeps_legacy_margin_borrow_policy_aliases():
    cfg = (
        '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m","strategy":"macd_triple_divergence",'
        '"live_margin_borrow_block_policy":"auto_repay_then_retry_once"}]'
    )

    task = parse_task_config(cfg)[0]

    assert task.live_margin_borrow_block_policy == "repay_single"


def test_task_config_parses_direct_margin_borrow_precheck_string():
    task = TaskConfig(
        1,
        TaskType.TRADER,
        SymbolInterval("BTC-USDT", Interval.INTERVAL_1m),
        live_margin_borrow_precheck="false",
    )

    assert task.live_margin_borrow_precheck is False


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


def test_new_and_env_log_file_accepts_path(monkeypatch):
    monkeypatch.setenv("TRADER_LOG_FILE", "./logs/trader.log")

    cfg = new_and_env()

    assert cfg.log_file == "./logs/trader.log"


def test_new_and_env_log_file_keeps_boolean_compatibility(monkeypatch):
    monkeypatch.setenv("TRADER_LOG_FILE", "true")

    cfg = new_and_env()

    assert cfg.log_file is True


def test_new_and_env_log_file_cli_preserves_path():
    ns = argparse.Namespace(log_file="./logs/from-cli.log")

    cfg = new_and_env(ns)

    assert cfg.log_file == "./logs/from-cli.log"


def test_logger_writes_to_configured_log_file_path(tmp_path, capsys):
    log_path = tmp_path / "logs" / "trader.log"
    cfg = Config(log_file=str(log_path))

    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    for handler in original_handlers:
        root_logger.removeHandler(handler)
    try:
        logger = Logger(cfg)
        logger.info("configured file path smoke")
        for handler in logging.getLogger().handlers:
            handler.flush()
    finally:
        for handler in list(logging.getLogger().handlers):
            handler.close()
            logging.getLogger().removeHandler(handler)
        for handler in original_handlers:
            logging.getLogger().addHandler(handler)

    captured = capsys.readouterr()

    assert log_path.exists()
    assert "configured file path smoke" in log_path.read_text(encoding="utf-8")
    assert "configured file path smoke" in captured.err


def test_logger_keeps_noisy_third_party_debug_logs_quiet(tmp_path):
    log_path = tmp_path / "logs" / "trader.log"
    cfg = Config(log_file=str(log_path), log_level="DEBUG")

    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_ccxt_level = logging.getLogger("ccxt").level
    for handler in original_handlers:
        root_logger.removeHandler(handler)
    try:
        Logger(cfg)
        logging.getLogger("ccxt").debug("ccxt private request payload")
        logging.getLogger("trader").debug("app debug lifecycle")
        for handler in logging.getLogger().handlers:
            handler.flush()
    finally:
        logging.getLogger("ccxt").setLevel(original_ccxt_level)
        for handler in list(logging.getLogger().handlers):
            handler.close()
            logging.getLogger().removeHandler(handler)
        for handler in original_handlers:
            logging.getLogger().addHandler(handler)

    text = log_path.read_text(encoding="utf-8")
    assert "app debug lifecycle" in text
    assert "ccxt private request payload" not in text


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

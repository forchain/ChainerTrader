import asyncio
import json
from types import SimpleNamespace

import pytest

from scripts.migrate_persisted_live_task_configs import main as migrate_persisted_live_task_configs_main
from trader.app.app import App
from trader.common.config import TRADER_DB, TRADER_EXCHANGE, TRADER_TASKS, Config
from trader.common.logger import Logger
from trader.common.message import new_add_tasks_msg, new_exit_msg
from trader.task.base_task import BaseTask
from trader.task.persisted_live_config_migration import migrate_persisted_task_config_json
from trader.task.task_config import TaskConfig
from trader.task.task_manager import TaskManager
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import Interval, SymbolInterval
from trader.utils.task_state import TaskState, TaskStateType


def test_task_manager_start_returns_none_when_tasks_parse_to_empty():
    cfg = Config(
        tasks='[{"task_type":"BACK_TRADER","symbol":"ETHUSDT","interval":"1h","strategy":"macd_triple_divergence","csv":"data/ETHUSDT-1h-202301-202401.csv"}]'
    )
    task_manager = TaskManager(cfg, Logger(cfg), None, None)

    assert task_manager.start() is None


def test_app_start_returns_false_when_task_manager_returns_no_message(monkeypatch):
    cfg = Config(tasks='[{"task_type":"BACK_TRADER","symbol":"ETHUSDT","interval":"1h","strategy":"macd_triple_divergence"}]')
    app = App(cfg)

    monkeypatch.setattr(app.task_manager, "start", lambda: None)
    monkeypatch.setattr(app, "process", lambda msgs: (_ for _ in ()).throw(AssertionError("process should not be called")))

    assert app.start() is False


def test_app_start_runs_startup_self_check_before_task_launch(monkeypatch):
    cfg = Config(
        tasks='[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1h","strategy":"macd_triple_divergence","strategy_params":{"chainer_mode":"BOTH"}}]',
        exchange='{"ty":"BINANCE","driver":"ccxt","api_key":"k","api_secret":"s"}',
    )
    app = App(cfg)
    calls = []

    monkeypatch.setattr(app.exchange, "start", lambda: calls.append("exchange.start"))
    monkeypatch.setattr(app, "process", lambda msgs: calls.append(("process", len(msgs))))
    monkeypatch.setattr(app.task_manager, "start", lambda *args, **kwargs: calls.append(("task_manager.start", len(args))) or None)

    assert app.start() is False
    assert "exchange.start" in calls
    assert any(item[0] == "task_manager.start" for item in calls if isinstance(item, tuple))
    assert hasattr(app, "startup_self_check")
    assert app.startup_self_check.required_margin_mode.value == "cross_margin"


def test_app_promotes_exchange_margin_mode_for_short_capable_tasks():
    cfg = Config(
        tasks='[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1h","strategy":"macd_triple_divergence","strategy_params":{"chainer_mode":"BOTH"}}]',
        exchange='{"ty":"BINANCE","driver":"ccxt","api_key":"k","api_secret":"s"}',
    )
    app = App(cfg)

    assert app.exchange is not None
    assert app.exchange.margin_mode.value == "cross_margin"


def test_app_does_not_promote_exchange_margin_mode_for_short_capable_backtests():
    cfg = Config(
        tasks='[{"task_type":"BACK_TRADER","symbol":"BTC-USDT","interval":"1d","strategy":"macd_triple_divergence","strategy_params":{"chainer_mode":"BOTH"}}]',
        exchange='{"ty":"BINANCE","driver":"ccxt","api_key":"k","api_secret":"s"}',
    )
    app = App(cfg)

    assert app.exchange is not None
    assert app.exchange.margin_mode.value == "spot"


def test_base_task_stop_without_db_manager_does_not_crash():
    cfg = Config(tasks="[]")
    tcfg = TaskConfig(
        id=1,
        ttype=TaskType.BACK_TRADER,
        symbol_interval=SymbolInterval("ETH-USDT", Interval("1h")),
        strategies=["macd_triple_divergence"],
    )
    task = BaseTask(tcfg, cfg, Logger(cfg))

    task.start(None)
    task.stop()

    assert task.ts.state.name == "DONE"


def test_base_task_start_persists_running_state_immediately():
    cfg = Config(tasks="[]")
    saved_batches = []

    async def add_tasks(states):
        saved_batches.append([state.to_dict() for state in states])
        return len(states)

    db_manager = SimpleNamespace(task=SimpleNamespace(add_tasks=add_tasks))
    tcfg = TaskConfig(
        id=3,
        ttype=TaskType.DEBUG,
        symbol_interval=SymbolInterval("ETH-USDT", Interval("1h")),
        strategies=[],
    )
    task = BaseTask(tcfg, cfg, Logger(cfg), db_manager)

    task.start(None)

    assert saved_batches
    assert saved_batches[0][0]["task_id"] == tcfg.id
    assert saved_batches[0][0]["state"] == "RUNNING"


def test_app_start_restores_running_tasks_from_database(monkeypatch):
    cfg = Config(tasks="[]", api="0.0.0.0:8000")
    app = App(cfg)
    recovered = TaskConfig(
        id=11,
        ttype=TaskType.DEBUG,
        symbol_interval=SymbolInterval("BTC-USDT", Interval("1h")),
        strategies=[],
    )
    running_state = SimpleNamespace(
        id=recovered.id,
        state=SimpleNamespace(name="RUNNING"),
        config_json='[{"task_type":"DEBUG","limit":1,"user_id":7,"run_id":"run-11"}]',
        user_id=7,
        to_dict=lambda: {
            "task_id": recovered.id,
            "state": "RUNNING",
            "config_json": '[{"task_type":"DEBUG","limit":1,"user_id":7,"run_id":"run-11"}]',
        },
    )
    events = []

    class _FakeTaskRepo:
        async def get_all_tasks(self):
            events.append("db.get_all_tasks")
            return [running_state]

    class _FakeDbManager:
        started = True
        task = _FakeTaskRepo()

        async def start(self):
            events.append("db.start")

        async def get_startup_admin(self):
            return SimpleNamespace(id=1)

    recovered_calls = []

    def _fake_process(msgs):
        app.queue = asyncio.Queue()
        app._mark_handler_ready()
        asyncio.run(app._recover_running_tasks_in_background())
        events.append(("process", len(msgs)))

    app.db_manager = _FakeDbManager()

    async def _recover_task(taskc, queue):
        recovered_calls.append((taskc.id, taskc.user_id, taskc.run_id))

    app.task_manager = SimpleNamespace(
        start=lambda *_args, **_kwargs: None,
        recover_task=_recover_task,
    )
    app.process = _fake_process

    monkeypatch.setattr("trader.app.app.parse_task_config", lambda _cfg: [recovered])

    assert app.start() is True
    assert "db.get_all_tasks" in events
    assert recovered_calls == [(recovered.id, 7, "run-11")]


def test_app_start_recovers_live_task_state_persisted_by_current_base_task():
    cfg = Config(tasks="[]", api="0.0.0.0:8000")
    app = App(cfg)
    persisted_task = BaseTask(
        TaskConfig(
            id=61,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            live_execution_mode="auto_trade",
            live_trade_max_notional=25.0,
            user_id=7,
            run_id="run-61",
        ),
        Config(tasks="[]"),
        Logger(Config(tasks="[]")),
    )
    running_state = SimpleNamespace(
        id=61,
        state=SimpleNamespace(name="RUNNING"),
        config_json=persisted_task.ts.config_json,
        user_id=7,
    )
    events = []
    recovered_calls = []

    class _FakeTaskRepo:
        async def get_all_tasks(self):
            events.append("db.get_all_tasks")
            return [running_state]

    class _FakeDbManager:
        started = True
        task = _FakeTaskRepo()

        async def start(self):
            events.append("db.start")

        async def get_startup_admin(self):
            return SimpleNamespace(id=1)

    def _fake_process(msgs):
        app.queue = asyncio.Queue()
        app._mark_handler_ready()
        asyncio.run(app._recover_running_tasks_in_background())
        events.append(("process", len(msgs)))

    async def _recover_task(taskc, queue):
        recovered_calls.append(
            (
                taskc.id,
                taskc.live_execution_mode,
                taskc.live_trade_max_notional,
                taskc.user_id,
                taskc.run_id,
            )
        )

    app.db_manager = _FakeDbManager()
    app.task_manager = SimpleNamespace(start=lambda *_args, **_kwargs: None, recover_task=_recover_task)
    app.process = _fake_process

    assert app.start() is True
    assert "db.get_all_tasks" in events
    assert recovered_calls == [(61, "auto_trade", 25.0, 7, "run-61")]


def test_app_start_skips_startup_task_when_matching_running_task_will_recover(monkeypatch):
    cfg = Config(tasks='[{"task_type":"DEBUG","limit":1}]', api="0.0.0.0:8000")
    app = App(cfg)
    running_state = SimpleNamespace(
        id=42,
        state=SimpleNamespace(name="RUNNING"),
        config_json='[{"task_type":"DEBUG","limit":1,"user_id":1,"run_id":"run-42"}]',
        user_id=1,
    )
    events = []

    class _FakeTaskRepo:
        async def get_all_tasks(self):
            events.append("db.get_all_tasks")
            return [running_state]

    class _FakeDbManager:
        started = True
        task = _FakeTaskRepo()

        async def start(self):
            events.append("db.start")

        async def get_startup_admin(self):
            return SimpleNamespace(id=1)

    def _fake_process(msgs):
        app.queue = asyncio.Queue()
        app._mark_handler_ready()
        asyncio.run(app._recover_running_tasks_in_background())
        events.append(("process", len(msgs)))

    recovered_calls = []

    async def _recover_task(taskc, queue):
        recovered_calls.append((taskc.id, taskc.user_id, taskc.run_id))

    app.db_manager = _FakeDbManager()
    app.task_manager = SimpleNamespace(
        start=lambda taskcs: new_add_tasks_msg(taskcs) if taskcs else None,
        recover_task=_recover_task,
    )
    app.process = _fake_process

    assert app.start() is True
    assert ("process", 0) in events
    assert recovered_calls == [(42, 1, "run-42")]


def test_app_start_skips_all_startup_tasks_when_any_running_task_will_recover():
    cfg = Config(
        tasks=(
            "["
            '{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1h","strategy":"macd_triple_divergence"},'
            '{"task_type":"TRADER","symbol":"ETH-USDT","interval":"1h","strategy":"macd_triple_divergence"}'
            "]"
        ),
        api="0.0.0.0:8000",
    )
    app = App(cfg)
    running_state = SimpleNamespace(
        id=42,
        state=SimpleNamespace(name="RUNNING"),
        config_json=(
            '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1h",'
            '"strategy":"macd_triple_divergence","run_id":"run-42"}]'
        ),
        user_id=1,
    )
    events = []

    class _FakeTaskRepo:
        async def get_all_tasks(self):
            return [running_state]

    class _FakeDbManager:
        started = True
        task = _FakeTaskRepo()

        async def start(self):
            raise AssertionError("db.start should not be called")

        async def get_startup_admin(self):
            return SimpleNamespace(id=1)

    app.db_manager = _FakeDbManager()
    app.task_manager = SimpleNamespace(
        start=lambda taskcs: new_add_tasks_msg(taskcs) if taskcs else None,
        recover_task=lambda *_args, **_kwargs: None,
    )
    app.process = lambda msgs: events.append(("process", len(msgs)))

    assert app.start() is True
    assert ("process", 0) in events


def test_app_handler_in_console_mode_does_not_schedule_recovery():
    cfg = Config(tasks="[]")
    app = App(cfg)
    close_called = []
    recover_called = []

    class _FakeDbManager:
        started = True

        async def start(self):
            raise AssertionError("db.start should not be called")

        async def get_startup_admin(self):
            raise AssertionError("startup admin should not be requested in console mode without startup tasks")

        async def stop(self):
            return None

    async def _close():
        close_called.append(True)

    async def _recover_task(*_args, **_kwargs):
        recover_called.append(True)

    app.db_manager = _FakeDbManager()
    app.task_manager = SimpleNamespace(close=_close, recover_task=_recover_task)

    asyncio.run(app.handler([new_exit_msg()], asyncio.Event()))

    assert close_called == [True]
    assert recover_called == []
    assert app.recovery_task is None


def test_app_start_skips_startup_task_when_migrated_persisted_row_matches_startup_config(monkeypatch):
    cfg = Config(
        tasks=(
            '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m","strategy":"macd_triple_divergence",'
            '"live_execution_mode":"auto_trade"}]'
        ),
        api="0.0.0.0:8000",
    )
    app = App(cfg)
    events = []
    running_state = SimpleNamespace(
        id=52,
        state=SimpleNamespace(name="RUNNING"),
        config_json=(
            '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m","strategy":"macd_triple_divergence",'
            '"live_execution_mode":"auto_trade","run_id":"run-52"}]'
        ),
        user_id=1,
    )

    class _FakeTaskRepo:
        async def get_all_tasks(self):
            return [running_state]

    class _FakeDbManager:
        started = True
        task = _FakeTaskRepo()

        async def start(self):
            raise AssertionError("db.start should not be called")

        async def get_startup_admin(self):
            return SimpleNamespace(id=1)

    app.db_manager = _FakeDbManager()
    app.task_manager = SimpleNamespace(
        start=lambda taskcs: new_add_tasks_msg(taskcs) if taskcs else None,
        recover_task=lambda *_args, **_kwargs: None,
    )
    app.process = lambda msgs: events.append(("process", len(msgs)))

    assert app.start() is True
    assert ("process", 0) in events


def test_app_start_ignores_recovery_only_live_data_mode_when_deduping_startup_task():
    cfg = Config(
        tasks=(
            '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m","strategy":"macd_triple_divergence",'
            '"live_execution_mode":"auto_trade"}]'
        ),
        api="0.0.0.0:8000",
    )
    app = App(cfg)
    events = []
    running_state = SimpleNamespace(
        id=53,
        state=SimpleNamespace(name="RUNNING"),
        config_json=(
            '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m","strategy":"macd_triple_divergence",'
            '"live_execution_mode":"auto_trade","persisted_live_data_mode":"realtime","run_id":"run-53"}]'
        ),
        user_id=1,
    )

    class _FakeTaskRepo:
        async def get_all_tasks(self):
            return [running_state]

    class _FakeDbManager:
        started = True
        task = _FakeTaskRepo()

        async def start(self):
            raise AssertionError("db.start should not be called")

        async def get_startup_admin(self):
            return SimpleNamespace(id=1)

    app.db_manager = _FakeDbManager()
    app.task_manager = SimpleNamespace(
        start=lambda taskcs: new_add_tasks_msg(taskcs) if taskcs else None,
        recover_task=lambda *_args, **_kwargs: None,
    )
    app.process = lambda msgs: events.append(("process", len(msgs)))

    assert app.start() is True
    assert ("process", 0) in events


def test_migrate_persisted_task_config_json_rewrites_supported_legacy_live_modes():
    migrated = json.loads(
        migrate_persisted_task_config_json(
            json.dumps(
                [
                    {
                        "task_type": "TRADER",
                        "symbol": "BTC-USDT",
                        "interval": "1m",
                        "strategy": "macd_triple_divergence",
                        "live_execution_mode": "small_live_auto",
                        "live_data_mode": "realtime",
                    },
                    {
                        "task_type": "TRADER",
                        "symbol": "ETH-USDT",
                        "interval": "1m",
                        "strategy": "macd_triple_divergence",
                        "live_execution_mode": "full_live_auto",
                        "live_data_mode": "polling",
                    },
                    {
                        "task_type": "TRADER",
                        "symbol": "SOL-USDT",
                        "interval": "1m",
                        "strategy": "macd_triple_divergence",
                        "live_execution_mode": "manual_notify",
                        "live_data_mode": "realtime",
                    },
                ]
            )
        )
    )

    assert migrated[0]["live_execution_mode"] == "auto_trade"
    assert "live_data_mode" not in migrated[0]
    assert migrated[0]["persisted_legacy_live_execution_mode"] == "small_live_auto"
    assert migrated[0]["persisted_live_data_mode"] == "realtime"
    assert migrated[1]["live_execution_mode"] == "auto_trade"
    assert "live_data_mode" not in migrated[1]
    assert migrated[1]["persisted_legacy_live_execution_mode"] == "full_live_auto"
    assert migrated[2]["live_execution_mode"] == "manual_notify"
    assert "live_data_mode" not in migrated[2]


@pytest.mark.parametrize("unsupported_mode", ["staged_auto_trade", "paper_auto", "manual", "notify"])
def test_migrate_persisted_task_config_json_rejects_unsupported_legacy_live_modes(unsupported_mode):
    with pytest.raises(ValueError, match=unsupported_mode):
        migrate_persisted_task_config_json(
            json.dumps(
                [
                    {
                        "task_type": "TRADER",
                        "symbol": "BTC-USDT",
                        "interval": "1m",
                        "strategy": "macd_triple_divergence",
                        "live_execution_mode": unsupported_mode,
                        "live_data_mode": "realtime",
                    }
                ]
            )
        )


def test_migrate_persisted_task_config_json_rejects_manual_notify_polling_rows():
    with pytest.raises(ValueError, match="manual_notify.*polling"):
        migrate_persisted_task_config_json(
            json.dumps(
                [
                    {
                        "task_type": "TRADER",
                        "symbol": "BTC-USDT",
                        "interval": "1m",
                        "strategy": "macd_triple_divergence",
                        "live_execution_mode": "manual_notify",
                        "live_data_mode": "polling",
                    }
                ]
            )
        )


def test_migrate_persisted_live_task_configs_command_updates_persisted_rows(monkeypatch, capsys):
    migrated_state = SimpleNamespace(
        id=7,
        state=SimpleNamespace(name="RUNNING"),
        config_json='[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m","strategy":"macd_triple_divergence","live_execution_mode":"small_live_auto","live_data_mode":"realtime"}]',
        user_id=9,
    )
    persisted_batches = []

    class _FakeTaskRepo:
        async def get_all_tasks(self):
            return [migrated_state]

        async def add_tasks(self, states):
            persisted_batches.append([state.to_dict() for state in states])
            return len(states)

    monkeypatch.setattr("scripts.migrate_persisted_live_task_configs.load_dotenv", lambda: None)
    monkeypatch.setenv(TRADER_DB, "sqlite://data/test.db")

    class _FakeDbManager:
        def __init__(self, cfg, log):
            self.cfg = cfg
            self.log = log
            self.started = False
            self.task = _FakeTaskRepo()

        async def start(self):
            self.started = True

        async def stop(self):
            self.started = False

    monkeypatch.setattr("scripts.migrate_persisted_live_task_configs.DatabaseManager", _FakeDbManager)

    exit_code = migrate_persisted_live_task_configs_main([])

    assert exit_code == 0
    assert persisted_batches
    persisted = persisted_batches[-1][0]
    persisted_config = json.loads(persisted["config_json"])
    assert persisted["task_id"] == 7
    assert persisted_config[0]["live_execution_mode"] == "auto_trade"
    assert "live_data_mode" not in persisted_config[0]
    assert persisted_config[0]["persisted_legacy_live_execution_mode"] == "small_live_auto"
    assert persisted_config[0]["persisted_live_data_mode"] == "realtime"
    assert "updated=1" in capsys.readouterr().out


def test_migrate_persisted_live_task_configs_command_preserves_manual_notify_rows(monkeypatch, capsys):
    manual_state = SimpleNamespace(
        id=8,
        state=SimpleNamespace(name="RUNNING"),
        config_json='[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m","strategy":"macd_triple_divergence","live_execution_mode":"manual_notify","live_data_mode":"realtime"}]',
        user_id=9,
    )
    persisted_batches = []

    class _FakeTaskRepo:
        async def get_all_tasks(self):
            return [manual_state]

        async def add_tasks(self, states):
            persisted_batches.append([state.to_dict() for state in states])
            return len(states)

    monkeypatch.setattr("scripts.migrate_persisted_live_task_configs.load_dotenv", lambda: None)
    monkeypatch.setenv(TRADER_DB, "sqlite://data/test.db")

    class _FakeDbManager:
        def __init__(self, cfg, log):
            self.cfg = cfg
            self.log = log
            self.started = False
            self.task = _FakeTaskRepo()

        async def start(self):
            self.started = True

        async def stop(self):
            self.started = False

    monkeypatch.setattr("scripts.migrate_persisted_live_task_configs.DatabaseManager", _FakeDbManager)

    exit_code = migrate_persisted_live_task_configs_main([])

    assert exit_code == 0
    assert persisted_batches
    persisted = persisted_batches[-1][0]
    persisted_config = json.loads(persisted["config_json"])
    assert persisted_config[0]["live_execution_mode"] == "manual_notify"
    assert "live_data_mode" not in persisted_config[0]
    assert "updated=1" in capsys.readouterr().out


def test_migrate_persisted_live_task_configs_command_fails_nonzero_for_partial_persistence(monkeypatch, capsys):
    migrated_state = SimpleNamespace(
        id=10,
        state=SimpleNamespace(name="RUNNING"),
        config_json='[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m","strategy":"macd_triple_divergence","live_execution_mode":"small_live_auto","live_data_mode":"realtime"}]',
        user_id=9,
    )

    class _FakeTaskRepo:
        async def get_all_tasks(self):
            return [migrated_state]

        async def add_tasks(self, states):
            return 0

    monkeypatch.setattr("scripts.migrate_persisted_live_task_configs.load_dotenv", lambda: None)
    monkeypatch.setenv(TRADER_DB, "sqlite://data/test.db")

    class _FakeDbManager:
        def __init__(self, cfg, log):
            self.cfg = cfg
            self.log = log
            self.started = False
            self.task = _FakeTaskRepo()

        async def start(self):
            self.started = True

        async def stop(self):
            self.started = False

    monkeypatch.setattr("scripts.migrate_persisted_live_task_configs.DatabaseManager", _FakeDbManager)

    exit_code = migrate_persisted_live_task_configs_main([])

    assert exit_code == 1
    assert "saved 0 of 1 intended task updates" in capsys.readouterr().err


def test_migrate_persisted_live_task_configs_command_skips_unsupported_finished_rows(monkeypatch, capsys):
    unsupported_done_state = SimpleNamespace(
        id=9,
        state=SimpleNamespace(name="DONE"),
        config_json=json.dumps(
            [
                {
                    "task_type": "TRADER",
                    "symbol": "BTC-USDT",
                    "interval": "1m",
                    "strategy": "macd_triple_divergence",
                    "live_execution_mode": "paper_auto",
                    "live_data_mode": "realtime",
                }
            ]
        ),
        user_id=9,
    )
    migrated_running_state = SimpleNamespace(
        id=10,
        state=SimpleNamespace(name="RUNNING"),
        config_json='[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m","strategy":"macd_triple_divergence","live_execution_mode":"small_live_auto","live_data_mode":"realtime"}]',
        user_id=9,
    )
    persisted_batches = []

    class _FakeTaskRepo:
        async def get_all_tasks(self):
            return [unsupported_done_state, migrated_running_state]

        async def add_tasks(self, states):
            persisted_batches.append([state.to_dict() for state in states])
            return len(states)

    monkeypatch.setattr("scripts.migrate_persisted_live_task_configs.load_dotenv", lambda: None)
    monkeypatch.setenv(TRADER_DB, "sqlite://data/test.db")

    class _FakeDbManager:
        def __init__(self, cfg, log):
            self.task = _FakeTaskRepo()

        async def start(self):
            return None

        async def stop(self):
            return None

    monkeypatch.setattr("scripts.migrate_persisted_live_task_configs.DatabaseManager", _FakeDbManager)

    exit_code = migrate_persisted_live_task_configs_main([])

    assert exit_code == 0
    assert len(persisted_batches[-1]) == 1
    assert json.loads(persisted_batches[-1][0]["config_json"])[0]["live_execution_mode"] == "auto_trade"
    output = capsys.readouterr().out
    assert "scanned=2" in output
    assert "updated=1" in output
    assert "skipped=1" in output


@pytest.mark.parametrize("unsupported_mode", ["staged_auto_trade", "paper_auto", "manual", "notify"])
def test_migrate_persisted_live_task_configs_command_fails_nonzero_for_unsupported_modes(monkeypatch, capsys, unsupported_mode):
    unsupported_state = SimpleNamespace(
        id=9,
        state=SimpleNamespace(name="RUNNING"),
        config_json=json.dumps(
            [
                {
                    "task_type": "TRADER",
                    "symbol": "BTC-USDT",
                    "interval": "1m",
                    "strategy": "macd_triple_divergence",
                    "live_execution_mode": unsupported_mode,
                    "live_data_mode": "realtime",
                }
            ]
        ),
        user_id=9,
    )

    class _FakeTaskRepo:
        async def get_all_tasks(self):
            return [unsupported_state]

        async def add_tasks(self, states):
            raise AssertionError("add_tasks should not be called on migration failure")

    monkeypatch.setattr("scripts.migrate_persisted_live_task_configs.load_dotenv", lambda: None)
    monkeypatch.setenv(TRADER_DB, "sqlite://data/test.db")

    class _FakeDbManager:
        def __init__(self, cfg, log):
            self.cfg = cfg
            self.log = log
            self.started = False
            self.task = _FakeTaskRepo()

        async def start(self):
            self.started = True

        async def stop(self):
            self.started = False

    monkeypatch.setattr("scripts.migrate_persisted_live_task_configs.DatabaseManager", _FakeDbManager)

    exit_code = migrate_persisted_live_task_configs_main([])

    assert exit_code == 1
    assert unsupported_mode in capsys.readouterr().err


def test_migrate_persisted_live_task_configs_command_ignores_invalid_task_and_exchange_env(monkeypatch, capsys):
    migrated_state = SimpleNamespace(
        id=13,
        state=SimpleNamespace(name="RUNNING"),
        config_json='[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m","strategy":"macd_triple_divergence","live_execution_mode":"small_live_auto","live_data_mode":"realtime"}]',
        user_id=9,
    )

    class _FakeTaskRepo:
        async def get_all_tasks(self):
            return [migrated_state]

        async def add_tasks(self, states):
            return len(states)

    class _FakeDbManager:
        def __init__(self, cfg, log):
            assert cfg.db == "sqlite://data/test.db"
            assert cfg.tasks is None
            assert cfg.exchange is None
            self.task = _FakeTaskRepo()

        async def start(self):
            return None

        async def stop(self):
            return None

    monkeypatch.setattr("scripts.migrate_persisted_live_task_configs.load_dotenv", lambda: None)
    monkeypatch.setattr("scripts.migrate_persisted_live_task_configs.DatabaseManager", _FakeDbManager)
    monkeypatch.setenv(TRADER_DB, "sqlite://data/test.db")
    monkeypatch.setenv(TRADER_TASKS, "[not valid json")
    monkeypatch.setenv(TRADER_EXCHANGE, "{not valid json")

    exit_code = migrate_persisted_live_task_configs_main([])

    assert exit_code == 0
    assert "updated=1" in capsys.readouterr().out


def test_task_manager_awaits_completed_task_state_persistence():
    async def _test():
        cfg = Config(tasks="[]")
        saved_batches = []

        async def add_tasks(states):
            await asyncio.sleep(0)
            saved_batches.append([state.to_dict() for state in states])
            return len(states)

        db_manager = SimpleNamespace(task=SimpleNamespace(add_tasks=add_tasks))
        task_manager = TaskManager(cfg, Logger(cfg), db_manager, None)
        task_config = TaskConfig(
            id=2,
            ttype=TaskType.DEBUG,
            symbol_interval=SymbolInterval("ETH-USDT", Interval("1h")),
            strategies=[],
        )

        async def fake_add_task(taskc, queue):
            task = BaseTask(taskc, cfg, Logger(cfg), db_manager)
            task_manager.tasks[task.id()] = task
            await task.start(queue)

        task_manager.add_task = fake_add_task

        await task_manager.do_add_tasks([task_config], asyncio.Queue())

        assert [batch[0]["state"] for batch in saved_batches] == ["RUNNING", "DONE"]
        assert all(batch[0]["task_id"] == task_config.id for batch in saved_batches)

    asyncio.run(_test())


def test_task_manager_persists_failed_state_when_task_startup_raises():
    async def _test():
        cfg = Config(tasks="[]")
        saved_batches = []

        async def add_tasks(states):
            saved_batches.append([state.to_dict() for state in states])
            return len(states)

        db_manager = SimpleNamespace(task=SimpleNamespace(add_tasks=add_tasks))
        task_manager = TaskManager(cfg, Logger(cfg), db_manager, None)
        task_config = TaskConfig(
            id=4,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            live_execution_mode="auto_trade",
            user_id=2,
        )

        async def fail_exchange_setup(_taskcs):
            raise RuntimeError('binance {"code":-1022,"msg":"Signature for this request is not valid."}')

        task_manager._ensure_routed_exchanges = fail_exchange_setup

        try:
            await task_manager.do_add_tasks([task_config], asyncio.Queue())
        except RuntimeError:
            pass

        assert saved_batches
        failed = saved_batches[-1][0]
        assert failed["task_id"] == task_config.id
        assert failed["state"] == "FAILED"
        assert failed["user_id"] == 2
        assert "Signature for this request is not valid" in failed["error_message"]

    asyncio.run(_test())


def test_task_manager_recover_task_keeps_running_state_persisted():
    cfg = Config(tasks="[]")
    logger = Logger(cfg)

    async def _test():
        saved_batches = []
        release_task = asyncio.Event()

        async def add_tasks(states):
            saved_batches.append([state.to_dict() for state in states])
            return len(states)

        class _FakeLongRunningTask(BaseTask):
            async def start(self, queue):
                await super().start(queue)
                await release_task.wait()

        db_manager = SimpleNamespace(task=SimpleNamespace(add_tasks=add_tasks))
        task_manager = TaskManager(cfg, logger, db_manager, None)
        task_config = TaskConfig(
            id=5,
            ttype=TaskType.DEBUG,
            symbol_interval=SymbolInterval("ETH-USDT", Interval("1h")),
            strategies=[],
        )

        task_manager._build_task = lambda task_cfg, exchange: _FakeLongRunningTask(task_cfg, cfg, logger, db_manager)

        await task_manager.recover_task(task_config, asyncio.Queue())
        await asyncio.sleep(0)

        assert task_config.id in task_manager.tasks
        assert task_manager.tasks[task_config.id].ts.state.name == "RUNNING"
        assert [batch[0]["state"] for batch in saved_batches] == ["RUNNING"]

        release_task.set()
        await asyncio.gather(*task_manager.async_tasks)

    asyncio.run(_test())


def test_task_manager_recover_task_restores_capped_auto_trade_budget():
    cfg = Config(tasks="[]", cash=1000.0)
    logger = Logger(cfg)

    async def _test():
        class _ExecutionStateRepo:
            async def list_open_by_task(self, task_id):
                assert task_id == 15
                return [
                    SimpleNamespace(
                        order_role="entry",
                        status=SimpleNamespace(value="submitted"),
                        raw_payload={"effective_notional": 5.0},
                        quantity=0.0,
                        price=0.0,
                    )
                ]

        exchange = SimpleNamespace(
            get_account_balance=lambda asset: 1000.0 if asset == "USDT" else 0.0,
            margin_mode=None,
        )
        task_manager = TaskManager(
            cfg,
            logger,
            SimpleNamespace(execution_state=_ExecutionStateRepo()),
            exchange,
        )
        task_config = TaskConfig(
            id=15,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            free=500.0,
            live_execution_mode="auto_trade",
            live_trade_max_notional=25.0,
        )

        await task_manager._restore_recovered_task_runtime_budget(task_config)

        assert task_config.fund_reservation_asset == "USDT"
        assert task_config.fund_reservation_amount == 25.0
        assert task_config.fund_reservation_remaining == 20.0

    asyncio.run(_test())


def test_task_manager_close_preserves_running_live_tasks_for_restart_recovery():
    cfg = Config(tasks="[]")
    logger = Logger(cfg)

    async def _test():
        saved_batches = []

        async def add_tasks(states):
            saved_batches.append([state.to_dict() for state in states])
            return len(states)

        db_manager = SimpleNamespace(task=SimpleNamespace(add_tasks=add_tasks))
        task_manager = TaskManager(cfg, logger, db_manager, None)
        task_config = TaskConfig(
            id=9,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1h")),
            strategies=["macd_triple_divergence"],
            live_execution_mode="manual_notify",
        )
        task = BaseTask(task_config, cfg, logger, db_manager)
        await task.start(asyncio.Queue())
        task_manager.tasks[task.id()] = task
        saved_batches.clear()

        await task_manager.close()

        assert task.ts.state == TaskStateType.RUNNING
        assert saved_batches[-1][0]["state"] == "RUNNING"

    asyncio.run(_test())


def test_task_manager_dispatch_shutdown_preserves_running_live_tasks_for_restart_recovery():
    cfg = Config(tasks="[]")
    logger = Logger(cfg)

    async def _test():
        saved_batches = []

        async def add_tasks(states):
            saved_batches.append([state.to_dict() for state in states])
            return len(states)

        class _FakeLiveTraderTask(BaseTask):
            async def start(self, queue):
                await super().start(queue)
                await self.quit.wait()

        db_manager = SimpleNamespace(task=SimpleNamespace(add_tasks=add_tasks))
        task_manager = TaskManager(cfg, logger, db_manager, None)
        task_config = TaskConfig(
            id=10,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1h")),
            strategies=["macd_triple_divergence"],
            live_execution_mode="manual_notify",
        )
        task_manager._build_task = lambda task_cfg, exchange: _FakeLiveTraderTask(task_cfg, cfg, logger, db_manager, exchange)

        task_manager.add_tasks([task_config], asyncio.Queue())
        while task_config.id not in task_manager.tasks:
            await asyncio.sleep(0)

        await task_manager.close()

        assert task_config.id in task_manager.tasks
        assert task_manager.tasks[task_config.id].ts.state == TaskStateType.RUNNING
        assert [batch[0]["state"] for batch in saved_batches] == ["RUNNING", "RUNNING"]

    asyncio.run(_test())


def test_task_manager_closes_persisted_running_task_not_loaded_in_memory():
    cfg = Config(tasks="[]")
    logger = Logger(cfg)

    async def _test():
        persisted = TaskState(
            8,
            "8.DEBUG",
            __import__("datetime").datetime.now(),
            config_json='[{"task_type":"DEBUG","limit":1,"user_id":3,"run_id":"run-8"}]',
            user_id=3,
        )
        persisted.state = TaskStateType.RUNNING
        saved_batches = []

        class _TaskRepo:
            async def get_task_for_user(self, task_id, user_id):
                if task_id == persisted.id and user_id == persisted.user_id:
                    return persisted
                return None

            async def add_tasks(self, states):
                saved_batches.append([state.to_dict() for state in states])
                return len(states)

        task_manager = TaskManager(cfg, logger, SimpleNamespace(task=_TaskRepo()), None)

        assert await task_manager.close_task_state(8, user_id=3) is True
        assert persisted.state == TaskStateType.DONE
        assert saved_batches[-1][0]["state"] == "DONE"

    asyncio.run(_test())

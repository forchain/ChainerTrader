import os
from argparse import Namespace

import pytest

from trader.app.app import App
from trader.common import path
from trader.common.common import NAME
from trader.common.config import Config, default, new_and_env


def test_app():
    app = App()
    assert NAME == app.name()


def test_path():
    print(path.GetProjectDir())


def test_data_path():
    assert os.path.exists(path.get_file_path("ETHUSDT-1h-202301-202401.csv"))


def test_log():
    cfg = default()
    cfg.log_level = "DEBUG"
    app = App()
    app.log().debug("I am test logger by debug")
    app.log().info("I am test logger by info")
    app.log().warning("I am test logger by warn")
    app.log().error("I am test logger by error")
    app.log().critical("I am test logger by critical")


def test_version():
    app = App()
    print(app.version())


def test_registration_enabled_defaults_to_true(monkeypatch):
    monkeypatch.delenv("TRADER_REGISTRATION_ENABLED", raising=False)
    assert new_and_env().registration_enabled is True


def test_registration_enabled_environment_and_cli_precedence(monkeypatch):
    monkeypatch.setenv("TRADER_REGISTRATION_ENABLED", "false")
    assert new_and_env().registration_enabled is False
    assert new_and_env(Namespace(registration_enabled=True)).registration_enabled is True
    assert new_and_env(Namespace(registration_enabled=False)).registration_enabled is False


def test_registration_enabled_rejects_invalid_environment_value(monkeypatch):
    monkeypatch.setenv("TRADER_REGISTRATION_ENABLED", "flase")
    with pytest.raises(ValueError, match="invalid boolean configuration value"):
        new_and_env()


@pytest.mark.parametrize("value", ["1", "yes", "on"])
def test_registration_enabled_accepts_truthy_aliases(monkeypatch, value):
    monkeypatch.setenv("TRADER_REGISTRATION_ENABLED", value)
    assert new_and_env().registration_enabled is True


@pytest.mark.parametrize("value", ["0", "no", "off"])
def test_registration_enabled_accepts_falsey_aliases(monkeypatch, value):
    monkeypatch.setenv("TRADER_REGISTRATION_ENABLED", value)
    assert new_and_env().registration_enabled is False


def test_registration_enabled_is_exported_and_serialized(monkeypatch):
    cfg = Config(registration_enabled=False)
    cfg.export_env()
    assert os.environ["TRADER_REGISTRATION_ENABLED"] == "False"
    assert cfg.to_dict()["registration_enabled"] is False
    assert cfg.safe_to_dict()["registration_enabled"] is False


def test_registration_enabled_does_not_shift_legacy_positional_config_args():
    cfg = Config(
        0.001,
        14,
        False,
        False,
        None,
        "INFO",
        None,
        None,
        "trader",
        1000,
        None,
        100000.0,
        50,
        None,
        None,
        None,
        None,
        None,
        None,
        False,
        24,
        3.0,
    )
    assert cfg.leverage_ratio == 3.0
    assert cfg.registration_enabled is True


def test_app_start_cleans_up_threads_with_sqlite_db(tmp_path, monkeypatch):
    import asyncio
    import threading
    from tortoise import Tortoise
    from trader.database.config import build_tortoise_config
    from trader.common.message import new_exit_msg

    db_path = tmp_path / "test_app_exit.db"
    db_url = f"sqlite://{db_path}"

    async def _init_schema():
        await Tortoise.init(config=build_tortoise_config(db_url))
        await Tortoise.generate_schemas()
        await Tortoise.close_connections()

    asyncio.run(_init_schema())

    cfg = Config(db=db_url, tasks="[]")
    app = App(cfg)

    # Return exit message immediately so start() finishes without hanging
    monkeypatch.setattr(app.task_manager, "start", lambda *args, **kwargs: new_exit_msg())

    started = app.start()
    app.stop()

    assert started is True
    active_thread_names = [t.name for t in threading.enumerate()]
    assert not any("_connection_worker_thread" in name for name in active_thread_names), (
        f"aiosqlite worker threads were leaked: {active_thread_names}"
    )



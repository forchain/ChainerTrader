from __future__ import annotations

import tomllib
from pathlib import Path

from trader.common.config import Config


def test_pyproject_scripts_point_to_composition_root_and_db_tool():
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject["project"]["scripts"]
    assert scripts["trader"] == "trader.main:main"
    assert scripts["trader-db"] == "trader.tools.db:main"


def test_compose_application_wires_container_and_promotes_short_margin_mode(monkeypatch):
    from trader.main import AppContainer, compose_application

    cfg = Config(
        exchange='{"name":"BINANCE","api_key":"k","api_secret":"s","margin_mode":"spot"}',
        tasks='[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1h","strategies":"macd_triple_divergence","strategy_params":{"chainer_mode":"BOTH"}}]',
    )
    container = compose_application(cfg)
    assert isinstance(container, AppContainer)
    assert container.exchange is not None
    assert container.exchange.margin_mode.value == "cross_margin"
    assert container.task_manager is not None
    assert container.report_store is not None
    assert container.config_file_store is not None


def test_main_routes_api_vs_console_mode(monkeypatch):
    import trader.main as main_mod

    called = []
    monkeypatch.delenv("TRADER_API", raising=False)
    monkeypatch.setattr(main_mod, "load_dotenv", lambda: None)
    monkeypatch.setattr(main_mod, "run_api_mode", lambda cfg: called.append(("api", cfg.api)))
    monkeypatch.setattr(main_mod, "run_console_mode", lambda cfg: called.append(("console", cfg.api)))

    main_mod.main(["--api", "127.0.0.1:8000"])
    main_mod.main([])

    assert called == [("api", "127.0.0.1:8000"), ("console", None)]


def test_main_version_exits_early_without_starting_modes(monkeypatch, capsys):
    import trader.main as main_mod

    called = []
    monkeypatch.delenv("TRADER_API", raising=False)
    monkeypatch.setattr(main_mod, "load_dotenv", lambda: None)
    monkeypatch.setattr(main_mod, "run_api_mode", lambda cfg: called.append("api"))
    monkeypatch.setattr(main_mod, "run_console_mode", lambda cfg: called.append("console"))

    main_mod.main(["--version"])

    out = capsys.readouterr().out.strip()
    assert out != ""
    assert called == []


def test_app_accepts_injected_container():
    from trader.app.app import App
    from trader.main import compose_application

    cfg = Config()
    container = compose_application(cfg)
    app = App(cfg, container=container)
    assert app.task_manager is container.task_manager
    assert app.notify_mgr is container.notify_mgr
    assert app.stat is container.stat

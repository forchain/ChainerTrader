from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

from trader.core.task.domain import TaskState, TaskType
from trader.statistics.stat import BackTraderStat


def test_cli_rendering_statistics_signals_and_optimization():
    from trader.adapters.inbound.cli import (
        render_optimization_summary_table,
        render_signal_table,
        render_statistics_table,
    )

    tret = SimpleNamespace(
        total_return_rate=12.34,
        hold_rate=5.0,
        max_drawdown=3.21,
        max_drawdown_duration=4,
        volatility=1.5,
        win_rate=60.0,
        plr=1.8,
        avg_profit=150.0,
        avg_loss=-80.0,
        buys=3,
        sells=3,
        data_len=100,
        operates=[],
    )
    ts = TaskState(1, "1.BACK_TRADER.BTCUSDT-1h", datetime(2026, 1, 1), user_id=0)
    ts.tret = tret
    stat_table = render_statistics_table([BackTraderStat("macd_triple_divergence", "BTCUSDT-1h", ts)])
    assert "BTCUSDT-1h" in stat_table
    assert "12.34%" in stat_table
    assert "3/3" in stat_table

    sig_table = render_signal_table(
        [
            {
                "signal_time": "2026-01-01T00:00:00",
                "symbol": "BTC-USDT",
                "interval": "1h",
                "strategy": "macd_triple_divergence",
                "side": "LONG",
                "price": 100.0,
            }
        ]
    )
    assert "Signal Time (Local)" in sig_table
    assert "BTC-USDT" in sig_table
    assert "LONG" in sig_table

    opt_table = render_optimization_summary_table(
        [
            {
                "symbol": "BTCUSDT",
                "interval": "1h",
                "param_id": "abc123",
                "score": 82.5,
                "avg_total_return_pct": 18.2,
                "avg_excess_return_pct": 11.1,
                "avg_max_dd_pct": 4.5,
                "total_trades": 12,
            }
        ]
    )
    assert "BTCUSDT" in opt_table
    assert "abc123" in opt_table
    assert "82.50" in opt_table


def test_console_runner_runs_startup_once_without_recovery_and_cleans_up():
    from trader.adapters.inbound.cli import ConsoleRunner

    events: list[str] = []

    class _FakeDb:
        started = False

        async def start(self):
            self.started = True
            events.append("db.start")

        async def stop(self):
            self.started = False
            events.append("db.stop")

        async def get_startup_admin(self):
            return SimpleNamespace(id=7)

    class _FakeTaskManager:
        def start(self, taskcs):
            events.append(f"tm.start:{len(taskcs)}")
            from trader.common.message import new_add_tasks_msg

            return new_add_tasks_msg(taskcs)

        def add_tasks(self, taskcs, queue):
            events.append(f"tm.add:{len(taskcs)}:{taskcs[0].user_id}")
            from trader.common.message import new_exit_msg

            queue.put_nowait(new_exit_msg())

        async def close(self):
            events.append("tm.close")

        def stop(self):
            events.append("tm.stop")

    class _FakeStat:
        def handler(self, msg):
            events.append("stat.handler")

        def report(self):
            events.append("stat.report")

    class _FakeContainer:
        cfg = SimpleNamespace(tasks="mock", is_server=lambda: False)
        logger = SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            error=lambda *a, **k: None,
            debug=lambda *a, **k: None,
            log=lambda: SimpleNamespace(info=lambda *a, **k: None),
        )
        db_manager = _FakeDb()
        exchange = SimpleNamespace(start=lambda: events.append("ex.start"), stop=lambda: events.append("ex.stop"))
        tasks_cfg = [SimpleNamespace(id=1, ttype=TaskType.DEBUG, user_id=None)]
        notify_mgr = SimpleNamespace(start=lambda: events.append("notify.start"), handler=lambda msg: None)
        stat = _FakeStat()
        task_manager = _FakeTaskManager()
        bootstrap_admin_fn = lambda *a, **k: asyncio.sleep(0)  # noqa: E731
        recovery_runner = SimpleNamespace(
            execute=lambda *a, **k: (_ for _ in ()).throw(AssertionError("console mode must not recover tasks"))
        )

    runner = ConsoleRunner(_FakeContainer())
    ok = runner.run()
    assert ok is True
    assert "db.start" in events
    assert "ex.start" in events
    assert "tm.start:1" in events
    assert "tm.add:1:7" in events
    assert "tm.close" in events
    assert "db.stop" in events
    assert "stat.report" in events
    assert "tm.stop" in events
    assert "ex.stop" in events

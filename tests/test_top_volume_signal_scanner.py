import asyncio
import datetime as dt
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from trader.scanner.top_volume_signal_scanner import (
    DEFAULT_SYMBOL_WHITELIST,
    STABLECOIN_BASE_ASSETS,
    build_scan_report,
    compute_scan_windows,
    dump_signals_json,
    ensure_symbol_window,
    extend_window_for_warmup,
    extract_entry_signals,
    fetch_top_usdt_symbols,
    load_window_klines,
    normalize_symbol,
    render_signal_table,
    run_strategy_triggered_signals,
    scan_market,
    scan_market_report,
    select_whitelist_usdt_symbols,
    select_top_usdt_symbols,
)
from trader.strategy.base_strategy import BaseStrategy
from trader.task.task_type import TaskType
from trader.utils.kline import Kline
from trader.utils.symbol_interval import Interval


def test_select_top_usdt_symbols_filters_stablecoins_and_limits_to_top_n():
    exchange_info = {
        "symbols": [
            {"symbol": "BTCUSDT", "status": "TRADING", "isSpotTradingAllowed": True, "quoteAsset": "USDT", "baseAsset": "BTC"},
            {"symbol": "ETHUSDT", "status": "TRADING", "isSpotTradingAllowed": True, "quoteAsset": "USDT", "baseAsset": "ETH"},
            {"symbol": "BNBUSDT", "status": "TRADING", "isSpotTradingAllowed": True, "quoteAsset": "USDT", "baseAsset": "BNB"},
            {"symbol": "USDCUSDT", "status": "TRADING", "isSpotTradingAllowed": True, "quoteAsset": "USDT", "baseAsset": "USDC"},
            {"symbol": "FDUSDUSDT", "status": "TRADING", "isSpotTradingAllowed": True, "quoteAsset": "USDT", "baseAsset": "FDUSD"},
            {"symbol": "ETHBTC", "status": "TRADING", "isSpotTradingAllowed": True, "quoteAsset": "BTC", "baseAsset": "ETH"},
        ]
    }
    tickers = [
        {"symbol": "USDCUSDT", "quoteVolume": "9999999"},
        {"symbol": "BTCUSDT", "quoteVolume": "5000"},
        {"symbol": "ETHUSDT", "quoteVolume": "7000"},
        {"symbol": "BNBUSDT", "quoteVolume": "3000"},
        {"symbol": "FDUSDUSDT", "quoteVolume": "8000000"},
        {"symbol": "ETHBTC", "quoteVolume": "10000000"},
    ]

    selected = select_top_usdt_symbols(exchange_info, tickers, top_n=2)

    assert "USDCUSDT" not in selected
    assert "FDUSDUSDT" not in selected
    assert selected == ["ETHUSDT", "BTCUSDT"]


def test_select_whitelist_usdt_symbols_preserves_whitelist_order():
    exchange_info = {
        "symbols": [
            {"symbol": "ETHUSDT", "status": "TRADING", "isSpotTradingAllowed": True, "quoteAsset": "USDT", "baseAsset": "ETH"},
            {"symbol": "BTCUSDT", "status": "TRADING", "isSpotTradingAllowed": True, "quoteAsset": "USDT", "baseAsset": "BTC"},
            {"symbol": "XRPUSDT", "status": "TRADING", "isSpotTradingAllowed": True, "quoteAsset": "USDT", "baseAsset": "XRP"},
            {"symbol": "USDCUSDT", "status": "TRADING", "isSpotTradingAllowed": True, "quoteAsset": "USDT", "baseAsset": "USDC"},
        ]
    }

    selected = select_whitelist_usdt_symbols(exchange_info, whitelist_bases=("BTC", "ETH", "XRP"), top_n=2)

    assert selected == ["BTCUSDT", "ETHUSDT"]


def test_fetch_top_usdt_symbols_uses_binance_exchange_info_and_whitelist_order():
    exchange_info = {
        "symbols": [
            {"symbol": "ETHUSDT", "status": "TRADING", "isSpotTradingAllowed": True, "quoteAsset": "USDT", "baseAsset": "ETH"},
            {"symbol": "BTCUSDT", "status": "TRADING", "isSpotTradingAllowed": True, "quoteAsset": "USDT", "baseAsset": "BTC"},
            {"symbol": "BNBUSDT", "status": "TRADING", "isSpotTradingAllowed": True, "quoteAsset": "USDT", "baseAsset": "BNB"},
        ]
    }

    with patch("trader.scanner.top_volume_signal_scanner.requests.get") as mock_get:
        mock_get.return_value = Mock(json=Mock(return_value=exchange_info))

        selected = fetch_top_usdt_symbols(top_n=2)

    assert selected == ["BTCUSDT", "ETHUSDT"]
    assert mock_get.call_args_list[0].args[0].endswith("/api/v3/exchangeInfo")
    assert len(mock_get.call_args_list) == 1


def test_default_symbol_whitelist_matches_requested_universe():
    assert DEFAULT_SYMBOL_WHITELIST == ("BTC", "ETH", "BNB", "XRP", "SOL", "TRX", "DOGE", "ADA", "BCH", "XLM")


def test_compute_scan_windows_uses_30d_for_daily_and_7d_for_hourly():
    now = int(dt.datetime(2026, 4, 9, 12, 0, 0).timestamp())

    windows = compute_scan_windows(now)

    assert windows
    assert windows[next(iter([k for k in windows if k.value == "1d"]))][1] == now
    assert windows[next(iter([k for k in windows if k.value == "1h"]))][1] == now
    assert windows[next(iter([k for k in windows if k.value == "1d"]))][0] == now - 30 * 24 * 60 * 60
    assert windows[next(iter([k for k in windows if k.value == "1h"]))][0] == now - 7 * 24 * 60 * 60


def test_extend_window_for_warmup_adds_history_without_shifting_end():
    start, end = extend_window_for_warmup(Interval.INTERVAL_1h, 1000, 2000, warmup_bars=10)

    assert start == 1000 - 10 * 60 * 60
    assert end == 2000


def test_extract_entry_signals_maps_divergence_types_and_ignores_non_entry_events():
    events = [
        {
            "signal_time": "2026-04-09T10:00:00",
            "signal_type": "bottom_divergence",
            "signal_bar": {"close": 101.0},
            "legs": [{"macd_trough": -1.2}],
            "conditions": {"macd_higher_troughs": {"passed": True}},
        },
        {"signal_time": "2026-04-09T11:00:00", "signal_type": "top_divergence", "signal_bar": {"close": 99.0}},
        {"signal_time": "2026-04-09T12:00:00", "side": "CLOSE", "signal_bar": {"close": 100.0}},
        {"signal_time": "2026-04-09T13:00:00", "side": "STOP", "signal_bar": {"close": 98.0}},
    ]

    extracted = extract_entry_signals(events, symbol="BTCUSDT", interval="1h", strategy_name="macd_triple_divergence")

    assert extracted == [
        {
            "signal_time": "2026-04-09T10:00:00",
            "symbol": "BTCUSDT",
            "interval": "1h",
            "strategy": "macd_triple_divergence",
            "side": "LONG",
            "price": 101.0,
            "signal_type": "bottom_divergence",
            "signal_bar": {"close": 101.0},
            "signal_time_local": "2026-04-09T10:00:00+08:00",
            "signal_time_utc": "2026-04-09T02:00:00+00:00",
            "signal_timezone": "CST (+08:00)",
            "legs": [{"macd_trough": -1.2}],
            "conditions": {"macd_higher_troughs": {"passed": True}},
            "trade_outcome": {},
        },
        {
            "signal_time": "2026-04-09T11:00:00",
            "symbol": "BTCUSDT",
            "interval": "1h",
            "strategy": "macd_triple_divergence",
            "side": "SHORT",
            "price": 99.0,
            "signal_type": "top_divergence",
            "signal_bar": {"close": 99.0},
            "signal_time_local": "2026-04-09T11:00:00+08:00",
            "signal_time_utc": "2026-04-09T03:00:00+00:00",
            "signal_timezone": "CST (+08:00)",
            "legs": [],
            "conditions": {},
            "trade_outcome": {},
        },
    ]


def test_extract_entry_signals_filters_out_warmup_period_events():
    events = [
        {"signal_time": "2026-04-09T09:59:59", "signal_type": "bottom_divergence", "signal_bar": {"close": 100.0}},
        {"signal_time": "2026-04-09T10:00:00", "signal_type": "bottom_divergence", "signal_bar": {"close": 101.0}},
        {"signal_time": "2026-04-09T11:00:01", "signal_type": "top_divergence", "signal_bar": {"close": 99.0}},
    ]

    extracted = extract_entry_signals(
        events,
        symbol="BTCUSDT",
        interval="1h",
        strategy_name="macd_triple_divergence",
        start_time=int(dt.datetime(2026, 4, 9, 10, 0, 0).timestamp()),
        end_time=int(dt.datetime(2026, 4, 9, 11, 0, 0).timestamp()),
    )

    assert [item["signal_time"] for item in extracted] == ["2026-04-09T10:00:00"]


def test_stablecoin_blacklist_covers_required_assets():
    for asset in ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI", "USD1", "USDE", "USDS", "PYUSD"):
        assert asset in STABLECOIN_BASE_ASSETS


def test_load_window_klines_reads_requested_symbol_interval_from_db():
    async def _test():
        db_manager = SimpleNamespace(
            kline=SimpleNamespace(
                get_klines=AsyncMock(return_value=["k1", "k2"]),
            )
        )

        result = await load_window_klines(db_manager, "BTC-USDT", Interval.INTERVAL_1h, 10, 20)

        assert result == ["k1", "k2"]
        args = db_manager.kline.get_klines.call_args.args
        assert args == ("BTCUSDT-1h", 10, 20)

    asyncio.run(_test())


def test_normalize_symbol_accepts_binance_compact_symbol():
    assert normalize_symbol("BTCUSDT") == "BTC-USDT"
    assert normalize_symbol("BTC-USDT") == "BTC-USDT"


def test_ensure_symbol_window_builds_update_task_with_requested_range():
    async def _run():
        cfg = SimpleNamespace()
        logger = SimpleNamespace()
        db_manager = SimpleNamespace()
        exchange = SimpleNamespace()

        with patch("trader.scanner.top_volume_signal_scanner.UpdateKlinesTask") as task_cls:
            task = task_cls.return_value
            task.start = AsyncMock()

            await ensure_symbol_window(
                cfg,
                logger,
                db_manager,
                exchange,
                "BTCUSDT",
                Interval.INTERVAL_1d,
                100,
                200,
            )

        tcfg = task_cls.call_args.args[0]
        assert tcfg.ttype == TaskType.UPDATE_KLINES
        assert tcfg.symbol_interval.name() == "BTCUSDT-1d"
        assert tcfg.start_time == 100
        assert tcfg.end_time == 200

    import asyncio

    asyncio.run(_run())


def test_render_signal_table_contains_expected_columns():
    table = render_signal_table(
        [
            {
                "signal_time": "2026-04-09T10:00:00",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "strategy": "macd_triple_divergence",
                "side": "LONG",
                "price": 100.0,
            }
        ]
    )

    assert "Signal Time (Local)" in table
    assert "BTCUSDT" in table
    assert "LONG" in table


def test_scan_market_updates_db_then_reads_db_and_sorts_results():
    async def _run():
        cfg = SimpleNamespace(cash=100000.0, commission=0.001)
        logger = SimpleNamespace()
        db_manager = SimpleNamespace()
        exchange = SimpleNamespace()

        with (
            patch("trader.scanner.top_volume_signal_scanner.fetch_top_usdt_symbols", return_value=["BTC-USDT", "ETH-USDT"]),
            patch("trader.scanner.top_volume_signal_scanner.ensure_symbol_window") as ensure_mock,
            patch("trader.scanner.top_volume_signal_scanner.load_window_klines", new=AsyncMock(return_value=["klines"])) as load_mock,
            patch(
                "trader.scanner.top_volume_signal_scanner.run_strategy_triggered_signals",
                side_effect=[
                    [
                        {
                            "signal_time": "2026-04-09T12:00:00",
                            "symbol": "BTC-USDT",
                            "interval": "1d",
                            "strategy": "macd_triple_divergence",
                            "side": "LONG",
                            "price": 100,
                        }
                    ],
                    [
                        {
                            "signal_time": "2026-04-09T10:00:00",
                            "symbol": "BTC-USDT",
                            "interval": "1h",
                            "strategy": "macd_triple_divergence",
                            "side": "SHORT",
                            "price": 99,
                        }
                    ],
                    [],
                    [
                        {
                            "signal_time": "2026-04-09T11:00:00",
                            "symbol": "ETH-USDT",
                            "interval": "1h",
                            "strategy": "macd_triple_divergence",
                            "side": "LONG",
                            "price": 50,
                        }
                    ],
                ],
            ) as run_mock,
        ):
            results = await scan_market(
                cfg,
                logger,
                db_manager,
                exchange,
                top_n=2,
                strategy_name="macd_triple_divergence",
                now_ts=int(dt.datetime(2026, 4, 9, 12, 0, 0).timestamp()),
            )

        assert ensure_mock.await_count == 4
        assert load_mock.call_count == 4
        assert run_mock.call_count == 4
        first_ensure_args = ensure_mock.await_args_list[0].args
        assert first_ensure_args[6] < int(dt.datetime(2026, 3, 10, 12, 0, 0).timestamp())
        assert [item["signal_time"] for item in results] == [
            "2026-04-09T10:00:00",
            "2026-04-09T11:00:00",
            "2026-04-09T12:00:00",
        ]

    import asyncio

    asyncio.run(_run())


def test_run_strategy_triggered_signals_uses_strategy_signal_events():
    class _FakeStrategy(BaseStrategy):
        params = ()

        def __init__(self):
            super().__init__()
            self._signal_events = []

        def log_info(self, msg):
            pass

        def log_debug(self, msg):
            pass

        def next(self):
            if len(self) == 1:
                self._signal_events = [
                    {"signal_time": "2026-04-09T10:00:00", "signal_type": "bottom_divergence", "signal_bar": {"close": 101.0}},
                    {"signal_time": "2026-04-09T11:00:00", "side": "STOP", "signal_bar": {"close": 99.0}},
                ]

    klines = [
        Kline(1, 100, 101, 99, 100, 2, 1, 1, 1, 1, 1),
        Kline(3, 100, 102, 98, 101, 4, 1, 1, 1, 1, 1),
    ]

    with patch("trader.scanner.top_volume_signal_scanner.parse_strategy", return_value=_FakeStrategy):
        signals = run_strategy_triggered_signals(
            "fake_strategy",
            "BTCUSDT",
            Interval.INTERVAL_1h,
            klines,
            signal_start_time=int(dt.datetime(2026, 4, 9, 10, 0, 0).timestamp()),
            signal_end_time=int(dt.datetime(2026, 4, 9, 10, 30, 0).timestamp()),
        )

    assert signals == [
        {
            "signal_time": "2026-04-09T10:00:00",
            "signal_time_local": "2026-04-09T10:00:00+08:00",
            "signal_time_utc": "2026-04-09T02:00:00+00:00",
            "signal_timezone": "CST (+08:00)",
            "symbol": "BTCUSDT",
            "interval": "1h",
            "strategy": "fake_strategy",
            "side": "LONG",
            "price": 101.0,
            "signal_type": "bottom_divergence",
            "signal_bar": {"close": 101.0},
            "legs": [],
            "conditions": {},
            "trade_outcome": {},
        }
    ]


def test_dump_signals_json_writes_expected_payload(tmp_path):
    output = tmp_path / "signals.json"
    payload = [
        {
            "signal_time": "2026-04-09T10:00:00",
            "symbol": "BTCUSDT",
            "interval": "1h",
            "strategy": "macd_triple_divergence",
            "side": "LONG",
            "price": 101.0,
        }
    ]

    dump_signals_json(output, payload)

    assert json.loads(output.read_text()) == payload


def test_build_scan_report_includes_window_metadata_and_signals():
    windows = {
        Interval.INTERVAL_1d: (int(dt.datetime(2026, 3, 10, 0, 0, 0).timestamp()), int(dt.datetime(2026, 4, 9, 0, 0, 0).timestamp())),
        Interval.INTERVAL_1h: (int(dt.datetime(2026, 4, 2, 0, 0, 0).timestamp()), int(dt.datetime(2026, 4, 9, 0, 0, 0).timestamp())),
    }
    signals = [{"signal_time": "2026-04-08T02:00:00", "symbol": "ZECUSDT"}]

    report = build_scan_report(
        signals=signals,
        strategy_name="macd_triple_divergence",
        top_n=10,
        selected_symbols=["BTCUSDT", "ZECUSDT"],
        windows=windows,
        generated_at_ts=int(dt.datetime(2026, 4, 9, 12, 0, 0).timestamp()),
    )

    assert report["report"]["requested_top"] == 10
    assert report["report"]["selected_symbols"] == ["BTCUSDT", "ZECUSDT"]
    assert report["report"]["signals_count"] == 1
    assert report["report"]["scan_windows"]["1d"]["signal_window_start_local"] == "2026-03-10T00:00:00+08:00"
    assert report["signals"] == signals


def test_scanner_cli_defaults_and_json_output(tmp_path, monkeypatch, capsys):
    import scripts.run_top_volume_signal_scanner as cli

    output = tmp_path / "signals.json"
    report = {
        "report": {"requested_top": 10, "signals_count": 1},
        "signals": [
            {
                "signal_time": "2026-04-09T10:00:00",
                "signal_time_local": "2026-04-09T10:00:00+08:00",
                "signal_time_utc": "2026-04-09T02:00:00+00:00",
                "signal_timezone": "CST (+08:00)",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "strategy": "macd_triple_divergence",
                "side": "LONG",
                "price": 101.0,
                "signal_type": "bottom_divergence",
                "signal_bar": {"close": 101.0},
                "legs": [],
                "conditions": {},
                "trade_outcome": {},
            }
        ],
    }
    db_manager = Mock()

    monkeypatch.setattr(
        cli,
        "build_runtime_config",
        lambda: (
            SimpleNamespace(cash=100000.0, commission=0.001),
            SimpleNamespace(),
            db_manager,
            SimpleNamespace(),
        ),
    )

    async def _fake_scan_market(cfg, log, db_manager_arg, exchange, top_n, strategy_name):
        assert top_n == 10
        assert strategy_name == "macd_triple_divergence"
        assert db_manager_arg is db_manager
        return report

    monkeypatch.setattr(cli, "scan_market_report", _fake_scan_market)
    monkeypatch.setattr(
        cli,
        "parse_args",
        lambda: SimpleNamespace(strategy="macd_triple_divergence", top=10, json_out=str(output)),
    )

    assert cli.main() == 0
    assert json.loads(output.read_text()) == report
    assert "BTCUSDT" in capsys.readouterr().out
    db_manager.stop.assert_called_once()


def test_scan_market_report_wraps_signals_with_metadata():
    async def _run():
        cfg = SimpleNamespace(cash=100000.0, commission=0.001)
        logger = SimpleNamespace()
        db_manager = SimpleNamespace()
        exchange = SimpleNamespace()

        with (
            patch("trader.scanner.top_volume_signal_scanner.fetch_top_usdt_symbols", return_value=["BTCUSDT"]),
            patch(
                "trader.scanner.top_volume_signal_scanner.scan_market",
                return_value=[{"signal_time": "2026-04-09T10:00:00", "symbol": "BTCUSDT"}],
            ),
        ):
            report = await scan_market_report(
                cfg,
                logger,
                db_manager,
                exchange,
                top_n=1,
                strategy_name="macd_triple_divergence",
                now_ts=int(dt.datetime(2026, 4, 9, 12, 0, 0).timestamp()),
            )

        assert report["report"]["requested_top"] == 1
        assert report["report"]["selected_symbols"] == ["BTCUSDT"]
        assert report["signals"] == [{"signal_time": "2026-04-09T10:00:00", "symbol": "BTCUSDT"}]

    import asyncio

    asyncio.run(_run())


def test_scanner_cli_exits_non_zero_for_unknown_strategy(monkeypatch):
    import scripts.run_top_volume_signal_scanner as cli

    monkeypatch.setattr(cli, "parse_strategy", lambda name: None)
    monkeypatch.setattr("sys.argv", ["run_top_volume_signal_scanner.py", "--strategy", "unknown_strategy"])

    with pytest.raises(SystemExit) as exc:
        cli.parse_args()

    assert exc.value.code == 2

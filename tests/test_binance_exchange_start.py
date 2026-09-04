from datetime import datetime

from trader.exchange.binance.exchange import BinanceExchange
from trader.exchange.exchange_config import ExchangeConfig


class DummyLog:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


def test_start_skips_margin_summary_when_base_path_is_blank(monkeypatch):
    margin_calls = []

    class FakeMarginTradingManager:
        def __init__(self, *args, **kwargs):
            margin_calls.append("init")

        def get_summary_of_margin_account(self):
            margin_calls.append("summary")

    monkeypatch.setattr("trader.exchange.binance.exchange.MarginTradingManager", FakeMarginTradingManager)
    monkeypatch.setattr(BinanceExchange, "ping", lambda self: True)
    monkeypatch.setattr(BinanceExchange, "time", lambda self: datetime(2026, 4, 13, 20, 54, 33))
    monkeypatch.setattr(BinanceExchange, "server_time_offset", lambda self: 0.0)

    exchange = BinanceExchange(ExchangeConfig(base_path=""), DummyLog())

    assert exchange.start() is True
    assert margin_calls == []

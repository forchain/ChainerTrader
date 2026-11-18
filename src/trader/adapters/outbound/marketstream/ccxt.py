"""CCXT polling market stream adapter."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Awaitable, Callable

from trader.core.marketdata.interfaces import DisconnectCallback, UpdateCallback
from trader.core.marketdata.stream import MarketStreamKey
from trader.core.marketdata.warmup import KlineUpdate
from trader.core.shared.domain import Interval, Kline, SymbolInterval, get_time_duration


@dataclass
class _PollingStreamState:
    key: MarketStreamKey
    on_update: UpdateCallback
    on_disconnect: DisconnectCallback | None
    next_poll_at: float
    baseline_initialized: bool = False
    last_published_open_time: int | None = None


class CcxtPollingMarketStreamAdapter:
    def __init__(
        self,
        *,
        exchange=None,
        poll_interval_seconds: float | None = None,
        min_request_spacing_seconds: float | None = None,
        closed_kline_delay_seconds: float = 5.0,
        startup_stagger_seconds: float = 10.0,
        fetch_limit: int = 2,
        now_func: Callable[[], float] | None = None,
        sleep_func: Callable[[float], Awaitable[None]] | None = None,
    ):
        self.exchange = exchange
        if min_request_spacing_seconds is None:
            min_request_spacing_seconds = 10.0 if poll_interval_seconds is None else float(poll_interval_seconds)
        self.min_request_spacing_seconds = max(0.0, float(min_request_spacing_seconds))
        self.poll_interval_seconds = self.min_request_spacing_seconds
        self.closed_kline_delay_seconds = max(0.0, float(closed_kline_delay_seconds))
        self.startup_stagger_seconds = max(0.0, float(startup_stagger_seconds))
        self.fetch_limit = max(2, int(fetch_limit))
        self.now_func = now_func or time.time
        self.sleep_func = sleep_func or asyncio.sleep
        self._streams: dict[MarketStreamKey, _PollingStreamState] = {}
        self._scheduler_task: asyncio.Task | None = None
        self._last_request_at: float | None = None
        self._wakeup = asyncio.Event()

    def set_exchange(self, exchange) -> None:
        self.exchange = exchange

    async def start(self, key: MarketStreamKey, on_update: UpdateCallback, on_disconnect: DisconnectCallback | None = None) -> None:
        if self.exchange is None:
            raise RuntimeError("CCXT polling market stream requires an exchange")
        if key in self._streams:
            return
        next_poll_at = self._now()
        self._streams[key] = _PollingStreamState(key=key, on_update=on_update, on_disconnect=on_disconnect, next_poll_at=next_poll_at)
        self._wakeup.set()
        logging.info(
            "CCXT polling scheduler stream registered: stream=%s min_request_spacing_seconds=%s "
            "closed_kline_delay_seconds=%s startup_stagger_seconds=%s next_poll_at=%s fetch_limit=%s",
            key.stream_name(),
            self.min_request_spacing_seconds,
            self.closed_kline_delay_seconds,
            self.startup_stagger_seconds,
            int(next_poll_at),
            self.fetch_limit,
        )
        if self._scheduler_task is None or self._scheduler_task.done():
            logging.info("CCXT polling scheduler started: min_request_spacing_seconds=%s", self.min_request_spacing_seconds)
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())

    async def stop(self, key: MarketStreamKey, reason: str = "") -> None:
        state = self._streams.pop(key, None)
        if state is None:
            return
        self._wakeup.set()
        logging.info("CCXT polling scheduler stream removed: stream=%s reason=%s", key.stream_name(), reason or "unspecified")
        if self._streams:
            return
        task = self._scheduler_task
        self._scheduler_task = None
        if task is None:
            return
        task.cancel()
        if task is asyncio.current_task():
            return
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _scheduler_loop(self) -> None:
        try:
            while True:
                if not self._streams:
                    return
                state = self._next_due_stream()
                now = self._now()
                if state is None:
                    await self.sleep_func(1.0)
                    continue
                sleep_seconds = state.next_poll_at - now
                if sleep_seconds > 0:
                    await self._sleep_or_wakeup(sleep_seconds)
                    continue
                if self._last_request_at is not None:
                    spacing_sleep = self.min_request_spacing_seconds - (now - self._last_request_at)
                    if spacing_sleep > 0:
                        await self._sleep_or_wakeup(spacing_sleep)
                        continue
                await self._poll_stream(state)
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("CCXT polling scheduler failed")

    def _next_due_stream(self) -> _PollingStreamState | None:
        if not self._streams:
            return None
        now = self._now()
        return min(
            self._streams.values(),
            key=lambda item: (
                0.0 if item.next_poll_at <= now else item.next_poll_at,
                self._interval_seconds(item.key),
                item.key.stream_name(),
            ),
        )

    async def _sleep_or_wakeup(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self._wakeup.clear()
        sleep_task = asyncio.create_task(self.sleep_func(seconds))
        wake_task = asyncio.create_task(self._wakeup.wait())
        done, pending = await asyncio.wait({sleep_task, wake_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        for task in done:
            await task

    @staticmethod
    def _interval_seconds(key: MarketStreamKey) -> int:
        return get_time_duration(Interval(key.interval))

    async def _poll_stream(self, state: _PollingStreamState) -> None:
        key = state.key
        now = self._now()
        self._last_request_at = now
        logging.info("CCXT polling fetch started: stream=%s reason=interval_due", key.stream_name())
        try:
            klines = self._closed_klines(key)
        except Exception:
            logging.exception("CCXT polling fetch failed: stream=%s", key.stream_name())
            state.next_poll_at = self._now() + max(self.min_request_spacing_seconds, 1.0)
            if state.on_disconnect is not None:
                try:
                    await state.on_disconnect()
                except Exception:
                    logging.exception("CCXT polling disconnect recovery failed: stream=%s", key.stream_name())
            return
        if not state.baseline_initialized:
            state.baseline_initialized = True
            state.last_published_open_time = int(klines[-1].open_time) if klines else None
            state.next_poll_at = self._next_poll_at(key, state.last_published_open_time)
            logging.info(
                "CCXT polling baseline initialized: stream=%s baseline_open_time=%s next_poll_at=%s",
                key.stream_name(),
                state.last_published_open_time,
                int(state.next_poll_at),
            )
            return
        pending = self._new_closed_klines(state, klines)
        for kline in pending:
            logging.debug(
                "CCXT polling market stream new closed kline: stream=%s open_time=%s close_time=%s close=%s volume=%s",
                key.stream_name(),
                int(kline.open_time),
                int(kline.close_time),
                kline.close,
                kline.volume,
            )
            await state.on_update(_kline_to_update(key, kline))
        state.next_poll_at = self._next_poll_at(key, state.last_published_open_time)
        logging.debug(
            "CCXT polling fetch completed: stream=%s new_closed_klines=%s next_poll_at=%s",
            key.stream_name(),
            len(pending),
            int(state.next_poll_at),
        )

    def _new_closed_klines(self, state: _PollingStreamState, klines: list[Kline]) -> list[Kline]:
        last_open_time = state.last_published_open_time
        pending = [kline for kline in klines if last_open_time is None or int(kline.open_time) > last_open_time]
        if pending:
            state.last_published_open_time = int(pending[-1].open_time)
        return pending

    def _next_poll_at(self, key: MarketStreamKey, latest_open_time: int | None) -> float:
        now = self._now()
        duration = get_time_duration(Interval(key.interval))
        if latest_open_time is None:
            current_open = int(now // duration) * duration
            target = current_open + duration + self.closed_kline_delay_seconds
        else:
            target = int(latest_open_time) + duration + self.closed_kline_delay_seconds
        if target <= now:
            periods = int((now - target) // duration) + 1
            target += periods * duration
        return float(target)

    def _now(self) -> float:
        return float(self.now_func())

    def _closed_klines(self, key: MarketStreamKey) -> list[Kline]:
        symbol_interval = _symbol_interval_from_key(key)
        klines = self.exchange.get_latest_klines(symbol_interval, self.fetch_limit) or []
        closed = [kline for kline in klines if _is_closed_kline(kline, now_wall_time=int(self._now()))]
        return sorted(closed, key=lambda item: int(item.open_time))


def _symbol_interval_from_key(key: MarketStreamKey) -> SymbolInterval:
    symbol = key.symbol
    if "-" not in symbol:
        for quote in ("USDT", "USDC", "BUSD", "BTC", "ETH"):
            if symbol.endswith(quote) and len(symbol) > len(quote):
                symbol = f"{symbol[:-len(quote)]}-{quote}"
                break
    return SymbolInterval(symbol, Interval(key.interval))


def _is_closed_kline(kline: Kline, now_wall_time: int | None = None) -> bool:
    now = int(time.time()) if now_wall_time is None else int(now_wall_time)
    return int(kline.close_time) <= now


def _kline_to_update(key: MarketStreamKey, kline: Kline) -> KlineUpdate:
    return KlineUpdate(
        exchange=key.exchange,
        symbol=key.symbol,
        interval=key.interval,
        open_time=int(kline.open_time),
        close_time=int(kline.close_time),
        open=float(kline.open),
        high=float(kline.high),
        low=float(kline.low),
        close=float(kline.close),
        volume=float(kline.volume),
        event_time=int(kline.close_time),
        is_closed=True,
        vol_quote=float(kline.vol_quote),
        trades=int(kline.trades),
        vol_taker_base=float(kline.vol_taker_base),
        vol_taker_quote=float(kline.vol_taker_quote),
        ignore=float(kline.ignore),
    )

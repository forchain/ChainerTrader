from __future__ import annotations

import queue
from datetime import datetime
from enum import Enum

import backtrader as bt
from backtrader import date2num

from trader.live.market_data import KlineUpdate
from trader.utils.kline import Kline


class LiveFeedPhase(str, Enum):
    WARMUP = "warmup"
    LIVE = "live"


class _LiveMarker:
    pass


_LIVE_MARKER = _LiveMarker()


class LiveKlineDataFeed(bt.feed.DataBase):
    """Backtrader live data feed for closed K-line bars."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._queue: queue.Queue[tuple[LiveFeedPhase, Kline] | _LiveMarker] = queue.Queue()
        self._stopped = False
        self._delivered_open_times: set[int] = set()
        self.phase = LiveFeedPhase.WARMUP
        self._input_phase = LiveFeedPhase.WARMUP
        self._live_requested = False
        self.current_bar_phase = LiveFeedPhase.WARMUP
        self.latest_delivered_open_time: int | None = None
        self.warmup_complete = False

    def islive(self):
        return True

    def haslivedata(self):
        return not self._queue.empty()

    def start(self):
        super().start()
        self._stopped = False
        self.phase = LiveFeedPhase.WARMUP
        self._input_phase = LiveFeedPhase.LIVE if self._live_requested else LiveFeedPhase.WARMUP
        self.current_bar_phase = LiveFeedPhase.WARMUP
        self.latest_delivered_open_time = None
        self.warmup_complete = False

    def stop(self):
        self._stopped = True

    def mark_live(self) -> None:
        self._live_requested = True
        self._input_phase = LiveFeedPhase.LIVE
        self._queue.put(_LIVE_MARKER)

    def current_bar_is_live(self) -> bool:
        return self.current_bar_phase == LiveFeedPhase.LIVE

    def put_update(self, update: KlineUpdate) -> bool:
        if not update.is_closed:
            return False
        return self.put_kline(update.to_kline())

    def put_kline(self, kline: Kline) -> bool:
        open_time = int(kline.open_time)
        if open_time in self._delivered_open_times:
            return False
        self._delivered_open_times.add(open_time)
        self._queue.put((self._input_phase, kline))
        return True

    def _load(self):
        while True:
            if self._stopped and self._queue.empty():
                return False

            timeout = max(float(getattr(self, "_qcheck", 0.0) or 0.0), float(getattr(self.p, "qcheck", 0.0) or 0.0))
            try:
                if timeout > 0.0:
                    item = self._queue.get(timeout=timeout)
                else:
                    item = self._queue.get_nowait()
            except queue.Empty:
                return False if self._stopped else None

            if item is _LIVE_MARKER:
                self.phase = LiveFeedPhase.LIVE
                self._input_phase = LiveFeedPhase.LIVE
                self.warmup_complete = True
                self.put_notification(self.LIVE)
                continue

            phase, kline = item
            self.current_bar_phase = phase
            break

        self.lines.datetime[0] = date2num(datetime.fromtimestamp(int(kline.open_time)))
        self.lines.open[0] = float(kline.open)
        self.lines.high[0] = float(kline.high)
        self.lines.low[0] = float(kline.low)
        self.lines.close[0] = float(kline.close)
        self.lines.volume[0] = float(kline.volume)
        self.lines.openinterest[0] = 0.0
        self.latest_delivered_open_time = int(kline.open_time)
        return True

    def status(self) -> dict:
        return {
            "feed_phase": self.phase.value,
            "current_bar_phase": self.current_bar_phase.value,
            "latest_delivered_open_time": self.latest_delivered_open_time,
            "warmup_complete": self.warmup_complete,
            "alive": not self._stopped,
            "queued_bars": self._queue.qsize(),
        }

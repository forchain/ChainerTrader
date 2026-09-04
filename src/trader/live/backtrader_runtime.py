from __future__ import annotations

import threading
from typing import Iterable

import backtrader as bt
from backtrader import num2date

from trader.live.feed import LiveKlineDataFeed
from trader.utils.kline import Kline
from trader.utils.operate import Operate, OperateType
from trader.utils.operation_state import enrich_operation_from_trade_context


class LiveOperationAnalyzer(bt.Analyzer):
    params = (("operation_handler", None),)

    def __init__(self):
        self.position_size = 0.0

    def notify_order(self, order):
        if order.status != order.Completed or self.p.operation_handler is None:
            return
        executed_dt = getattr(order.executed, "dt", None)
        if executed_dt:
            dtime = int(num2date(executed_dt).timestamp())
        else:
            dtime = int(self.strategy.data.datetime.datetime(0).timestamp())
        prev_position = self.position_size
        order_size = float(getattr(order.executed, "size", 0.0) or 0.0)
        if order.isbuy():
            if prev_position < 0:
                otype = OperateType.CLOSE
            elif prev_position == 0:
                otype = OperateType.LONG
            else:
                otype = OperateType.BUY
            self.position_size += order_size
        else:
            if prev_position > 0:
                otype = OperateType.CLOSE
            elif prev_position == 0:
                otype = OperateType.SHORT
            else:
                otype = OperateType.SELL
            self.position_size -= abs(order_size)
        op = Operate(otype, dtime, float(order.executed.price))
        enrich_operation_from_trade_context(op, self._trade_context_for_order(order))
        self.p.operation_handler(op)

    def notify_trade(self, trade):
        self.position_size = float(getattr(self.strategy.position, "size", self.position_size) or 0.0)

    def _trade_context_for_order(self, order):
        tradeid = getattr(order, "tradeid", None)
        if tradeid is None:
            return None
        try:
            return getattr(self.strategy, "_trades_by_id", {}).get(int(tradeid))
        except (TypeError, ValueError):
            return None


class LiveProgressAnalyzer(bt.Analyzer):
    params = (("progress_handler", None),)

    def next(self):
        if self.p.progress_handler is None:
            return
        open_time = int(self.strategy.data.datetime.datetime(0).timestamp())
        self.p.progress_handler(open_time)


class BacktraderLiveRunner:
    def __init__(
        self,
        strategy,
        *,
        cash: float,
        commission: float,
        qcheck: float = 0.5,
        strategy_kwargs: dict | None = None,
        feed: LiveKlineDataFeed | None = None,
        operation_handler=None,
        inject_operation_sink: bool = False,
    ):
        self.strategy = strategy
        self.cash = float(cash)
        self.commission = float(commission)
        self.strategy_kwargs = dict(strategy_kwargs or {})
        self.operation_handler = operation_handler
        self.inject_operation_sink = bool(inject_operation_sink)
        self.feed = feed or LiveKlineDataFeed(qcheck=qcheck)
        self.cerebro = bt.Cerebro()
        self.cerebro.adddata(self.feed)
        if self.operation_handler is not None and self.inject_operation_sink:
            self.strategy_kwargs.setdefault("live_operation_sink", self._handle_operation)
        strategies = list(self.strategy) if isinstance(self.strategy, (list, tuple)) else [self.strategy]
        for strategy_cls in strategies:
            self.cerebro.addstrategy(strategy_cls, **self.strategy_kwargs)
        if self.operation_handler is not None:
            self.cerebro.addanalyzer(LiveOperationAnalyzer, _name="live_operation", operation_handler=self._handle_operation)
        self.cerebro.addanalyzer(
            LiveProgressAnalyzer,
            _name="live_progress",
            progress_handler=self._handle_processed_bar,
        )
        self.cerebro.broker.setcash(self.cash)
        self.cerebro.broker.setcommission(commission=self.commission, commtype=bt.CommInfoBase.COMM_PERC, stocklike=True)
        self._thread: threading.Thread | None = None
        self._exception: BaseException | None = None
        self._seen_operation_keys: set[tuple] = set()
        self._latest_processed_open_time: int | None = None

    def start(self, warmup: Iterable[Kline] | None = None) -> None:
        if self._thread is not None:
            raise RuntimeError("BacktraderLiveRunner already started")
        for kline in warmup or []:
            self.feed.put_kline(kline)
        self.feed.mark_live()
        self._thread = threading.Thread(target=self._run, name="backtrader-live-runner", daemon=True)
        self._thread.start()

    def put_kline(self, kline: Kline) -> bool:
        return self.feed.put_kline(kline)

    def status(self) -> dict:
        payload = self.feed.status()
        payload.update(
            {
                "running": self._thread is not None and self._thread.is_alive(),
                "legacy_fallback": False,
                "last_error": str(self._exception) if self._exception is not None else None,
                "latest_processed_open_time": self._latest_processed_open_time,
            }
        )
        return payload

    def stop(self, timeout: float = 5.0) -> None:
        self.feed.stop()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        if self._exception is not None:
            raise self._exception

    def _run(self) -> None:
        try:
            self.cerebro.run()
        except BaseException as exc:
            self._exception = exc
            log = self.strategy_kwargs.get("log")
            if log is not None and hasattr(log, "error"):
                log.error(f"Backtrader live runner failed: {exc}")

    def _handle_operation(self, operation) -> None:
        if self.operation_handler is None:
            return
        self._tag_operation_phase(operation)
        key = self._operation_key(operation)
        if key in self._seen_operation_keys:
            return
        self._seen_operation_keys.add(key)
        self.operation_handler(operation)

    def _handle_processed_bar(self, open_time: int) -> None:
        self._latest_processed_open_time = int(open_time)

    def _tag_operation_phase(self, operation) -> None:
        phase = getattr(self.feed, "current_bar_phase", None)
        if phase is None:
            return
        value = getattr(phase, "value", phase)
        setattr(operation, "feed_phase", str(value))

    @staticmethod
    def _operation_key(operation) -> tuple:
        side = operation.otype.name if getattr(operation, "otype", None) else "UNKNOWN"
        dtime = int(getattr(operation, "dtime", 0) or 0)
        price = float(getattr(operation, "price", 0.0) or 0.0)
        signal_event_id = getattr(operation, "signal_event_id", None)
        if signal_event_id:
            return ("signal_event_id", str(signal_event_id), side, dtime, f"{price:.12g}")
        return ("operation", side, dtime, f"{price:.12g}")

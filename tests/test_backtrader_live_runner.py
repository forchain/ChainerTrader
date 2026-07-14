import time

import backtrader as bt

from trader.common.config import Config
from trader.common.logger import Logger
from trader.live.backtrader_runtime import BacktraderLiveRunner
from trader.strategy.macd_triple_divergence import MacdTripleDivergenceStrategy
from trader.strategy.node import build_strategy_kwargs
from trader.utils.kline import Kline
from trader.utils.operate import Operate, OperateType

BASE = 1_714_281_600


class RecordingLiveStrategy(bt.Strategy):
    events = []
    instance_ids = []

    def __init__(self):
        RecordingLiveStrategy.instance_ids.append(id(self))

    def next(self):
        RecordingLiveStrategy.events.append((id(self), int(self.data.datetime.datetime(0).timestamp()), float(self.data.close[0])))


class OperationEveryBarStrategy(bt.Strategy):
    params = (("live_operation_sink", None),)

    def next(self):
        if self.p.live_operation_sink is not None:
            self.p.live_operation_sink(Operate(OperateType.BUY, int(self.data.datetime.datetime(0).timestamp()), float(self.data.close[0])))


class DuplicateOperationStrategy(bt.Strategy):
    params = (("live_operation_sink", None),)

    def next(self):
        if self.p.live_operation_sink is None:
            return
        op = Operate(OperateType.BUY, int(self.data.datetime.datetime(0).timestamp()), float(self.data.close[0]))
        op.signal_event_id = "same-signal"
        self.p.live_operation_sink(op)
        self.p.live_operation_sink(op)


class BuyOnceStrategy(bt.Strategy):
    def __init__(self):
        self.order = None

    def next(self):
        if self.order is None and not self.position:
            self.order = self.buy()

    def notify_order(self, order):
        if order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected):
            self.order = None


class ShortOnceStrategy(bt.Strategy):
    def __init__(self):
        self.order = None

    def next(self):
        if self.order is None and not self.position:
            self.order = self.sell()

    def notify_order(self, order):
        if order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected):
            self.order = None


def _kline(open_time, close):
    return Kline(open_time, close - 1, close + 1, close - 2, close, open_time + 59, 1, 1, 1, 1, 1)


def _wait_until(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


def test_backtrader_live_runner_warms_then_advances_same_strategy_instance():
    RecordingLiveStrategy.events = []
    RecordingLiveStrategy.instance_ids = []
    runner = BacktraderLiveRunner(RecordingLiveStrategy, cash=1000.0, commission=0.0, qcheck=0.001)

    runner.start(warmup=[_kline(BASE, 100.0), _kline(BASE + 60, 101.0)])
    try:
        _wait_until(lambda: len(RecordingLiveStrategy.events) >= 2)
        assert runner.status()["latest_processed_open_time"] == BASE + 60
        runner.put_kline(_kline(BASE + 120, 102.0))
        _wait_until(lambda: len(RecordingLiveStrategy.events) >= 3)
        assert runner.status()["latest_processed_open_time"] == BASE + 120
    finally:
        runner.stop()

    assert len(set(RecordingLiveStrategy.instance_ids)) == 1
    assert len({event[0] for event in RecordingLiveStrategy.events}) == 1
    assert [event[1] for event in RecordingLiveStrategy.events] == [BASE, BASE + 60, BASE + 120]
    assert [event[2] for event in RecordingLiveStrategy.events] == [100.0, 101.0, 102.0]


def test_backtrader_live_runner_executes_macd_strategy_warmup_without_init_datetime_error():
    cfg = Config(log_level="INFO", api="127.0.0.1:8000")
    log = Logger(cfg)
    warmup = [_kline(BASE + i * 86400, 100.0 + (i % 20)) for i in range(80)]
    runner = BacktraderLiveRunner(
        [MacdTripleDivergenceStrategy],
        cash=10000.0,
        commission=0.001,
        qcheck=0.001,
        strategy_kwargs=build_strategy_kwargs(
            cfg,
            log,
            0.0,
            True,
            {
                "chainer_mode": "BOTH",
                "chainer_need_confirm": True,
                "chainer_stoploss_atr_mult": 1,
                "macd_stop_enabled": True,
            },
        ),
    )

    runner.start(warmup=warmup)
    try:
        _wait_until(lambda: runner.status()["latest_delivered_open_time"] == warmup[-1].open_time)
    finally:
        runner.stop()

    assert runner.status()["last_error"] is None


def test_backtrader_live_runner_emits_warmup_and_live_operations_for_dev_validation():
    operations = []
    runner = BacktraderLiveRunner(
        OperationEveryBarStrategy,
        cash=1000.0,
        commission=0.0,
        qcheck=0.001,
        operation_handler=operations.append,
        inject_operation_sink=True,
    )

    runner.start(warmup=[_kline(BASE, 100.0), _kline(BASE + 60, 101.0)])
    try:
        _wait_until(lambda: len(operations) == 2)

        runner.put_kline(_kline(BASE + 120, 102.0))
        _wait_until(lambda: len(operations) == 3)
    finally:
        runner.stop()

    assert [op.dtime for op in operations] == [BASE, BASE + 60, BASE + 120]
    assert [op.price for op in operations] == [100.0, 101.0, 102.0]
    assert [op.feed_phase for op in operations] == ["warmup", "warmup", "live"]


def test_backtrader_live_runner_dedupes_live_operations_by_stable_identity():
    operations = []
    runner = BacktraderLiveRunner(
        DuplicateOperationStrategy,
        cash=1000.0,
        commission=0.0,
        qcheck=0.001,
        operation_handler=operations.append,
        inject_operation_sink=True,
    )

    runner.start(warmup=[])
    try:
        runner.put_kline(_kline(BASE, 100.0))
        _wait_until(lambda: len(operations) >= 1)
        time.sleep(0.05)
    finally:
        runner.stop()

    assert len(operations) == 1
    assert operations[0].signal_event_id == "same-signal"


def test_backtrader_live_runner_keeps_entry_and_exit_with_same_signal_event_id():
    operations = []
    runner = BacktraderLiveRunner(
        OperationEveryBarStrategy,
        cash=1000.0,
        commission=0.0,
        qcheck=0.001,
        operation_handler=operations.append,
        inject_operation_sink=True,
    )
    entry = Operate(OperateType.LONG, BASE, 100.0)
    entry.signal_event_id = "same-trade-signal"
    exit_op = Operate(OperateType.CLOSE, BASE + 60, 90.0)
    exit_op.signal_event_id = "same-trade-signal"

    runner._handle_operation(entry)
    runner._handle_operation(exit_op)

    assert [op.otype for op in operations] == [OperateType.LONG, OperateType.CLOSE]


def test_backtrader_live_runner_captures_completed_long_order_operations_incrementally():
    operations = []
    runner = BacktraderLiveRunner(BuyOnceStrategy, cash=1000.0, commission=0.0, qcheck=0.001, operation_handler=operations.append)

    runner.start(warmup=[])
    try:
        runner.put_kline(_kline(BASE, 100.0))
        runner.put_kline(_kline(BASE + 60, 101.0))
        _wait_until(lambda: len(operations) == 1)
    finally:
        runner.stop()

    assert operations[0].otype == OperateType.LONG
    assert operations[0].dtime == BASE + 60
    assert operations[0].price == 100.0


def test_backtrader_live_runner_captures_completed_short_order_operations_incrementally():
    operations = []
    runner = BacktraderLiveRunner(ShortOnceStrategy, cash=1000.0, commission=0.0, qcheck=0.001, operation_handler=operations.append)

    runner.start(warmup=[])
    try:
        runner.put_kline(_kline(BASE, 100.0))
        runner.put_kline(_kline(BASE + 60, 101.0))
        _wait_until(lambda: len(operations) == 1)
    finally:
        runner.stop()

    assert operations[0].otype == OperateType.SHORT
    assert operations[0].dtime == BASE + 60
    assert operations[0].price == 100.0

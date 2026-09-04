
from trader.strategy.base_strategy import BaseStrategy
from trader.utils.operate import OperateType

class SmokeTestStrategy(BaseStrategy):
    params = (
        ("name", "SmokeTest"),
        ("smoke_sequence", "long_short"),
        ("smoke_trigger_steps", "1,2,3,4"),
    )

    def __init__(self):
        super().__init__()
        self._session_step = 0
        self._trigger_steps = self._parse_trigger_steps(self.params.smoke_trigger_steps)

    def _parse_trigger_steps(self, raw):
        text = str(raw or "1,2,3,4")
        values = []
        for part in text.split(","):
            item = part.strip()
            if not item:
                continue
            try:
                step = int(item)
            except ValueError:
                continue
            if step > 0:
                values.append(step)
        if len(values) < 4:
            values = [1, 2, 3, 4]
        return values[:4]

    def next(self):
        self._session_step += 1
        long_entry, long_exit, short_entry, short_exit = self._trigger_steps
        sequence = str(self.params.smoke_sequence or "long_short").strip().lower()

        if self._session_step == long_entry and sequence in {"long_only", "long_short"}:
            self.log_info(f"SmokeTest: Triggering LONG entry at session_step={self._session_step}")
            self.buy_signal(reason="smoke_test_long")
        elif self._session_step == long_exit and sequence in {"long_only", "long_short"}:
            self.log_info(f"SmokeTest: Triggering SELL exit at session_step={self._session_step}")
            self.sell_signal(reason="smoke_test_long_exit")
        elif self._session_step == short_entry and sequence in {"short_only", "long_short"}:
            self.log_info(f"SmokeTest: Triggering SHORT entry at session_step={self._session_step}")
            self.short_signal(reason="smoke_test_short")
        elif self._session_step == short_exit and sequence in {"short_only", "long_short"}:
            self.log_info(f"SmokeTest: Triggering CLOSE exit at session_step={self._session_step}")
            self.close_signal(reason="smoke_test_short_exit")

    def buy_signal(self, reason):
        if self.params.live_operation_sink:
            from trader.utils.operate import Operate
            op = Operate(OperateType.BUY, self.datas[0].datetime.datetime(0).timestamp(), self.datas[0].close[0])
            op.reason = reason
            # Set stop loss and take profit to trigger advanced order logic
            op.stop_loss = self.datas[0].close[0] * 0.95
            op.take_profit = self.datas[0].close[0] * 1.05
            self.params.live_operation_sink(op)

    def sell_signal(self, reason):
        if self.params.live_operation_sink:
            from trader.utils.operate import Operate
            op = Operate(OperateType.SELL, self.datas[0].datetime.datetime(0).timestamp(), self.datas[0].close[0])
            op.reason = reason
            self.params.live_operation_sink(op)

    def short_signal(self, reason):
        if self.params.live_operation_sink:
            from trader.utils.operate import Operate
            op = Operate(OperateType.SHORT, self.datas[0].datetime.datetime(0).timestamp(), self.datas[0].close[0])
            op.reason = reason
            # Set stop loss and take profit for short
            op.stop_loss = self.datas[0].close[0] * 1.05
            op.take_profit = self.datas[0].close[0] * 0.95
            self.params.live_operation_sink(op)

    def close_signal(self, reason):
        if self.params.live_operation_sink:
            from trader.utils.operate import Operate
            op = Operate(OperateType.CLOSE, self.datas[0].datetime.datetime(0).timestamp(), self.datas[0].close[0])
            op.reason = reason
            self.params.live_operation_sink(op)

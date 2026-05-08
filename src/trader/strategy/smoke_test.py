
import backtrader as bt
from trader.strategy.base_strategy import BaseStrategy
from trader.utils.operate import OperateType

class SmokeTestStrategy(BaseStrategy):
    params = (
        ("name", "SmokeTest"),
    )

    def next(self):
        # We use a simple counter based on bars processed in this session
        bar_count = len(self)
        
        # bar_count starts at 1 in Backtrader
        if bar_count == 5:
            self.log.info("SmokeTest: Triggering LONG entry")
            self.buy_signal(reason="smoke_test_long")
        elif bar_count == 10:
            self.log.info("SmokeTest: Triggering SELL exit")
            self.sell_signal(reason="smoke_test_long_exit")
        elif bar_count == 15:
            self.log.info("SmokeTest: Triggering SHORT entry")
            self.short_signal(reason="smoke_test_short")
        elif bar_count == 20:
            self.log.info("SmokeTest: Triggering CLOSE exit")
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

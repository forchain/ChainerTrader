from __future__ import absolute_import, division, print_function, unicode_literals

import backtrader as bt

from trader.indicators.qqe_mod import QQEMod
from trader.indicators.super_trend import SuperTrend
from trader.indicators.trend_a import TrendA
from trader.strategy.base_strategy import BaseStrategy
from trader.utils.ma import MAType
from trader.utils.operate import OperateType


class SuperTrendQQEMODStrategy(BaseStrategy):
    params = (
        # QQE parameters
        ("rsi_length_secondary", 10),  # QQE secondary period
        # Heikin Ashi MA parameters
        ("ma_type", MAType.EMA),
        ("ma_period", 77),
        ("ma_period_smoothing", 21),
        # Super Trend  parameters
        ("periods", 10),
        ("multiplier", 3.3),
    )

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()}, {txt}')

    def __init__(self):
        super().__init__()

        self.super_trend = SuperTrend(
            periods=self.params.periods,
            multiplier=self.params.multiplier,
        )

        self.qqe_mod = QQEMod(
            rsi_length_secondary=self.params.rsi_length_secondary,
        )

        self.trend_a = TrendA(
            ma_type=self.params.ma_type,
            ma_period=self.params.ma_period,
            ma_period_smoothing=self.params.ma_period_smoothing,
        )

        self.stop_loss_point = 0
        self.take_profit_point = 0

        # 记录订单引用，用于避免重复下单 (订单管理核心变量)
        self.order = None

        # 记录买入价格 (用于计算止损/止盈价格)
        self.buy_price = None

    def next(self):
        """Main strategy logic"""
        super().next()

        if self.order:
            return

        # Buy
        if self.super_trend.trend[0] == 1 and self.qqe_mod.qqe_up_signal[0] and self.trend_a.trend[0] == 1:
            self.order = self.buy()
            self.stop_loss_point = self.super_trend.dn[0]
            stop_loss_range = self.data.close - self.stop_loss_point
            self.take_profit_point = self.stop_loss_point + 2 * stop_loss_range

        # Sell
        if self.super_trend.trend[0] == -1 and self.qqe_mod.qqe_down_signal[0] and self.trend_a.trend[0] == -1:
            self.order = self.sell()
            self.stop_loss_point = self.super_trend.up[0]
            stop_loss_range = self.stop_loss_point - self.data.close
            self.take_profit_point = self.stop_loss_point - 2 * stop_loss_range

        # only one order at a time
        if self.data.low < self.stop_loss_point:
            self.order = self.close()

        # 1. 订单管理核心：如果有挂单，等待成交，避免重复下单
        if self.order:
            return

        # 2. 持仓管理：没有持仓时才考虑开仓
        if self.position:
            return

        if self.super_trend.trend[0] == 1 and self.qqe_mod.qqe_up_signal[0] and self.trend_a.trend[0] == 1:
            current_price = self.data.close[0]

            # --- 核心：使用 buy_bracket 设置 OCO 订单 ---

            size = 100
            stop_price = self.super_trend.dn[0]
            stop_loss_range = current_price - self.stop_loss_point
            limit_price = stop_price + 2 * stop_loss_range

            self.log(f'📈 发现金叉，发送括号订单: 止损@{stop_price:.2f}, 止盈@{limit_price:.2f}')

            # buy_bracket 一次性发出 (主单买入, 止损单, 止盈限价单)
            self.order = self.buy_bracket(
                size=size,
                stopprice=stop_price,
                limitprice=limit_price
            )

        if self.super_trend.trend[0] == -1 and self.qqe_mod.qqe_down_signal[0] and self.trend_a.trend[0] == -1:
            current_price = self.data.close[0]

            # --- 核心：使用 buy_bracket 设置 OCO 订单 ---

            # 假设我们想要：止损 5%，止盈 10%
            size = 100
            stop_price = self.super_trend.up[0]
            limit_price = current_price * 1.10

            self.log(f'📈 发现金叉，发送括号订单: 止损@{stop_price:.2f}, 止盈@{limit_price:.2f}')

            # buy_bracket 一次性发出 (主单买入, 止损单, 止盈限价单)
            self.order = self.buy_bracket(
                size=size,
                stopprice=stop_price,
                limitprice=limit_price
            )

    def notify_order(self, order):
        # 订单还在排队中，不需要处理
        if order.status in [order.Submitted, order.Accepted]:
            return

        # 订单已成交 (Completed)
        if order.status == order.Completed:
            if order.isbuy():
                # 记录买入价 (用于计算后续百分比止损/止盈)
                self.buy_price = order.executed.price
                self.log(f'✅ 买入成交：价格 {self.buy_price:.2f}, 费用 {order.executed.comm:.2f}')

            elif order.issell():
                self.log(f'❌ 卖出平仓：价格 {order.executed.price:.2f}, 费用 {order.executed.comm:.2f}')

            # 重置订单引用，允许策略在下一根K线开始新交易
            self.order = None

        # 订单失败/取消/拒单
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            # 资金不足 (Margin) 是最常见的错误
            self.log('⚠️ 订单失败/取消/资金不足。重置订单标志。')
            self.order = None  # 重要的清空标志位操作！

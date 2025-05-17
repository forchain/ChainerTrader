from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt

from trader.strategy.base_strategy import BaseStrategy

class GridStrategy(BaseStrategy):
    params = (
        ("grid_size", 20),
        ("grid_levels", 10),
        ("once_size", 20),
    )

    def __init__(self):
        super().__init__()

        self.grid_centers = []
        self.buy_levels = []
        self.sell_levels = []
        self.order_dict = {}

        # init grid
        self.latest_price = self.data.close[-len(self.data)]
        grid_size = self.params.grid_size
        levels = self.params.grid_levels

        for i in range(0, levels):
            self.buy_levels.append(self.latest_price - (i+1) * grid_size)
            self.sell_levels.append(self.latest_price + (i+1) * grid_size)

    def next(self):
        super().next()

        current_price = self.data.close[0]
        cash = self.broker.get_cash()
        positions = self.getposition(self.data).size

        if current_price - self.latest_price > self.params.grid_size*self.params.grid_levels:
            self.latest_price=current_price
            self.buy_levels.clear()
            self.sell_levels.clear()
            for i in range(0, self.params.grid_levels):
                self.buy_levels.append(self.latest_price - (i + 1) * self.params.grid_size)
                self.sell_levels.append(self.latest_price + (i + 1) * self.params.grid_size)

        if self.latest_price - current_price > self.params.grid_size*self.params.grid_levels:
            self.latest_price = current_price
            self.buy_levels.clear()
            self.sell_levels.clear()
            for i in range(0, self.params.grid_levels):
                self.buy_levels.append(self.latest_price - (i + 1) * self.params.grid_size)
                self.sell_levels.append(self.latest_price + (i + 1) * self.params.grid_size)

        for buy_level in self.buy_levels:
            if current_price <= buy_level and buy_level not in self.order_dict:
                if cash >= self.params.once_size * current_price:
                    order = self.buy(size=self.params.once_size, price=current_price)
                    self.order_dict[buy_level] = order
                    self.log_debug(f"Will buy placed at {buy_level}, Cash: {cash}, Position: {positions}")
                    self.update_stop_loss_point()

        for sell_level in self.sell_levels:
            if current_price >= sell_level and sell_level not in self.order_dict:
                if self.need_stop_loss():
                    order = self.sell(size=self.params.once_size, price=current_price)
                    self.order_dict[sell_level] = order
                    self.log_debug(f"Will sell placed at {sell_level}, Cash: {cash}, Position: {positions}")
                    return
                if positions >= self.params.once_size:
                    order = self.sell(size=self.params.once_size, price=current_price)
                    self.order_dict[sell_level] = order
                    self.log_debug(f"Will sell placed at {sell_level}, Cash: {cash}, Position: {positions}")


    def notify_order(self, order):
        super().notify_order(order)

        if order.status in [order.Completed]:
            for key in list(self.order_dict.keys()):
                if self.order_dict[key] == order:
                    del self.order_dict[key]
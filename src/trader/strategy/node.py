from __future__ import absolute_import, division, print_function, unicode_literals

from datetime import timedelta

import backtrader as bt
from backtrader import num2date
from prettytable import PrettyTable

from trader.common.config import Config
from trader.common.log_tag import LogTag
from trader.common.logger import Logger
from trader.strategy.trader_result import TraderResult
from trader.utils.operation_state import OptStatAnalyzer
from trader.utils.symbol_interval import SymbolInterval, get_time_duration


class Node:
    def __init__(
            self,
            name,
            strategy,
            si: SymbolInterval,
            cfg: Config = None,
            log: Logger = None,
            data=None,
            position: float = 0,
            trader: bool = False,
            free: float = 0,
    ):
        self.log = log
        self.name = name
        self.cfg = cfg
        self.si = si
        self.free = free

        log.info("New node", LogTag.STRATEGY)

        data_ha = None

        cerebro = bt.Cerebro()
        for st in strategy:
            cerebro.addstrategy(
                st,
                stoploss=cfg.stoploss,
                atr=cfg.atr,
                mode=cfg.mode,
                period=cfg.period,
                log=log,
                name=st.__name__,
                position=position,
                trader=trader,
            )

        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.02)
        cerebro.addanalyzer(bt.analyzers.VWR, _name="volatility")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade_analyzer")

        cerebro.addanalyzer(OptStatAnalyzer, _name="optstat", si=self.si)

        self.cerebro = cerebro

        cerebro.adddata(data)
        if data_ha is not None:
            cerebro.adddata(data_ha)
            self.log.info(f"Add HeikinAshi data for {self.name}", LogTag.STRATEGY)

        cerebro.broker.setcash(free)

        cerebro.addsizer(bt.sizers.FixedSize, stake=10)

        cerebro.broker.setcommission(commission=cfg.commission, commtype=bt.CommInfoBase.COMM_PERC, stocklike=True)

    def get_win_rate(self, strategy: bt.Strategy):
        trade_analysis = strategy.analyzers.trade_analyzer.get_analysis()
        total_trades = trade_analysis.total.closed if "closed" in trade_analysis.total else 0
        win_trades = trade_analysis.won.total if "won" in trade_analysis and "total" in trade_analysis.won else 0

        if total_trades > 0:
            win_rate = (win_trades / total_trades) * 100
            return win_rate
        else:
            return 0

    def get_profit_loss(self, strategy: bt.Strategy):
        trade_analysis = strategy.analyzers.trade_analyzer.get_analysis()
        avg_win = trade_analysis.won.pnl.average if "won" in trade_analysis and "pnl" in trade_analysis.won else None
        avg_loss = trade_analysis.lost.pnl.average if "lost" in trade_analysis and "pnl" in trade_analysis.lost else None

        if avg_win is not None and avg_loss is not None and avg_loss != 0:
            profit_loss_ratio = abs(avg_win / avg_loss)
            return profit_loss_ratio, avg_win, avg_loss
        else:
            if avg_win is None:
                avg_win = 0
            if avg_loss is None:
                avg_loss = 0

            return 0, avg_win, avg_loss

    def get_hold_rate(self):
        data_len = len(self.cerebro.datas[0])
        start_price = self.cerebro.datas[0].open[1 - data_len]
        end_price = self.cerebro.datas[0].close[0]
        hold_rate = (end_price - start_price) / start_price * 100
        return hold_rate

    def start(self):
        self.log.info("start node", LogTag.STRATEGY)

        rets = self.cerebro.run()
        ret = rets[0]

        finalFund = self.cerebro.broker.getvalue()
        totalReturnRate = (finalFund - self.free) / self.cfg.cash * 100

        hold_rate = self.get_hold_rate()

        drawdown = ret.analyzers.drawdown.get_analysis()
        maxDrawdown = drawdown.max.drawdown

        maxDrawdownLen = drawdown.max.len
        maxDrawdownLen = get_time_duration(self.si.interval) * maxDrawdownLen
        maxDrawdownDuration = timedelta(seconds=maxDrawdownLen)

        sharpeRatio = ret.analyzers.sharpe.get_analysis()
        volatility = ret.analyzers.volatility.get_analysis()["vwr"]
        winRate = self.get_win_rate(ret)

        plr, avgProfit, avgLoss = self.get_profit_loss(ret)

        optstat = ret.analyzers.optstat.get_analysis()

        if self.cfg.plot:
            self.cerebro.plot()

        data_len = len(self.cerebro.datas[0])
        end_time = num2date(self.cerebro.datas[0].datetime[0])
        start_time = num2date(self.cerebro.datas[0].datetime[1 - data_len])

        # statistics
        table = PrettyTable()
        table.field_names = ["Name", "Value"]
        table.add_row(["策略", f"{self.name}"])

        table.add_row(["交易对", self.si.symbol()])
        table.add_row(["总收益率", format(totalReturnRate, ".2f") + "%"])
        table.add_row(["持有增长率:", (f"{hold_rate:.2f}%")])
        if sharpeRatio["sharperatio"]:
            table.add_row(["夏普比率", (f"{sharpeRatio['sharperatio']:.2f}")])
        table.add_row(["最大回撤:", (f"{maxDrawdown:.2f}%")])
        table.add_row(["回撤时长:", (f"{maxDrawdownDuration}")])
        table.add_row(["波动率:", (f"{volatility:.2f}%")])
        table.add_row(["胜率:", (f"{winRate:.2f}%")])
        table.add_row(["平均盈亏比:", (f"{plr:.2f}")])
        table.add_row(["平均盈利:", (f"{avgProfit:.2f}")])
        table.add_row(["平均亏损:", (f"{avgLoss:.2f}")])

        table.add_row(["开始时间", (f"{start_time}")])
        table.add_row(["结束时间", (f"{end_time}")])
        table.add_row(["数据量", data_len])
        table.add_row(["手续费率", self.cfg.commission])
        table.add_row(["ATR", self.cfg.atr])
        table.add_row(["初始资金", format(self.cfg.cash, ".2f")])
        table.add_row(["冻结资金", format(self.cfg.cash - self.free, ".2f")])
        table.add_row(["可用资金", format(self.free, ".2f")])
        table.add_row(["最终资金", format(finalFund, ".2f")])
        table.add_row(["操作买单数", optstat["buys"]])
        table.add_row(["操作卖单数", optstat["sells"]])

        self.log.info(f"\n{table}", LogTag.STRATEGY)

        return TraderResult(
            totalReturnRate,
            maxDrawdown,
            maxDrawdownDuration,
            volatility,
            winRate,
            plr,
            avgProfit,
            avgLoss,
            optstat["buys"],
            optstat["sells"],
            optstat["opts"],
            hold_rate,
            data_len,
        )

import json
import os
from collections import defaultdict
from datetime import datetime

import backtrader as bt

class BacktestReportAnalyzer(bt.Analyzer):
    """
    Generates a structured JSON report after backtest completion.

    Collects per-trade records via notify_trade() and aggregates summary metrics
    from other registered analyzers (TradeAnalyzer, SharpeRatio, DrawDown, SQN)
    in stop(). Writes the report to reports/<strategy>_<symbol>_<interval>_<timestamp>.json.
    """

    params = (
        ("strategy_name", "unknown"),
        ("symbol", "unknown"),
        ("interval", "unknown"),
    )

    def __init__(self):
        self._trades = []
        self._trade_entries = {}
        self._total_signals = 0
        self._entered_signals = 0
        self._confirm_failed = 0
        self.report = None

    def _current_dt_iso(self):
        return self.strategy.datetime.datetime().isoformat()

    def notify_trade(self, trade):
        if not trade.isclosed:
            if trade.justopened:
                ctx = getattr(self.strategy, "_trades_by_id", {}).get(trade.ref)
                entry_px = trade.price
                direction = "L" if trade.size > 0 else "S"
                if ctx is not None:
                    if getattr(ctx, "entry_price", None) is not None:
                        entry_px = float(ctx.entry_price)
                    direction = "L" if getattr(ctx, "direction", "LONG") == "LONG" else "S"
                self._trade_entries[trade.ref] = {
                    "entry_time": self._current_dt_iso(),
                    "entry_px": entry_px,
                    "size": trade.size,
                    "dir": direction,
                }
            return

        entry_info = self._trade_entries.pop(trade.ref, {})
        entry_time = entry_info.get("entry_time", "")
        entry_px = entry_info.get("entry_px", 0)
        entry_size = entry_info.get("size", 0)
        ctx = getattr(self.strategy, "_trades_by_id", {}).get(trade.ref)

        exit_time = self._current_dt_iso()
        exit_px = self.strategy.data.close[0]
        if ctx is not None and getattr(ctx, "exit_price", None) is not None:
            exit_px = float(ctx.exit_price)

        direction = entry_info.get("dir", "L" if entry_size > 0 else "S")

        if entry_px > 0:
            if direction == "L":
                pnl_pct = (exit_px - entry_px) / entry_px * 100
            else:
                pnl_pct = (entry_px - exit_px) / entry_px * 100
        else:
            pnl_pct = 0.0

        bars_held = trade.barclose - trade.baropen

        self._trades.append({
            "id": trade.ref,
            "dir": direction,
            "entry": entry_time,
            "entry_px": round(entry_px, 2),
            "exit": exit_time,
            "exit_px": round(float(exit_px), 2),
            "pnl_pct": round(pnl_pct, 2),
            "pnl": round(trade.pnlcomm, 2),
            "bars_held": bars_held,
        })

    def stop(self):
        report = self._build_report()
        self.report = report
        self._write_report(report)

    def _build_report(self):
        # --- Summary from other analyzers ---
        ta = self._get_trade_analyzer()
        sharpe = self._get_sharpe()
        sqn_val = self._get_sqn()
        dd = self._get_drawdown()

        total_closed = ta.get("total_closed", 0)
        won_total = ta.get("won_total", 0)
        won_pnl = ta.get("won_pnl_total", 0)
        lost_pnl = ta.get("lost_pnl_total", 0)

        win_rate = (won_total / total_closed * 100) if total_closed > 0 else 0
        profit_factor = (won_pnl / abs(lost_pnl)) if lost_pnl != 0 else None
        avg_rr = 0
        if ta.get("lost_pnl_avg") and ta["lost_pnl_avg"] != 0:
            avg_rr = abs(ta.get("won_pnl_avg", 0) / ta["lost_pnl_avg"])

        # Total return
        broker = self.strategy.broker
        final_value = broker.getvalue()
        initial_cash = broker.startingcash if hasattr(broker, "startingcash") else 100000
        total_return_pct = (final_value - initial_cash) / initial_cash * 100

        # Hold return
        data = self.strategy.data
        data_len = len(data)
        if data_len > 1:
            start_price = data.open[1 - data_len]
            end_price = data.close[0]
            hold_return_pct = (end_price - start_price) / start_price * 100
        else:
            hold_return_pct = 0

        # Monthly PnL
        monthly_pnl = self._calc_monthly_pnl()
        signals = self._collect_signals()

        summary = {
            "total_return_pct": round(total_return_pct, 2),
            "hold_return_pct": round(hold_return_pct, 2),
            "sharpe": round(sharpe, 2) if sharpe is not None else None,
            "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
            "sqn": round(sqn_val, 2) if sqn_val is not None else None,
            "max_dd_pct": round(dd.get("max_dd", 0), 2),
            "max_dd_days": dd.get("max_dd_days", 0),
            "win_rate_pct": round(win_rate, 2),
            "avg_rr": round(avg_rr, 2),
            "total_trades": total_closed,
            "total_signals": len(signals),
        }

        return {
            "strategy": self.p.strategy_name,
            "symbol": self.p.symbol,
            "interval": self.p.interval,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "summary": summary,
            "monthly_pnl": monthly_pnl,
            "trades": self._trades,
            "signals": signals,
        }

    def _get_trade_analyzer(self):
        result = {}
        try:
            ta = self.strategy.analyzers.trade_analyzer.get_analysis()
            result["total_closed"] = ta.total.closed if "closed" in ta.total else 0
            result["won_total"] = ta.won.total if "won" in ta and "total" in ta.won else 0
            result["lost_total"] = ta.lost.total if "lost" in ta and "total" in ta.lost else 0
            result["won_pnl_total"] = ta.won.pnl.total if "won" in ta and "pnl" in ta.won else 0
            result["lost_pnl_total"] = ta.lost.pnl.total if "lost" in ta and "pnl" in ta.lost else 0
            result["won_pnl_avg"] = ta.won.pnl.average if "won" in ta and "pnl" in ta.won else 0
            result["lost_pnl_avg"] = ta.lost.pnl.average if "lost" in ta and "pnl" in ta.lost else 0
        except (AttributeError, KeyError):
            pass
        return result

    def _get_sharpe(self):
        try:
            return self.strategy.analyzers.sharpe.get_analysis().get("sharperatio")
        except (AttributeError, KeyError):
            return None

    def _get_sqn(self):
        try:
            return self.strategy.analyzers.sqn.get_analysis().get("sqn")
        except (AttributeError, KeyError):
            return None

    def _get_drawdown(self):
        result = {"max_dd": 0, "max_dd_days": 0}
        try:
            dd = self.strategy.analyzers.maxdd_ex.get_analysis()
            result["max_dd"] = dd.get("max_drawdown", 0)
            start = dd.get("start")
            end = dd.get("end")
            if start and end:
                result["max_dd_days"] = (end - start).days
        except (AttributeError, KeyError):
            pass
        return result

    def _calc_monthly_pnl(self):
        monthly = defaultdict(float)
        for t in self._trades:
            if t.get("exit"):
                try:
                    exit_dt = datetime.fromisoformat(t["exit"])
                    key = exit_dt.strftime("%Y-%m")
                    monthly[key] += t.get("pnl", 0)
                except (ValueError, TypeError):
                    pass
        return {k: round(v, 2) for k, v in sorted(monthly.items())}

    def _collect_signals(self):
        events = getattr(self.strategy, "_signal_events", [])
        return list(events)

    def _write_report(self, report):
        reports_dir = os.path.join(os.getcwd(), "reports")
        os.makedirs(reports_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.p.strategy_name}_{self.p.symbol}_{self.p.interval}_{timestamp}.json"
        filepath = os.path.join(reports_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)

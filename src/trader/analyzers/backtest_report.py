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
        ("report_context", None),
    )

    def __init__(self):
        self._trades = []
        self._trade_entries = {}
        self._total_signals = 0
        self._entered_signals = 0
        self._confirm_failed = 0
        self.report = None
        self.report_path = None

    def _current_dt_iso(self):
        return self.strategy.datetime.datetime().isoformat()

    def notify_trade(self, trade):
        trade_key = getattr(trade, "tradeid", None)
        if trade_key is None:
            trade_key = trade.ref
        if not trade.isclosed:
            if trade.justopened:
                ctx = getattr(self.strategy, "_trades_by_id", {}).get(trade_key)
                entry_px = trade.price
                direction = "L" if trade.size > 0 else "S"
                entry_signal_time = None
                if ctx is not None:
                    if getattr(ctx, "entry_price", None) is not None:
                        entry_px = float(ctx.entry_price)
                    direction = "L" if getattr(ctx, "direction", "LONG") == "LONG" else "S"
                    signal_metadata = getattr(ctx, "signal_metadata", None) or {}
                    entry_signal_time = signal_metadata.get("signal_time")
                self._trade_entries[trade_key] = {
                    "entry_signal_time": entry_signal_time,
                    "entry_time": self._current_dt_iso(),
                    "entry_px": entry_px,
                    "size": trade.size,
                    "dir": direction,
                }
            return

        entry_info = self._trade_entries.pop(trade_key, {})
        entry_signal_time = entry_info.get("entry_signal_time")
        entry_time = entry_info.get("entry_time", "")
        entry_px = entry_info.get("entry_px", 0)
        entry_size = entry_info.get("size", 0)
        ctx = getattr(self.strategy, "_trades_by_id", {}).get(trade_key)

        exit_time = self._current_dt_iso()
        exit_signal_time = None
        exit_px = self.strategy.data.close[0]
        if ctx is not None and getattr(ctx, "exit_price", None) is not None:
            exit_px = float(ctx.exit_price)
            exit_signal_time = self._exit_signal_time(ctx, fallback=exit_time)

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
            "id": trade_key,
            "broker_ref": trade.ref,
            "dir": direction,
            "qty": round(abs(float(entry_size)), 8),
            "entry_signal_time": entry_signal_time,
            "entry": entry_time,
            "entry_px": float(entry_px),
            "exit_signal_time": exit_signal_time,
            "exit": exit_time,
            "exit_px": float(exit_px),
            "pnl_pct": round(pnl_pct, 2),
            "pnl": round(trade.pnlcomm, 2),
            "bars_held": bars_held,
            "exit_reason_code": getattr(ctx, "exit_reason_code", None) if ctx is not None else None,
            "exit_reason_label": getattr(ctx, "exit_reason_label", None) if ctx is not None else None,
            "exit_reason_detail": getattr(ctx, "exit_reason_detail", None) if ctx is not None else None,
            "replacement_trade_id": getattr(ctx, "replacement_trade_id", None) if ctx is not None else None,
            "stop_multiple_r": getattr(ctx, "stop_multiple_r", None) if ctx is not None else None,
            "risk_reward_ratio": getattr(ctx, "exit_risk_reward_ratio", None) if ctx is not None else None,
            "framework_initial_stop_price": getattr(ctx, "initial_stop_price", None) if ctx is not None else None,
            "framework_final_stop_price": getattr(ctx, "stop_price", None) if ctx is not None else None,
            "framework_tp_price": getattr(ctx, "tp_price", None) if ctx is not None else None,
            "strategy_suggested_stop_price": (
                getattr(ctx, "signal_metadata", {}).get("suggested_stop_price") if ctx is not None and getattr(ctx, "signal_metadata", None) else None
            ),
        })

    def stop(self):
        self._append_missing_closed_trade_records_from_contexts()
        self._enrich_trade_records_from_contexts()
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
        reported_closed = len(self._trades)
        if reported_closed > total_closed:
            total_closed = reported_closed
            won_total = sum(1 for trade in self._trades if float(trade.get("pnl", 0.0) or 0.0) > 0.0)
            won_pnl = sum(
                float(trade.get("pnl", 0.0) or 0.0)
                for trade in self._trades
                if float(trade.get("pnl", 0.0) or 0.0) > 0.0
            )
            lost_pnl = sum(
                float(trade.get("pnl", 0.0) or 0.0)
                for trade in self._trades
                if float(trade.get("pnl", 0.0) or 0.0) < 0.0
            )

        win_rate = self._trade_win_rate_pct(total_closed, won_total)
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
        open_trades = self._collect_open_trade_records_from_contexts()

        summary = {
            "total_return_pct": round(total_return_pct, 2),
            "hold_return_pct": round(hold_return_pct, 2),
            "sharpe": round(sharpe, 2) if sharpe is not None else None,
            "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
            "sqn": round(sqn_val, 2) if sqn_val is not None else None,
            "max_dd_pct": round(dd.get("max_dd", 0), 2),
            "max_dd_days": dd.get("max_dd_days", 0),
            "active_max_dd_pct": round(dd.get("active_max_dd", dd.get("max_dd", 0)), 2),
            "active_max_dd_days": dd.get("active_max_dd_days", dd.get("max_dd_days", 0)),
            "win_rate_pct": round(win_rate, 2),
            "avg_rr": round(avg_rr, 2),
            "total_trades": total_closed,
            "open_trades": len(open_trades),
            "total_signals": len(signals),
        }

        return {
            "strategy": self.p.strategy_name,
            "symbol": self.p.symbol,
            "interval": self.p.interval,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "optimization_run_id": self._context_value("optimization_run_id"),
            "report_version": self._report_version(),
            "param_id": self._context_value("param_id"),
            "params": self._context_value("params"),
            "dataset_ref": self._context_value("dataset_ref"),
            "summary": summary,
            "monthly_pnl": monthly_pnl,
            "trades": self._trades,
            "open_trades": open_trades,
            "signals": signals,
        }

    def _trade_win_rate_pct(self, total_closed, won_total):
        if self._trades:
            decisive_trades = [
                trade
                for trade in self._trades
                if float(trade.get("pnl_pct", trade.get("pnl", 0.0)) or 0.0) != 0.0
            ]
            if decisive_trades:
                won = sum(
                    1
                    for trade in decisive_trades
                    if float(trade.get("pnl_pct", trade.get("pnl", 0.0)) or 0.0) > 0.0
                )
                return won / len(decisive_trades) * 100
            return 0.0
        return (won_total / total_closed * 100) if total_closed > 0 else 0

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
        result = {"max_dd": 0, "max_dd_days": 0, "active_max_dd": 0, "active_max_dd_days": 0}
        try:
            dd = self.strategy.analyzers.maxdd_ex.get_analysis()
            result["max_dd"] = dd.get("max_drawdown", 0)
            start = dd.get("start")
            end = dd.get("end")
            if start and end:
                result["max_dd_days"] = (end - start).days
            result["active_max_dd"] = dd.get("active_max_drawdown", result["max_dd"])
            active_start = dd.get("active_start")
            active_end = dd.get("active_end")
            if active_start and active_end:
                result["active_max_dd_days"] = (active_end - active_start).days
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

    def _collect_open_trade_records_from_contexts(self):
        contexts = getattr(self.strategy, "_trades_by_id", {})
        open_statuses = {"active", "opening", "pending_entry_confirm", "pending_exit_confirm", "closing"}
        records = []
        for trade_id, ctx in sorted(contexts.items()):
            status_value = getattr(getattr(ctx, "status", None), "value", getattr(ctx, "status", None))
            if status_value not in open_statuses:
                continue
            entry_price = getattr(ctx, "entry_price", None)
            if entry_price is None:
                continue

            direction = getattr(ctx, "direction", "LONG")
            trade_entries = getattr(self, "_trade_entries", {})
            entry_info = (
                trade_entries.get(trade_id)
                or trade_entries.get(getattr(ctx, "trade_id", trade_id))
                or {}
            )
            entry_time = entry_info.get("entry_time")
            entry_signal_time = entry_info.get("entry_signal_time")
            entry_size = entry_info.get("size")
            entry_direction = entry_info.get("dir")
            signal_metadata = getattr(ctx, "signal_metadata", None) or {}
            current_px = self._current_data_close()
            unrealized_pnl_pct = self._unrealized_pnl_pct(direction, float(entry_price), current_px)
            if entry_size is not None:
                qty = abs(float(entry_size))
            else:
                qty = abs(float(getattr(getattr(self.strategy, "position", None), "size", 0.0) or 0.0))

            records.append({
                "id": int(getattr(ctx, "trade_id", trade_id)),
                "dir": entry_direction or ("L" if direction == "LONG" else "S"),
                "status": "open",
                "qty": round(qty, 8),
                "entry_signal_time": entry_signal_time or signal_metadata.get("signal_time"),
                "entry": entry_time,
                "entry_px": float(entry_price),
                "current_px": float(current_px) if current_px is not None else None,
                "unrealized_pnl_pct": round(unrealized_pnl_pct, 2) if unrealized_pnl_pct is not None else None,
                "framework_initial_stop_price": getattr(ctx, "initial_stop_price", None),
                "framework_final_stop_price": getattr(ctx, "stop_price", None),
                "framework_tp_price": getattr(ctx, "tp_price", None),
                "strategy_suggested_stop_price": signal_metadata.get("suggested_stop_price"),
                "exit_reason_code": "open_position",
                "exit_reason_label": "未平仓",
                "exit_reason_detail": "回测结束时仍有未平仓仓位",
            })
        return records

    def _current_data_close(self):
        try:
            return float(self.strategy.data.close[0])
        except (AttributeError, IndexError, TypeError, ValueError):
            return None

    def _unrealized_pnl_pct(self, direction, entry_price, current_px):
        if current_px is None or entry_price <= 0:
            return None
        if direction == "SHORT":
            return (entry_price - current_px) / entry_price * 100
        return (current_px - entry_price) / entry_price * 100

    def _append_missing_closed_trade_records_from_contexts(self):
        contexts = getattr(self.strategy, "_trades_by_id", {})
        existing_ids = {trade.get("id") for trade in self._trades}
        for trade_id, ctx in sorted(contexts.items()):
            record_id = int(getattr(ctx, "trade_id", trade_id))
            if record_id in existing_ids:
                continue
            status_value = getattr(getattr(ctx, "status", None), "value", getattr(ctx, "status", None))
            if status_value != "closed":
                continue
            entry_price = getattr(ctx, "entry_price", None)
            exit_price = getattr(ctx, "exit_price", None)
            if entry_price is None or exit_price is None:
                continue

            trade_entries = getattr(self, "_trade_entries", {})
            entry_info = trade_entries.pop(record_id, None) or trade_entries.pop(trade_id, None) or {}
            direction = getattr(ctx, "direction", "LONG")
            dir_label = entry_info.get("dir") or ("L" if direction == "LONG" else "S")
            qty = self._closed_context_qty(ctx, entry_info, float(exit_price))
            pnl_pct = self._unrealized_pnl_pct(direction, float(entry_price), float(exit_price)) or 0.0
            pnl = self._closed_context_pnl(ctx, float(entry_price), float(exit_price), qty)
            signal_metadata = getattr(ctx, "signal_metadata", None) or {}
            entry_dt = entry_info.get("entry_time") or self._iso_dt(getattr(ctx, "entry_dt", None))
            exit_dt = self._iso_dt(getattr(ctx, "exit_dt", None)) or self._exit_signal_time(ctx) or self._current_dt_iso()

            self._trades.append({
                "id": record_id,
                "broker_ref": None,
                "dir": dir_label,
                "qty": round(abs(float(qty)), 8),
                "entry_signal_time": entry_info.get("entry_signal_time") or signal_metadata.get("signal_time"),
                "entry": entry_dt,
                "entry_px": float(entry_price),
                "exit_signal_time": self._exit_signal_time(ctx, fallback=exit_dt),
                "exit": exit_dt,
                "exit_px": float(exit_price),
                "pnl_pct": round(pnl_pct, 2),
                "pnl": round(pnl, 2),
                "bars_held": None,
                "exit_reason_code": getattr(ctx, "exit_reason_code", None),
                "exit_reason_label": getattr(ctx, "exit_reason_label", None),
                "exit_reason_detail": getattr(ctx, "exit_reason_detail", None),
                "replacement_trade_id": getattr(ctx, "replacement_trade_id", None),
                "stop_multiple_r": getattr(ctx, "stop_multiple_r", None),
                "risk_reward_ratio": getattr(ctx, "exit_risk_reward_ratio", None),
                "framework_initial_stop_price": getattr(ctx, "initial_stop_price", None),
                "framework_final_stop_price": getattr(ctx, "stop_price", None),
                "framework_tp_price": getattr(ctx, "tp_price", None),
                "strategy_suggested_stop_price": signal_metadata.get("suggested_stop_price"),
                "recovered_from_context": True,
            })
            existing_ids.add(record_id)

    def _closed_context_qty(self, ctx, entry_info, exit_price):
        entry_size = entry_info.get("size")
        if entry_size is not None:
            return abs(float(entry_size))
        exit_value = getattr(ctx, "exit_value", None)
        if exit_value is not None and exit_price > 0:
            return abs(float(exit_value) / exit_price)
        return 0.0

    def _closed_context_pnl(self, ctx, entry_price, exit_price, qty):
        direction = getattr(ctx, "direction", "LONG")
        price_diff = exit_price - entry_price if direction == "LONG" else entry_price - exit_price
        gross_pnl = price_diff * qty
        commission_rate = self._commission_rate()
        commission = (entry_price * qty + exit_price * qty) * commission_rate
        return gross_pnl - commission

    def _commission_rate(self):
        try:
            return float(self.strategy.broker.getcommissioninfo(self.strategy.data).p.commission)
        except (AttributeError, TypeError, ValueError):
            return 0.0

    def _iso_dt(self, value):
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    def _enrich_trade_records_from_contexts(self):
        contexts = getattr(self.strategy, "_trades_by_id", {})
        for trade_record in self._trades:
            ctx = contexts.get(trade_record.get("id"))
            if ctx is None:
                ctx = contexts.get(trade_record.get("trade_id"))
            if ctx is not None:
                signal_metadata = getattr(ctx, "signal_metadata", None) or {}
                trade_record["signal_event_id"] = signal_metadata.get("signal_event_id")
                trade_record["entry_signal_time"] = signal_metadata.get("signal_time")
                trade_record["exit_signal_time"] = trade_record.get("exit_signal_time") or self._exit_signal_time(ctx)
                trade_record["exit_reason_code"] = getattr(ctx, "exit_reason_code", None)
                trade_record["exit_reason_label"] = getattr(ctx, "exit_reason_label", None)
                trade_record["exit_reason_detail"] = getattr(ctx, "exit_reason_detail", None)
                trade_record["replacement_trade_id"] = getattr(ctx, "replacement_trade_id", None)
                trade_record["stop_multiple_r"] = getattr(ctx, "stop_multiple_r", None)
                trade_record["risk_reward_ratio"] = getattr(ctx, "exit_risk_reward_ratio", None)
                trade_record["framework_initial_stop_price"] = getattr(ctx, "initial_stop_price", None)
                trade_record["framework_final_stop_price"] = getattr(ctx, "stop_price", None)
                trade_record["framework_tp_price"] = getattr(ctx, "tp_price", None)
                trade_record["strategy_suggested_stop_price"] = signal_metadata.get("suggested_stop_price")

            if not trade_record.get("exit_reason_code"):
                trade_record["exit_reason_code"] = "unclassified_exit"
            if not trade_record.get("exit_reason_label"):
                trade_record["exit_reason_label"] = "未分类退出"

    def _exit_signal_time(self, ctx, fallback=None):
        if ctx is None:
            return None
        exit_key_ref = getattr(ctx, "exit_key_kline_ref", None)
        if exit_key_ref is not None and getattr(exit_key_ref, "dt", None) is not None:
            return exit_key_ref.dt.isoformat()
        if getattr(ctx, "exit_reason_code", None) in {"framework_stop", "risk_reward_take_profit"} and getattr(ctx, "exit_price", None) is not None:
            return fallback
        return None

    def _write_report(self, report):
        reports_dir = self._resolve_reports_dir(report)
        os.makedirs(reports_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        param_suffix = f"_{report['param_id']}" if report.get("param_id") else ""
        filename = f"{self.p.strategy_name}_{self.p.symbol}_{self.p.interval}{param_suffix}_{timestamp}.json"
        filepath = os.path.join(reports_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        self.report_path = filepath

    def _context_value(self, key):
        context = self.p.report_context or {}
        return context.get(key)

    def _report_version(self):
        if self._context_value("optimization_run_id"):
            return "2.0"
        return "1.0"

    def _resolve_reports_dir(self, report):
        reports_dir = os.path.join(os.getcwd(), "reports")
        if report.get("optimization_run_id"):
            return os.path.join(reports_dir, "optimizations", report["optimization_run_id"], "runs")
        return reports_dir

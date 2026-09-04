from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from trader.strategy.lifecycle import SignalSnapshot, TradeContext, TradeStatus


class SignalRouteActionType(str, Enum):
    DETECTED = "detected"
    BLOCKED = "blocked"
    ENTER = "enter"
    EXIT = "exit"


@dataclass(frozen=True)
class SignalRouteAction:
    action_type: SignalRouteActionType
    direction: str
    context: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    exit_reason_code: str | None = None
    exit_reason_label: str | None = None
    exit_reason_detail: str | None = None
    active_trade: dict[str, Any] | None = None


@dataclass(frozen=True)
class SignalRoutingState:
    mode: str
    can_open_new_position: bool
    active_trade: TradeContext | None
    position_size: float


class SignalRouter:
    valid_modes = {"LONG_ONLY", "SHORT_ONLY", "BOTH"}

    def route(self, snapshot: SignalSnapshot, state: SignalRoutingState) -> list[SignalRouteAction]:
        mode = str(state.mode or "LONG_ONLY").upper()
        if mode not in self.valid_modes:
            mode = "LONG_ONLY"

        actions: list[SignalRouteAction] = []
        if snapshot.long_signal:
            actions.append(SignalRouteAction(SignalRouteActionType.DETECTED, "LONG", dict(snapshot.long_context)))
        if snapshot.short_signal:
            actions.append(SignalRouteAction(SignalRouteActionType.DETECTED, "SHORT", dict(snapshot.short_context)))

        no_active_trade = state.active_trade is None or state.active_trade.status in {
            TradeStatus.CLOSED,
            TradeStatus.CANCELLED,
        }
        trade_is_active = state.active_trade is not None and state.active_trade.status == TradeStatus.ACTIVE
        has_long_position = float(state.position_size) > 0.0
        has_short_position = float(state.position_size) < 0.0

        if mode == "LONG_ONLY":
            actions.extend(
                self._entry_actions(
                    signal=snapshot.long_signal,
                    direction="LONG",
                    context=snapshot.long_context,
                    no_active_trade=no_active_trade,
                    can_open_new_position=state.can_open_new_position,
                    active_trade=state.active_trade,
                )
            )
            if snapshot.short_signal and trade_is_active and has_long_position:
                actions.append(
                    SignalRouteAction(
                        SignalRouteActionType.EXIT,
                        "SHORT",
                        dict(snapshot.short_context),
                        reason="signal",
                        exit_reason_code="signal_exit",
                        exit_reason_label="信号出场",
                        exit_reason_detail="LONG_ONLY 模式下出现反向信号",
                    )
                )
            elif snapshot.short_signal:
                actions.append(SignalRouteAction(SignalRouteActionType.BLOCKED, "SHORT", dict(snapshot.short_context), reason="mode"))
            return actions

        if mode == "SHORT_ONLY":
            actions.extend(
                self._entry_actions(
                    signal=snapshot.short_signal,
                    direction="SHORT",
                    context=snapshot.short_context,
                    no_active_trade=no_active_trade,
                    can_open_new_position=state.can_open_new_position,
                    active_trade=state.active_trade,
                )
            )
            if snapshot.long_signal and trade_is_active and has_short_position:
                actions.append(
                    SignalRouteAction(
                        SignalRouteActionType.EXIT,
                        "LONG",
                        dict(snapshot.long_context),
                        reason="signal",
                        exit_reason_code="signal_exit",
                        exit_reason_label="信号出场",
                        exit_reason_detail="SHORT_ONLY 模式下出现反向信号",
                    )
                )
            elif snapshot.long_signal:
                actions.append(SignalRouteAction(SignalRouteActionType.BLOCKED, "LONG", dict(snapshot.long_context), reason="mode"))
            return actions

        actions.extend(
            self._entry_actions(
                signal=snapshot.long_signal,
                direction="LONG",
                context=snapshot.long_context,
                no_active_trade=no_active_trade,
                can_open_new_position=state.can_open_new_position,
                active_trade=state.active_trade,
            )
        )
        actions.extend(
            self._entry_actions(
                signal=snapshot.short_signal,
                direction="SHORT",
                context=snapshot.short_context,
                no_active_trade=no_active_trade,
                can_open_new_position=state.can_open_new_position,
                active_trade=state.active_trade,
            )
        )
        return actions

    def _entry_actions(
        self,
        *,
        signal: bool,
        direction: str,
        context: dict[str, Any],
        no_active_trade: bool,
        can_open_new_position: bool,
        active_trade: TradeContext | None,
    ) -> list[SignalRouteAction]:
        if not signal:
            return []
        if no_active_trade and can_open_new_position:
            return [SignalRouteAction(SignalRouteActionType.ENTER, direction, dict(context))]
        if not no_active_trade:
            return [
                SignalRouteAction(
                    SignalRouteActionType.BLOCKED,
                    direction,
                    dict(context),
                    reason="active_trade",
                    active_trade=self._active_trade_payload(active_trade),
                )
            ]
        return [SignalRouteAction(SignalRouteActionType.BLOCKED, direction, dict(context), reason="equity")]

    def _active_trade_payload(self, active_trade: TradeContext | None) -> dict[str, Any] | None:
        if active_trade is None:
            return None
        key_ref = getattr(active_trade, "key_kline_ref", None)
        entry_time = getattr(key_ref, "dt", None)
        status = getattr(active_trade, "status", None)
        return {
            "trade_id": int(getattr(active_trade, "trade_id", 0)),
            "direction": getattr(active_trade, "direction", None),
            "entry_time": entry_time.isoformat() if entry_time is not None else None,
            "status": getattr(status, "value", str(status)),
        }

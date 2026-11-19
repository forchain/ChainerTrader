"""Notification domain values: notice configuration and notification events.

Pure data and rules; no framework or adapter imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Notice:
    notice_type: str
    server: str
    port: int
    sender: str | None = None
    password: str | None = field(default=None, repr=False)
    recipients: tuple[str, ...] = ()

    @property
    def recipient(self) -> str:
        return ",".join(self.recipients)


@dataclass
class ManualTradeAccountState:
    cash_before: float
    cash_after: float
    position_before: float
    position_after: float


@dataclass
class ManualTradeNotificationEvent:
    market: str
    strategy: str
    task_id: int
    mode: str
    action: str
    side: str
    signal_time: int
    signal_price: float
    suggested_amount: float
    suggested_quantity: float
    trigger_reason: str
    local_state: ManualTradeAccountState
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    interval: Optional[str] = None
    strategy_id: Optional[str] = None
    signal_event_id: Optional[str] = None
    breakeven_new_stop: Optional[float] = None
    breakeven_step: Optional[int] = None
    divergence_metadata: Optional[dict] = None

    def to_dict(self):
        return {
            "market": self.market,
            "interval": self.interval,
            "strategy": self.strategy,
            "strategy_id": self.strategy_id,
            "task_id": self.task_id,
            "mode": self.mode,
            "action": self.action,
            "side": self.side,
            "signal_time": self.signal_time,
            "signal_price": self.signal_price,
            "suggested_amount": self.suggested_amount,
            "suggested_quantity": self.suggested_quantity,
            "trigger_reason": self.trigger_reason,
            "local_state": self.local_state.__dict__,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_reward_ratio": self.risk_reward_ratio,
            "signal_event_id": self.signal_event_id,
            "breakeven_new_stop": self.breakeven_new_stop,
            "breakeven_step": self.breakeven_step,
            "divergence_metadata": self.divergence_metadata,
        }

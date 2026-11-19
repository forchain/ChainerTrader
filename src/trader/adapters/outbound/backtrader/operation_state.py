"""Operation-state helpers shared by the backtrader adapter layer.

The enrichment itself lives in :class:`trader.core.strategy.domain.lifecycle.OperateFactory`
so framework events are built through one typed seam; this module hosts the
order-to-trade-context lookup that the analyzers and the live runtime share.
"""

from trader.core.shared.domain import Operate
from trader.core.strategy.domain.lifecycle import OperateFactory


def trade_context_for_order(strategy, order):
    """Resolve the framework trade context that produced ``order``."""
    tradeid = getattr(order, "tradeid", None)
    if tradeid is None or strategy is None:
        return None
    try:
        trade_ref = int(tradeid)
    except (TypeError, ValueError):
        return None
    resolver = getattr(strategy, "trade_context", None)
    if callable(resolver):
        return resolver(trade_ref)
    return getattr(strategy, "_trades_by_id", {}).get(trade_ref)


def enrich_operation_from_trade_context(op: Operate, ctx) -> Operate:
    """Attach shared framework trade references to an emitted operation."""
    return OperateFactory.enrich(op, ctx)

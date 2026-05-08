# Design: Binance Driver Completion

## Overview
Complete the implementation of the Binance exchange driver to support advanced orders and reconciliation, as required by the `BinanceLiveExecutionGateway`.

## Goals
- Support `get_position_view` for Spot and Cross Margin.
- Support `get_open_protection_orders` for Spot and Cross Margin.
- Support `verify_order_ids`.
- Ensure all advanced order methods (`new_oco_order`, `new_stop_order`, etc.) are robustly implemented for both modes.

## Architecture

### Component Diagram
```
[BinanceLiveExecutionGateway]
      |
      v
[BinanceExchange] <------> [Binance SDK Spot]
      |
      +--> [MarginTradingManager] <------> [Binance SDK Margin]
```

### Key Methods to Implement/Refine

#### BinanceExchange (Spot)
- `get_position_view(symbol: Symbol) -> list[PositionView]`
  - Query Spot account balances.
  - Find balance for `symbol.base`.
  - Map to `PositionView` (Side LONG if > 0).
- `get_open_protection_orders(symbol: Symbol) -> list[ProtectionOrderView]`
  - Query open orders for `symbol`.
  - Filter for "STOP_LOSS", "TAKE_PROFIT", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT" or OCO.
  - Group OCO legs by `orderListId`.
- `verify_order_ids(symbol: Symbol, order_ids: list[str]) -> bool`
  - For now, check if IDs are non-empty and well-formatted.

#### MarginTradingManager (Cross Margin)
- `get_position_view(symbol: Symbol) -> list[PositionView]`
  - Query Cross Margin account details.
  - Find `user_assets` for `symbol.base`.
  - Determine side based on `netAsset` (positive = LONG, negative = SHORT).
- `get_open_protection_orders(symbol: Symbol) -> list[ProtectionOrderView]`
  - Query open margin orders.
  - Map to `ProtectionOrderView`.

## Data Models Mapping

### PositionView
- **Spot:** Base asset balance > 0 => LONG.
- **Margin:** `netAsset` > 0 => LONG, `netAsset` < 0 => SHORT.

### ProtectionOrderView
- **SDK Type** -> **ProtectionIntentType**:
  - `STOP_LOSS`, `STOP_LOSS_LIMIT` -> `STOP_LOSS`
  - `TAKE_PROFIT`, `TAKE_PROFIT_LIMIT` -> `TAKE_PROFIT`
  - OCO -> `BRACKET`

## Testing Strategy
- **Unit Tests:** Mock SDK responses and verify mapping to `PositionView` and `ProtectionOrderView`.
- **Smoke Tests:** Use existing test infrastructure if possible.

## Verification
- Run `pytest tests/test_binance_exchange_start.py` (if relevant) or create new tests.
- Linting and type checking.

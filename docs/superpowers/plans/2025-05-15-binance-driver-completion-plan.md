# Implementation Plan: Binance Driver Completion

## Overview
Implement reconciliation and advanced order verification for Binance Spot and Cross Margin drivers.

## Task List

### Phase 1: Foundation & Models
- [ ] Task 1: Add necessary imports to `exchange.py` and `margin.py`.
  - Files: `src/trader/exchange/binance/exchange.py`, `src/trader/exchange/binance/margin.py`

### Phase 2: Spot Implementation
- [ ] Task 2: Implement `get_position_view` in `BinanceExchange`.
  - Files: `src/trader/exchange/binance/exchange.py`
- [ ] Task 3: Implement `get_open_protection_orders` in `BinanceExchange`.
  - Files: `src/trader/exchange/binance/exchange.py`
- [ ] Task 4: Implement `verify_order_ids` in `BinanceExchange`.
  - Files: `src/trader/exchange/binance/exchange.py`

### Phase 3: Margin Implementation
- [ ] Task 5: Implement `get_position_view` in `MarginTradingManager`.
  - Files: `src/trader/exchange/binance/margin.py`
- [ ] Task 6: Implement `get_open_protection_orders` in `MarginTradingManager`.
  - Files: `src/trader/exchange/binance/margin.py`
- [ ] Task 7: Update `BinanceExchange` to delegate these calls to `MarginTradingManager` when in margin mode.
  - Files: `src/trader/exchange/binance/exchange.py`

### Phase 4: Verification
- [ ] Task 8: Create/update tests to verify implementation.
  - Files: `tests/test_binance_reconciliation.py` (new)
- [ ] Task 9: Run linting and type checking.

## Checkpoint: Complete
- [ ] All tests pass.
- [ ] `BinanceLiveExecutionGateway` can successfully call all required methods.

# Convert Pine Script Indicator to Backtrader

## Command Description

This command converts a TradingView Pine Script indicator to a backtrader Python indicator with matching test cases.

## Usage

1. Provide the Pine Script code (paste or reference file path)
2. Specify the indicator name (e.g., "SuperTrend", "TrendA")
3. The command will generate:
   - Python indicator file: `src/trader/indicators/{indicator_name}.py`
   - Pine Script file (if not exists): `src/pine_scripts/indicators/{indicator_name}.pine`
   - Test file: `tests/trader/indicators/test_{indicator_name}.py`

## Prompt

When I provide a Pine Script indicator, please convert it to backtrader following these steps:

### Step 0: Pine Script Debug Block

Before any analysis, ensure the Pine Script source already contains the standard `debug_times` input and logging block (see `@.cursor/rules/pinescript-to-backtrader.mdc`). If it is missing, add it first so both Pine and Python versions can emit aligned logs. Pine only supports single-line function invocations for `log.info`, so always format each debug call (and other function calls) on a single line to avoid syntax errors. The debug timestamps are entered in **seconds** for both Pine and Python; Pine scripts must multiply by `1000` internally before comparing against `time`.

### Step 1: Analyze the Pine Script

1. Identify all input parameters and their types
2. Identify output lines (plot, plotshape, etc.)
3. Identify recursive/stateful calculations
4. Identify conditional display logic (e.g., `condition ? value : na`)
5. Note any Pine Script features that backtrader doesn't support

### Step 2: Create the Python Indicator

Reference: `@.cursor/rules/pinescript-to-backtrader.mdc`

**Key principle**: Maximize use of backtrader built-in indicators (including `bt.ind.HeikinAshi` for HA conversion). Only create helper `bt.Indicator` subclasses for recursive calculations that backtrader doesn't provide.

Structure the indicator as follows:

```python
"""
{IndicatorName} Indicator

Based on Pine Script v6:
- {Brief description}
"""

import logging
import math

import backtrader as bt

logger = logging.getLogger(__name__)


def _create_ma(line, ma_type, period):
    """Factory for MA indicators - reuse backtrader built-ins."""
    if ma_type == "SMA":
        return bt.ind.SMA(line, period=period)
    if ma_type == "WMA":
        return bt.ind.WeightedMovingAverage(line, period=period)
    return bt.ind.EMA(line, period=period)


class {IndicatorName}(bt.Indicator):
    """
    {IndicatorName} indicator based on Pine Script logic.
    
    Calculation:
    1. {Step 1 description}
    2. {Step 2 description}
    ...
    """

    lines = ("line1", "line2", ...)

    params = (
        ("param1", default_value),
        ("debug_times", None),  # REQUIRED: List of timestamps for debugging
    )

    plotinfo = dict(subplot=False)

    plotlines = dict(
        line1=dict(color="green", _name="Line 1", linewidth=2.0),
        signal=dict(color="green", marker="^", markersize=10.0, ls=""),
    )

    def __init__(self):
        self._debug_timestamps = list(self.p.debug_times) if self.p.debug_times else []
        
        # Chain indicators in __init__ - let backtrader handle execution order
        # For HA-based indicators: first HA conversion, then apply MA
        self.ha = bt.ind.HeikinAshi(self.data)  # Use built-in HeikinAshi
        self.ma1 = _create_ma(self.ha.ha_close, "EMA", self.p.period1)
        self.ma2 = _create_ma(self.ma1, "EMA", self.p.period2)

    def next(self):
        # Just read final values and output - no manual calculations
        self.l.line1[0] = self.ma2[0]
        
        # Debug logging
        if self._debug_timestamps:
            ts = int(bt.num2date(self.data.datetime[0]).timestamp())
            if ts in self._debug_timestamps:
                logger.info("===== {IndicatorName} Debug [time=%s] =====", ts)
```

### Step 3: Update the Pine Script (if needed)

Add debug output matching Python format:

```pine
// Debug settings (timestamps in milliseconds)
debug_times = ''
// debug_times = '1763938800000,1764000000000'

should_debug = false
if str.length(debug_times) > 0
    debug_times_list = str.split(debug_times, ',')
    for i = 0 to array.size(debug_times_list) - 1
        debug_ts = str.tonumber(str.trim(array.get(debug_times_list, i)))
        if not na(debug_ts) and time == debug_ts
            should_debug := true

if should_debug
    log.info('===== {IndicatorName} Debug [time={0}] =====', time)
    // Log matching Python format
```

### Step 4: Create Test File

Reference: `tests/trader/indicators/test_super_trend.py`

```python
"""
Test {IndicatorName} indicator with BTC-USDT 1h data.
"""
# ... (follow test_super_trend.py template)
```

### Step 5: Verify

1. Run the test: `pytest tests/trader/indicators/test_{indicator_name}.py -v`
2. Compare with TradingView:
   - Enable debug_times on both sides
   - Compare log output
   - Compare CSV data
   - Compare chart visually

## Critical Conversion Rules

### Heikin Ashi with request.security (CRITICAL)

Pine Script's `request.security(ha, tf, expr)` executes an expression in the HA data context:

```pine
// Pine Script
o = f_ma_type(ma_type, open, ma_period)     // Expression definition
ha = ticker.heikinashi(syminfo.tickerid)    // Get HA ticker
ha_o = request.security(ha, timeframe.period, o)  // Execute on HA data
```

**Key insight**: The expression `o` uses `open`, which becomes HA's open when executed via `request.security`.

**Correct conversion**: First convert to HA, then apply MA.

```python
# Python - CORRECT
self.ha = bt.ind.HeikinAshi(self.data)  # Step 1: Get HA data
ha_o_ma = bt.ind.EMA(self.ha.ha_open, period=ma_period)  # Step 2: MA on HA
```

**Common Error**: `MA(raw_open) → HA conversion` is WRONG. Correct is: `HA conversion → MA(ha_open)`.

### Bar Index Reference
- Pine `close[1]` = Python `self.data.close[-1]` (previous bar)
- Pine `close` or `close[0]` = Python `self.data.close[0]` (current bar)

### NaN Handling
- Pine `nz(value[1], default)` = Python `prev if prev is not None else default`
- Pine `na` = Python `math.nan`

### Conditional Display
- Pine `condition ? value : na` = Python `value if condition else math.nan`

### Signals (backtrader limitation)
- Pine `plotshape(..., text="Buy")` → Python marker only, no text labels
- Use `marker="^"` for buy, `marker="v"` for sell
- Signal value = price position, not 0/1

### Trend Logic
- Convert ternary chains to explicit if-elif-else for clarity

## Error Recovery

If the converted indicator doesn't match TradingView:

1. Enable debug_times on both sides with the same timestamps
2. Compare the debug logs line by line
3. Identify which calculation step differs
4. Common issues:
   - Wrong bar index reference (close vs close[-1])
   - Incorrect recursive variable initialization
   - Missing NaN for invisible lines
   - Signal at wrong price position

Update `.cursor/rules/pinescript-to-backtrader.mdc` with new learnings for future conversions.


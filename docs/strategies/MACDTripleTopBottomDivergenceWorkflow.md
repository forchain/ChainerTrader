# MACD Triple Divergence Workflow

This note is the handoff entry point for continuing MACD triple divergence work on another machine, another Codex session, or a plain terminal.

## Generate A Fresh Report

From the repo root:

```bash
uv run python scripts/run_macd_triple_divergence_report.py
```

The script prints the full path of the newly generated JSON report.

Optional flags:

```bash
uv run python scripts/run_macd_triple_divergence_report.py \
  --data data/BTCUSDT-1d-20170101-20251231.csv \
  --cash 100000 \
  --commission 0.001
```

## Where Reports Go

Reports are written to:

```bash
reports/macd_triple_divergence_BTCUSDT_1d_<timestamp>.json
```

To inspect the newest report:

```bash
ls -1t reports | head -1
```

## What The Report Contains

The JSON includes:

- `summary`: aggregate backtest metrics
- `trades`: executed trades
- `signals`: every detected signal with context
- `documented_cases`: all 15 document cases, including failed examples, with debug analysis

Each signal includes:

- `signal_time`
- `signal_type`
- `signal_bar`
- `legs`
- `conditions.separator_details`
- `trade_outcome`

Each leg now includes:

- `wave_start_time`
- `wave_end_time`
- `macd_half_strength`
- `wave_price_low` / `wave_price_high`
- `trigger_price_extreme_so_far` for the third leg when applicable

## Current Working Rules

This workflow now matches the current implementation and the validated document cases.

### Parameters

- `noise_cluster_ratio = 0.10`
  - Used only for near-zero separator detection and near-zero split candidates.
- `weak_wave_filter_ratio = 0.11`
  - Used only for filtering interior weak same-sign waves.
- `trigger_latest_leg_min_ratio = 0.10`
  - Used only at actual signal trigger time for the latest leg.
- `max_same_sign_waves = 5`
  - Hard cap on the same-sign wave count inside the selected local triplet window.

### Wave Construction

- MACD histogram is first split into raw same-sign segments.
- A sign flip creates a new raw segment.
- A same-sign retrace that comes back close to zero can also create a split candidate.
- Near-zero is defined relative to neighboring wave MACD extremes with `noise_cluster_ratio = 0.10`.

### Effective Wave Rules

- Near-zero split is only a candidate split, not an automatic new effective wave.
- If a resumed same-sign wave does not create new directional price progress, it should not become a new effective wave.
- For a tiny opposite-color separator between two same-sign waves:
  - if the resumed wave does not beat the previous same-sign wave in price, ignore it
  - if it beats the previous same-sign wave in price, extends the MACD extreme, and also beats the separator’s own price extreme, merge it back into the previous effective wave
  - otherwise keep it as a new effective wave

### Weak-Wave Filtering

- Weak-wave filtering uses segment-level MACD extreme strength: `abs(wave.extreme_val)`.
- It does not use `macd_half_strength`.
- Filtering compares the current interior same-sign wave against the previous kept same-sign wave.
- A wave is filtered when:

```text
abs(current_wave_macd_extreme) / abs(previous_kept_wave_macd_extreme) < weak_wave_filter_ratio
```

- With the current defaults, an interior wave below `11%` of the previous kept wave is treated as weak noise.
- The latest leg is kept available during candidate construction even if it is small; its minimum strength is checked later at trigger time.

### Triplet Selection

- Divergence candidates are taken from the latest effective same-sign waves.
- Only the latest contiguous triplet is allowed after weak-wave filtering.
- Non-contiguous combinations such as `1/3/4` are invalid.
- The same-sign wave count limit is applied to the selected local triplet window, not to the entire lookback history.

### Price Ownership Rules

- The second and third legs must each own their directional price progress.
- That means a leg must not only improve on the previous same-sign leg, but also beat the adjacent opposite-color separator’s price extreme.
- This rule prevents counting a new low/high that was actually made by the separator instead of by the divergence leg itself.

### Trigger Rules

- Structure uses MACD segment extremes for the first two legs.
- The third leg is triggered only on the first shortening bar after a confirmed local MACD pivot.
- At the trigger bar, the third leg’s price is evaluated using the directional price extreme seen so far in that leg.
- The latest leg must also pass the trigger strength gate:

```text
abs(latest_leg_macd_extreme) / abs(previous_leg_macd_extreme) >= trigger_latest_leg_min_ratio
```

- With the current defaults, the latest leg must reach at least `10%` of the previous leg’s MACD extreme to actually trigger.

### Validation Status

- The focused regression suite for the strategy and report is green.
- The 15 documented cases match in the current report output.
- Signal count and documented cases are aligned; if report signals exceed the article examples by one, the extra early signal is due to the article’s later manual backtest start window rather than a current rule mismatch.

## Validation Commands

Run the focused regression suite:

```bash
uv run pytest tests/test_macd_triple_divergence_strategy.py \
  tests/test_macd_triple_divergence_report.py -q
```

## Suggested Continue Flow

1. Generate a fresh report.
2. Check `documented_cases` first, then `signals`.
3. Inspect `documented_cases[*].analysis.recent_streak_legs`, `price_qualified_legs`, `selected_triplet_legs`, `trigger_pivot`, and `fail_reason`.
4. Compare unmatched documented cases against the article screenshots.
5. Re-run tests.
6. Re-generate the report.

---
name: macd-triple-divergence-report
description: "Generate the MACD triple divergence JSON report for this repo and print the new file path."
---

# MACD Triple Divergence Report

Use this skill when you want a fresh structured report for the MACD triple divergence strategy in this repository.

## Command

Run from the repo root:

```bash
uv run python scripts/run_macd_triple_divergence_report.py
```

The command prints the absolute path of the newly generated report file.

## Optional Parameters

```bash
uv run python scripts/run_macd_triple_divergence_report.py \
  --data data/BTCUSDT-1d-20170101-20251231.csv \
  --cash 100000 \
  --commission 0.001
```

## Follow-up

After generating the report, inspect the newest file in `reports/` and focus on:

- `signals`
- `legs[*].macd_half_strength`
- `conditions.separator_details`
- `trade_outcome`

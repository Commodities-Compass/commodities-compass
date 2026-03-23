# Indicator Computation Engine

Replaces the Google Sheets formula engine (21,468 formulas across 4 sheets) with a Python pipeline that computes all technical indicators, normalizations, and trading signals from raw OHLCV data.

## Architecture

```
pl_contract_data_daily (raw OHLCV)
    │
    ├─→ registry.compute_all()         # 14 indicators in topological order
    │   └─→ pl_derived_indicators      # 27 columns
    │
    ├─→ smoothing.compute_raw_scores() # 5-day SMA on 5 indicators + 1 direct
    │
    ├─→ normalization.normalize_scores() # Rolling 252-day z-score
    │
    ├─→ composite.compute_signals()    # NEW CHAMPION power formula
    │   ├─→ pl_indicator_daily         # scores + norms + composite + decision
    │   └─→ pl_signal_component        # per-indicator weighted contributions
    │
    └─→ pipeline.run(df) → PipelineResult
```

All functions are **pure** (no I/O, no DB, no side effects) and operate on pandas DataFrames. The DB layer (`db_writer.py`, `runner.py`) is separate.

## File Structure

```
app/engine/
├── types.py                  # AlgorithmConfig (frozen), column constants
├── indicators/
│   ├── base.py               # Indicator protocol
│   ├── pivots.py             # Classical pivot points (7 outputs)
│   ├── ema.py                # EMA12, EMA26 (SMA seed, recursive)
│   ├── macd.py               # MACD + Signal(9)
│   ├── rsi.py                # Wilder's RSI (14-period, recursive)
│   ├── stochastic.py         # %K, %D (14-period, clamped 0-100)
│   ├── atr.py                # True Range + Wilder's ATR (α=1/14)
│   ├── bollinger.py          # SMA(20) ± 2×STDEV(20), symmetric
│   └── ratios.py             # Close/Pivot, Vol/OI, daily return
├── registry.py               # Topological sort on dependency graph
├── smoothing.py              # 5-day SMA scoring layer
├── normalization.py          # Rolling z-score (252-day default)
├── composite.py              # Power formula + decision thresholds
├── pipeline.py               # Orchestrator: PipelineResult
├── db_writer.py              # Upsert results to 3 pl_* tables
└── runner.py                 # CLI: poetry run compute-indicators
```

## Usage

```bash
# Dry run — compute and print, no DB write
poetry run compute-indicators --contract CAK26 --dry-run

# Full run — compute and write to DB
poetry run compute-indicators --contract CAK26

# Custom normalization window
poetry run compute-indicators --contract CAK26 --window 365

# Specific algorithm and version
poetry run compute-indicators --contract CAK26 --algorithm legacy --algorithm-version 1.0.0
```

## Programmatic Usage

```python
from app.engine.pipeline import IndicatorPipeline
from app.engine.types import LEGACY_V1

pipeline = IndicatorPipeline(config=LEGACY_V1, normalization_window=252)
result = pipeline.run(raw_df)

# result.derived    → DataFrame with 27 indicator columns
# result.scores     → + 6 raw score columns
# result.normalized → + 6 z-score columns
# result.signals    → + final_indicator, decision, momentum
```

## Indicator Reference

### Derived Indicators (pl_derived_indicators)

| Indicator | Module | Outputs | Warmup | Dependencies |
|-----------|--------|---------|--------|--------------|
| Pivot Points | `pivots.py` | pivot, r1-r3, s1-s3 | 0 | high, low, close |
| EMA12 | `ema.py` | ema12 | 12 | close |
| EMA26 | `ema.py` | ema26 | 26 | close |
| MACD | `macd.py` | macd | 26 | ema12, ema26 |
| MACD Signal | `macd.py` | macd_signal | 35 | macd |
| RSI (Wilder) | `rsi.py` | rsi_14d, gain_14d, loss_14d, rs | 15 | close |
| Stochastic %K | `stochastic.py` | stochastic_k_14 | 14 | close, high, low |
| Stochastic %D | `stochastic.py` | stochastic_d_14 | 16 | stochastic_k_14 |
| True Range | `atr.py` | atr | 1 | high, low, close |
| ATR (Wilder) | `atr.py` | atr_14d | 14 | atr (true range) |
| Bollinger Bands | `bollinger.py` | bollinger, upper, lower, width | 20 | close |
| Close/Pivot | `ratios.py` | close_pivot_ratio | 0 | close, pivot |
| Volume/OI | `ratios.py` | volume_oi_ratio | 0 | volume, oi |
| Daily Return | `ratios.py` | daily_return | 1 | close |

### Scoring Layer (smoothing.py)

5-day SMA smoothing applied to reduce daily noise:

| Score | Source | Smoothed? |
|-------|--------|-----------|
| rsi_score | rsi_14d | Yes (SMA5) |
| macd_score | macd | Yes (SMA5) |
| stochastic_score | stochastic_k_14 | Yes (SMA5) |
| atr_score | atr_14d | Yes (SMA5) |
| close_pivot | close_pivot_ratio | No (direct) |
| volume_oi | volume_oi_ratio | Yes (SMA5) |

### Normalization (normalization.py)

Rolling z-score with configurable window:

```
z = (x - mean(x, 252d)) / std(x, 252d)
```

- Default window: 252 trading days (~1 year)
- Outlier cap: ±10 (clip, don't replace)
- Min periods: max(window/2, 20) before producing values

### Composite Score (composite.py)

NEW CHAMPION power formula:

```
SCORE = k + Σ (coefficient × sign(input) × |input|^exponent)
```

8 input pairs: RSI, MACD, Stochastic, ATR, Close/Pivot, Vol/OI, Momentum, Macroeco.

Decision thresholds:
- `SCORE ≥ 1.5` → **OPEN**
- `SCORE ≤ -1.5` → **HEDGE**
- Otherwise → **MONITOR**

Momentum is binary ±0.2, derived from the linear indicator direction change.

## Bugs Fixed vs Google Sheets

| Bug | Sheets | Engine |
|-----|--------|--------|
| RSI smoothing | SMA (SUM/14) | Wilder's `(prev×13 + current) / 14` |
| RSI window | 13 values / 14 (off-by-one) | 14 values / 14 |
| ATR smoothing | EMA α=2/15 | Wilder's α=1/14 |
| Stochastic range | Excludes today's H/L, goes negative | Includes today, clamped 0-100 |
| Bollinger bands | Asymmetric (STDEVP vs STDEV, different windows) | Symmetric SMA(20) ± 2×STDEV(20) |
| Pivot anchoring | 1.1x multiplier, anchored on Close | Standard classical, anchored on Pivot |
| Z-score normalization | Full-history AVERAGE/STDEV (look-ahead bias) | Rolling 252-day window |
| Decision labels | MONITOR/HEDGE swapped | Correct: negative = HEDGE |
| INDICATOR!Q formula | Linear for rows 2-352, power for 353-354 | Same formula for all rows |

## Design Principles

1. **Pure functions** — every indicator is `compute(df) → df`, no side effects
2. **Immutable** — input DataFrames are never mutated, always copied
3. **Dependency resolution** — topological sort handles computation order automatically
4. **Config as data** — algorithm params loaded from `pl_algorithm_config`, not hardcoded
5. **Contract-centric** — all data keyed on `(date, contract_id)`, enabling multi-contract
6. **Idempotent writes** — DB writer uses upsert, safe to re-run

## Adding a New Indicator

1. Create a file in `indicators/` implementing the `Indicator` protocol:

```python
class MyIndicator:
    name = "my_indicator"
    outputs = ("my_output_col",)
    depends_on = ("close",)  # what it reads
    warmup = 10              # rows before first valid output

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        result["my_output_col"] = ...
        return result
```

2. Add it to `indicators/__init__.py` → `ALL_INDICATORS` list
3. Add the column to `pl_derived_indicators` model + Alembic migration
4. Write tests in `tests/engine/test_indicators.py`

The registry handles ordering automatically from `depends_on` → `outputs`.

## Tests

```bash
# Run engine tests only
poetry run pytest tests/engine/ -v

# With coverage
poetry run pytest tests/engine/ -v --cov=app/engine --cov-report=term-missing
```

75 tests covering all indicators, composite scoring, normalization, registry, and pipeline integration.

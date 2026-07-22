# Time-Series Uniqueness — One Row Per Time Step, Asserted

> Origin: 2026-07-22 — `load_all_market_data` / `load_market_data` LEFT-JOINed `macroeco_bonus` from `pl_indicator_daily` on `(date, contract_id)` only, but that table is keyed on `(date, contract_id, algorithm_version_id, language)`. With ≥2 compute-enabled versions (legacy + power10years) and the fr/en language dimension, the join **fanned the OHLCV series out 2-5×** — duplicate dates. The engine computes EMA/RSI/ATR (Wilder), Bollinger, stochastic and 252-day z-scores **positionally** over the row order, with no dedup, so every rolling/recursive value was computed over a doubled series → **`pl_derived_indicators` corrupted across all history**. The writer upserts one row per `(date, contract)` (last-write-wins), so the stored table *looked* clean while holding wrong numbers — which is why it went unnoticed for months. The corruption flipped decisions (MONITOR↔OPEN) and propagated into the **ensemble/dashboard** (the 14 specialists read those exact `pl_derived_indicators` columns as pure passthrough features).

## The Principle

Any query whose result feeds a **rolling / recursive / positional** time-series computation MUST return **exactly one row per time step** (per date, per entity). A series with duplicate time steps silently corrupts every downstream indicator — no error, no NaN, just plausible-but-wrong numbers. Correctness here is an **invariant**, and an unasserted invariant is a latent bug waiting for a new dimension (a new algorithm version, a new language, a new join) to break it.

## Rules

### 1. Assert uniqueness at every series-load boundary — fail loud

Every function that loads a time-series for computation ends with a uniqueness check:
```python
_assert_unique_dates(df, "load_all_market_data")   # raises if df["date"] is not unique
```
This turns any future fan-out into an **immediate crash** instead of silent corruption. It is cheap and it is the only runtime guarantee. Never skip it "because the query looks fine" — the macroeco join looked fine for months.

### 2. Joins that can fan out must be constrained to one row — or moved out

A `LEFT JOIN` onto a table with a **wider unique key** than your join predicate fans out. Before adding such a join to a series loader, ask: *does the joined table have rows the join key does not distinguish (version? language? a 1-to-many child)?* If yes, either:
- constrain it to one row (`DISTINCT ON`, `LEFT JOIN LATERAL (... LIMIT 1)`, or filter the extra dimensions), **or**
- **keep it out of the loader entirely** and attach it downstream where the discriminator is known (e.g. `macroeco_bonus` is now merged per-algorithm-version in `_run_for_version`, not in the loader — the loader stays pure OHLCV and cannot fan out).

Prefer "keep it out" — a loader that never touches the multi-keyed table **cannot** fan out, which is stronger than a filter that a future edit might loosen.

### 3. Tests must reproduce the multi-dimension reality

A regression test for any series loader MUST seed the **fan-out conditions** (≥2 algorithm versions AND ≥2 languages per `(date, contract)`) and assert the loader still returns one row per date. Single-version/single-language fixtures hide this entire bug class — that is exactly why CI stayed green while prod was corrupted (see `tests/test_indicator_loader_fanout.py`).

### 4. A "clean" stored table is not proof of correct computation

An upsert on `(date, contract)` de-duplicates *at write time* — the stored table shows one row per date even when the in-memory series it was computed from was doubled. **Never** infer computation correctness from the shape of the stored table. Verify against a **deduplicated recompute** or hand-checked golden values.

## When to check

Before writing or reviewing any code that:
- loads a DataFrame/series that will be passed to a rolling/recursive/positional computation (indicator engines, GARCH, z-scores, EMA/RSI/ATR, cumulative returns);
- adds or modifies a JOIN in such a loader;
- adds a new discriminating column to a table a loader joins (a new algorithm version, a new language, a new tenant, a new provider).

Ask: **"Can this return more than one row per time step?"** If you cannot prove no, add the `_assert_unique_dates` guard and a fan-out regression test.

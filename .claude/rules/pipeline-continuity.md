# Pipeline Continuity — Computation-to-Storage Contract

> Origin: 2026-03-26 — momentum computed correctly inside `_compute_final_indicator` but never returned; writer hardcoded 0.0, corrupting 3 production rows. Separately, `pl_signal_component.raw_value` stores z-scores instead of pre-normalization scores because the writer only mapped one column where two were needed.

## The Principle

The indicator engine is a **mathematical pipeline**: raw data flows through computation stages, and each stage produces values that the next stage or the storage layer consumes. The storage layer is a **faithful mirror** of what computation produced — it receives, it stores, it does not invent.

**If a value is computed, it must be stored as-is. If it's not yet computable, store NULL. Never substitute a constant for a computed result.**

## Rules

### 1. Writer functions receive — they don't compute or invent

A DB writer (INSERT/UPDATE) must get every computed column value as a **parameter from its caller**. If the writer needs a value it doesn't have, the fix is upstream: expand the return type, add a parameter, plumb the data through. Never patch the writer with a literal.

**Test**: for every column in an INSERT/UPDATE, can you trace the value back to a computation function's return value or an explicit caller parameter? If the answer is "no, it's a literal in the writer," that's a bug — unless it falls under the exceptions below.

### 2. Function signatures must expose all computed values that downstream needs

If a function computes a value internally and that value must be stored, the function **must return it**. A local variable that gets used then discarded is a data flow leak.

**Test**: list every value a function computes. For each one: is it returned, or does it die as a local? If it dies but shows up in a DB column downstream (even as a placeholder), the signature is incomplete.

### 3. Two columns = two distinct data sources

If a table has `raw_value` and `normalized_value` (or any pair of semantically distinct columns), the writer must read from **two different sources**. Setting `normalized = raw` is only valid when the value genuinely has no normalization step (e.g., momentum, macroeco) — and in that case, document why.

### 4. NULL means "not yet computed" — zero does not

If a computed value isn't available at write time, the column must be **NULL**. Zero (0, 0.0) is a valid mathematical result and must never be used as a placeholder. NULL is queryable (`WHERE col IS NULL`), makes gaps visible, and won't silently corrupt downstream formulas.

## Exceptions — what IS fine to hardcode in writers

- **Identity/metadata columns**: `pipeline_name="daily-analysis-db"`, `category="macro"`, `status="success"` — these describe WHAT wrote the row, not computed results.
- **Schema defaults**: `server_default=func.now()`, auto-generated UUIDs.
- **Algorithm config values**: coefficients intentionally set to 0 in `pl_algorithm_config` — that's parameter tuning, not a bug. The coefficient is the source of truth; the resulting `weighted_contribution=0` is mathematically correct.
- **Safe defaults in READ paths**: `or 0.0` when reading a nullable column for display or downstream computation — the storage is correct, the consumer is protecting itself.

## When to check

Before writing or reviewing any code that touches `INSERT INTO` or `UPDATE ... SET`:

1. For each column, classify: is this a **computed result** or a **config/metadata** value?
2. For computed results: trace the value from computation → return → caller → writer. Is the chain complete?
3. Look for TODO/FIXME/HACK near write statements — these are confirmed leaks, not plans.
4. Check function return types: does the computation return everything the writer needs?

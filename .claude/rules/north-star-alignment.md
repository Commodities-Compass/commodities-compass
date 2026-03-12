# North Star — Directional Alignment Check

> Full MCD design: [The_North_Star.md](../../The_North_Star.md) — validated 2026-02-25.
> Implementation is incremental. This rule is NOT about enforcing the full 43-table MCD now.
> It IS about catching work that actively contradicts the long-term architectural direction.

## When to check

Before any schema change, new table, new data flow, or significant refactor — do a quick mental pass against the principles below. If something looks like it's heading in the opposite direction of the North Star, ask the user: *"This works for now, but it conflicts with [principle X] from the North Star — is that intentional or should we adjust?"*

## Core directional principles

1. **Contract-centric over commodity-centric** — the long-term model keys market data to contracts (CAK26), not commodities. Don't create new structures that make this harder to reach later.

2. **Immutable raw data** — raw ingested data and produced signals should not be updated or deleted in place. Prefer append patterns where practical.

3. **Pipelines are shared, tenants subscribe** — tenant-specific logic should stay separate from pipeline computation logic. Don't tightly couple the two.

4. **Config as data, not code** — algorithm parameters and thresholds are heading toward being DB-configurable rows. Avoid new hardcoded constants that should eventually be tunable.

5. **Schema namespaces** — tables will eventually live in separated PG schemas (reference, pipeline, audit, tenant). Keep a mental note of which domain a new table belongs to.

6. **Rolling normalization** — full-history z-scores are a known anti-pattern. If touching normalization logic, prefer rolling windows.

## What this rule does NOT mean

- You don't need to implement EAV, multi-tenant, or the full schema now
- You don't need to refactor existing code to match the MCD
- Pragmatic shortcuts are fine as long as they don't actively block the migration path
- The question is "does this make the North Star harder to reach?" — not "does this implement the North Star?"

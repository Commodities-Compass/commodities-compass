# Compass Wrapper Levers — Tuning & Rollback Runbook

> Compass-side levers on the ensemble decision, all **config-as-data** in
> `pl_algorithm_config` (scoped to `ensemble_v1_softgate_wrapper` v1.0.0). Tunable /
> disable-able **without a redeploy** — append the row, the next `cc-ensemble-compute`
> run picks it up. Levers added 2026-06 (migration `e7f8a9b0c1d2`); **temporal config +
> C5-full retune 2026-07-22** (migration `g2b3c4d5e6f7`).
> See [PIPELINE_ENSEMBLE.md §4.1](../architecture/PIPELINE_ENSEMBLE.md).

## ⚠️ Config is TEMPORAL (append-only) since 2026-07-22

`pl_algorithm_config` carries `effective_from DATE` + `active BOOLEAN`, unique on
`(algorithm_version_id, parameter_name, effective_from)`. **Never UPDATE or DELETE a
config row** — that destroys provenance. Instead:

- **Change a value** → INSERT a new row with `effective_from = today` (the old row stays
  as history).
- **Turn a lever off** → INSERT a **tombstone** row (`active = false`, `effective_from = today`).
  Absent-from-current-view ⇒ lever OFF by design.
- The runtime reads the VIEW **`v_algorithm_config_current`** = latest row per param with
  `effective_from <= CURRENT_DATE`, kept only if `active`. All config loaders
  (`scripts/ensemble_compute/cluster_mapping_loader.py`, `app/engine/runner.py`) go
  through it.
- Audit "what changed when": `SELECT parameter_name, value, effective_from, active FROM
  pl_algorithm_config WHERE algorithm_version_id = … ORDER BY parameter_name, effective_from;`

**Never ship a config change as a new `pl_algorithm_version`** — the pipeline assumes ONE
continuous ensemble version (YTD, wrapper trailing windows, explainer/brief pin the
version). The v1.1.0 attempt of 2026-07-22 broke all of those in cascade before being
collapsed (PRs #75→#77). Temporal config IS the versioning.

## The levers (current = C5-full, effective 2026-07-22)

| Lever | Config key | Current | History | Effect |
|---|---|---|---|---|
| **alpha_macro cap** | `compass_softgate_alpha_macro_cap` | **0.3** | 0.9 (2026-06) → 0.3 | Caps the soft-gate `alpha_macro` (tuned 1.477). **Dominant lever of the C5-full retune**: the LLM press-review macro signal is noisy — over-weighted it degrades dir-acc. At 0.3 it is a mild tilt. |
| **commit_threshold** | `commit_threshold` | **0.15** | 0.2493 (artifact) → 0.15 | Soft-gate commit band on \|net_score\|. Wired from config since 2026-07-22 (`ensemble_compute/main.py` override, mirrors the alpha-cap pattern). Lower ⇒ more actionable days. |
| **Trend-conflict (FIX2)** | `wrapper_use_trend_conflict` / `wrapper_tau_trend` | `1` / **0.05** | tau 0.03 → 0.05 | Detector kept; at 0.03 it over-vetoed correct commits on corrected indicators. |
| **regime-MONITOR** | `compass_regime_monitor_atr_pctl` | **OFF (tombstone)** | 0.80 active → 0.80 `active=false` | On corrected data its veto-precision was **0.14** (killed 25 winners / 4 losers) — its "top-vol ⇒ dir-acc < break-even" premise was an artifact of the macroeco corruption. Code path remains, config-gated. |

Validation (143 corrected sessions, harness `backend/scripts/research/wrapper_retune_*.py`):
published dir-acc **75→88 %** full / **57→87.5 %** last-50, actionable days **14→35 %**,
robust J+3..J+6, spread across months, not downtrend-beta (OPEN 7/7 incl. the June rally).

## How the published decision is composed

```
soft-gate(alpha_macro capped 0.3)  →  Compass wrapper (trend/run_acc/dispersion)  →  [regime-MONITOR if configured — OFF]
        ↓                                   ↓                                            ↓
   soft_gate_decision                 decision_wrapped                         pl_indicator_daily.decision (PUBLISHED)
                                      (audit, in pl_orchestrator_decision)      regime_monitor_fired = the override flag
```

## Tune a lever (no redeploy) — APPEND, never UPDATE

Prod via the IAP bastion (`.local/db-prod.sh`) — a deliberate config append, allowed on
explicit intent per `migrations-prod-via-main-only` §2 (DML, not DDL). Prefer landing it
as an idempotent migration when not urgent.

```sql
-- e.g. re-enable regime-MONITOR at a higher threshold, effective today
INSERT INTO pl_algorithm_config (id, algorithm_version_id, parameter_name, value, description, effective_from, active)
SELECT gen_random_uuid(), v.id, 'compass_regime_monitor_atr_pctl', '0.90',
       're-enabled at 0.90 after forward validation', CURRENT_DATE, true
FROM pl_algorithm_version v WHERE v.name = 'ensemble_v1_softgate_wrapper' AND v.version = '1.0.0';
```

## Disable a lever (instant rollback) — tombstone

```sql
-- e.g. alpha_macro cap OFF (soft-gate falls back to the artifact value 1.477 — NOT recommended)
INSERT INTO pl_algorithm_config (id, algorithm_version_id, parameter_name, value, description, effective_from, active)
SELECT gen_random_uuid(), v.id, 'compass_softgate_alpha_macro_cap', '0.3',
       'tombstone — cap disabled', CURRENT_DATE, false
FROM pl_algorithm_version v WHERE v.name = 'ensemble_v1_softgate_wrapper' AND v.version = '1.0.0';
```

To revert a change made TODAY (same `effective_from`, unique conflict): that single case
is a value `UPDATE` of today's row — the only in-place edit that doesn't lose history.

The next `cc-ensemble-compute` run (19:18 UTC) reflects the change. **Gotcha for manual
re-runs**: `gcloud run jobs execute --args=…` REPLACES the job's full arg list — replicate
the defaults (e.g. `--language both`) or you silently drop them.

## Watch-list

- `alpha_macro_cap=0.3` and `commit_threshold=0.15` were tuned on 143 corrected sessions
  (Dec-2025→Jul-2026, HEDGE-heavy downtrend). Re-evaluate quarterly with
  `wrapper_retune_softgate.py` as data accrues.
- regime-MONITOR stays off unless a forward analysis shows a regime where committing is
  reliably EV-negative (score-grid break-even ≈ 81 % dir-acc).

## Research provenance

`backend/scripts/research/` (non-production):
- **`wrapper_retune_{verify,recompute,lib,sweep,robustness,explore,softgate,softgate_robust,joint_check}.py`**
  — the 2026-07-22 C5-full harness: pinned recompute, in-memory evaluator that reproduces
  prod exactly (wrapper = pure post-process of soft-gate output), veto-precision
  diagnostic, Pareto sweep, recency/horizon/beta robustness, soft-gate alpha sweep.
- `wrapper_levers_decade_backtest.py` (recency-weighted selectivity judge that rejected
  COT/OI/IV levers), `resimulate_may_to_now.py`, `p0_macro_gate_retune.py`,
  `robustness_fixes_backtest.py`. See
  [SOFTGATE_MACRO_GATE_RETUNE_SPEC.md](../research/SOFTGATE_MACRO_GATE_RETUNE_SPEC.md).

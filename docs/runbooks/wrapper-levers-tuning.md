# Compass Wrapper Levers — Tuning & Rollback Runbook

> Three Compass-side levers on the ensemble decision, all **config-as-data** in
> `pl_algorithm_config` (scoped to `ensemble_v1_softgate_wrapper`). Tunable / disable-able
> **without a redeploy** — flip the row, the next `cc-ensemble-compute` run picks it up.
> Added 2026-06 (migration `e7f8a9b0c1d2`). See [PIPELINE_ENSEMBLE.md §4](../architecture/PIPELINE_ENSEMBLE.md).

## The levers

| Lever | Config key | Active value | Effect | Validation |
|---|---|---|---|---|
| **Trend-conflict detector (FIX2)** | `wrapper_use_trend_conflict` | `1` | Wrapper dampens a commit → MONITOR when the realized 7d return is opposite `net_score` by > `wrapper_tau_trend` (0.03). Reactive (price already moved against the bet). | +1.69 Σ on the 6-month ensemble backfill; catches the 05-01 HEDGE-on-+15.85%. |
| **regime-MONITOR** | `compass_regime_monitor_atr_pctl` | `0.80` | Overrides a committed decision → MONITOR when today's `atr_14d/close` percentile (trailing 252 sessions) exceeds the threshold. EV: in top-vol regimes dir-accuracy (~76%) < the score-grid break-even (~81%). | ⚠️ **In-sample** (threshold fitted on the 6-month data). It is *abstention*, not prediction — it mutes winners too (e.g. June correct HEDGEs). Watch it forward. |
| **alpha_macro cap** | `compass_softgate_alpha_macro_cap` | `0.9` | Caps the soft-gate `alpha_macro` (tuned 1.477) so a specialist voting against `macro_direction` is down-weighted `(1−0.9)`, never zeroed `(1−1.477)→0`. Dissolves the unanimous `net_score=−1.000` collapse. | Robustness; ≈neutral on May decisions (the May consensus was genuinely bearish), prevents the future macro-disagree pathology. |

## How the published decision is composed

```
soft-gate(alpha_macro capped)  →  Compass wrapper (trend/run_acc/dispersion)  →  regime-MONITOR override
        ↓                                   ↓                                            ↓
   soft_gate_decision                 decision_wrapped                         pl_indicator_daily.decision (PUBLISHED)
                                      (audit, in pl_orchestrator_decision)      regime_monitor_fired = the override flag
```

- `pl_orchestrator_decision.decision_wrapped` = the **wrapper's** output (unchanged audit semantics).
- `pl_orchestrator_decision.regime_monitor_fired` = `True` when regime-MONITOR forced MONITOR on top.
- `pl_indicator_daily.decision` (what the dashboard serves) = the **regime-adjusted final**.

## Tune a lever (no redeploy)

Connect to prod via the IAP bastion (read-only by default — this is a deliberate **value UPDATE**, allowed on
explicit intent per `migrations-prod-via-main-only` §2, NOT a DDL change):

```sql
-- e.g. raise the regime-MONITOR threshold to be less trigger-happy (fewer abstentions)
UPDATE pl_algorithm_config SET value = '0.90'
WHERE parameter_name = 'compass_regime_monitor_atr_pctl'
  AND algorithm_version_id = (SELECT id FROM pl_algorithm_version WHERE name = 'ensemble_v1_softgate_wrapper');
```

## Disable a lever (instant rollback, no redeploy)

```sql
-- regime-MONITOR OFF: delete the row (absent row → lever OFF by design)
DELETE FROM pl_algorithm_config
WHERE parameter_name = 'compass_regime_monitor_atr_pctl'
  AND algorithm_version_id = (SELECT id FROM pl_algorithm_version WHERE name = 'ensemble_v1_softgate_wrapper');

-- alpha_macro cap OFF: same (delete compass_softgate_alpha_macro_cap)

-- trend-conflict detector OFF: flip the switch back
UPDATE pl_algorithm_config SET value = '0'
WHERE parameter_name = 'wrapper_use_trend_conflict'
  AND algorithm_version_id = (SELECT id FROM pl_algorithm_version WHERE name = 'ensemble_v1_softgate_wrapper');
```

The next `cc-ensemble-compute` run (19:18 UTC) reflects the change. A full rollback of all three is the migration
`downgrade()` (drops the two compass keys, resets `wrapper_use_trend_conflict=0`, drops the audit column) — but
prefer the config flips above for live ops; reserve the downgrade for removing the column.

## Watch-list (regime-MONITOR is the one to watch)

regime-MONITOR is the only **un-validated-out-of-sample** lever. Monitor forward:
- Count of `regime_monitor_fired = True` rows per month (it will spike in volatile months).
- Whether it mutes **correct** directional calls (compare `decision_wrapped` vs realized J+4 on fired rows).
- If it bleeds in a sustained high-vol *trend* (e.g. a 2024-style melt-up where committing is right), raise the
  threshold or disable. The score-grid EV break-even is ~81% dir-accuracy; if a regime sustains accuracy above that,
  the lever is net-negative there.

## Research provenance

`backend/scripts/research/` (non-production): `wrapper_levers_decade_backtest.py` (the recency-weighted selectivity
judge that rejected COT/OI/IV predictive levers), `resimulate_may_to_now.py` (the May→now stacked re-simulation),
`p0_macro_gate_retune.py` (the alpha_macro in-project retune proof), `robustness_fixes_backtest.py` (FIX2 vs the
dropped NaN-inversion). See [SOFTGATE_MACRO_GATE_RETUNE_SPEC.md](../research/SOFTGATE_MACRO_GATE_RETUNE_SPEC.md).

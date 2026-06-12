# Ensemble v1.0.1 — R&D Retrain Brief

> **Direction:** Compass (prod) → R&D. The reverse of the v1.0.0 flow: R&D delivered the frozen pack to prod
> ([CAMPAIGN_5_PROD_DEPLOYMENT.md](../archive/onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md), [HEDI_DATA_MAP.md](../archive/onboarding/HEDI_DATA_MAP.md));
> this is the **production feedback + retrain spec** for v1.0.1.
> **Date:** 2026-06-12. **Owner ask:** R&D produces a new frozen pack passing `tools/verify_delivery.py`; prod ingests it as `ensemble_v1_softgate_wrapper` **v1.0.1**.
> **Backup specs (read these):** [SOFTGATE_MACRO_GATE_RETUNE_SPEC.md](../research/SOFTGATE_MACRO_GATE_RETUNE_SPEC.md) · [IV_HISTORY_SOURCING.md](../research/IV_HISTORY_SOURCING.md).

---

## 0 — TL;DR

v1.0.0 specialists are **frozen at `training_month=2026-04`** (the monthly retrain job `cc-ensemble-monthly-retrain` is built but not scheduled). They never saw the **May-2026 high-vol regime** that broke accuracy (Jan 100% → May 58%). v1.0.1 asks for:

1. **Retrain the 14 specialists** on an extended window that **includes May + June 2026** (and ideally the 2024 super-spike + 2025 reversal in the stratified validation).
2. **Retune the soft-gate macro gate** — cap `alpha_macro < 1.0` + a **vol-stratified** objective (full spec in [SOFTGATE_MACRO_GATE_RETUNE_SPEC.md](../research/SOFTGATE_MACRO_GATE_RETUNE_SPEC.md)).
3. Optionally **wire implied-volatility features** (scraped since 2025-01-28, currently consumed by **zero** specialists — free alpha).
4. Ship a frozen pack via the **same delivery contract** (38 artifacts, manifest + SHA-256, `verify_delivery.py` green), `training_month` bumped to the retrain month.

**Do NOT** (refuted in production this session — don't spend R&D cycles): a 15th "reversal" specialist; a COT-positioning reversal veto; a realized-vol IV proxy. See §5.

---

## 1 — Why v1.0.1 (production learnings)

May-2026 collapse, root-caused against synced prod data:

- **The short-covering reversal is NOT forecastable** from owned data. We tested (and refuted, on a decade with a recency-weighted judge) a dedicated reversal specialist, COT-positioning vetoes, OI/volume flow signals. The ones that "looked great on May" were coincidences (no edge over 10 years). Honest target ≠ "predict the reversal" — it's "don't bleed + step back when out-of-distribution".
- **The soft-gate macro gate is the structural amplifier.** `alpha_macro=1.477` (>1) means a specialist voting against `macro_direction` gets weight `(1−1.477)→clamped 0` = **excluded**. On 2026-05-15 the (weak, news-volume) macro signal flipped bearish and **mechanically forced unanimous HEDGE (`net_score=−1.000`) for 9 sessions through the +20% rebound**. The 14 trend-followers weren't "all wrong" — the contrarians were erased before the vote.
- **The macro gate is a robustness fix, not an accuracy cure.** In-project re-run (real vendor `SoftGateOrchestrator`, our votes): capping `alpha_macro` to 0.9 dissolves the unanimity (47.9%→1.7% of days at |net|>0.99) but barely moves May accuracy — the specialists were genuinely bearish. ⟹ v1.0.1's accuracy lift must come from the **retrain on the new regime**, not the gate cap alone.

---

## 2 — What changed on the PROD side since v1.0.0 (new consumption contract)

R&D must know these — they affect how your artifacts are consumed:

- **Wrapper config is now config-as-data.** Prod loads `WrapperConfig` from `pl_algorithm_config` (`wrapper_*` rows), **overriding the frozen `tpw_v1` artifact** (`load_wrapper_config`). So the wrapper-detector switches/thresholds you ship in the artifact are **defaults**, not authority. Three Compass levers are now **live** (PR #43, migration `e7f8a9b0c1d2`):
  - `wrapper_use_trend_conflict = 1` (detector B re-enabled — was off in v1.0.0).
  - `compass_regime_monitor_atr_pctl = 0.80` (override commit→MONITOR in top-vol regimes; prod-side, NOT in your pack).
  - `compass_softgate_alpha_macro_cap = 0.9` (caps `alpha_macro` post-load).
- **New audit column** `pl_orchestrator_decision.regime_monitor_fired`. Published `pl_indicator_daily.decision` = regime-adjusted final; `decision_wrapped` stays = wrapper output.
- **Diagnostics fixed**: `fired_trend`/`fired_three_way` now read the real wrapper state (were hardcoded `False`); `macro_half_life_days` now computed.

**Implication for your `soft_gate_config` / `wrapper_config` artifacts:** ship them at the values you want as *defaults*, but expect prod to drive the wrapper via `pl_algorithm_config`. If the v1.0.1 macro-gate retune lands a new `alpha_macro`, **set it in the `soft_gate_config` artifact** (prod does NOT yet override soft-gate config from `pl_algorithm_config` except the `alpha_macro` cap) — coordinate the value with prod so the cap doesn't double-apply.

---

## 3 — Data delta to train on

Everything is in prod Cloud SQL (synced); pull via the bastion or request a fresh `extract_rd_dataset.py` snapshot.

| Source | v1.0.0 had | v1.0.1 must include | Note |
|---|---|---|---|
| `v_contract_data_chained` (OHLCV+IV, front-month chain) | → 2026-04 | **→ latest (incl. May+June high-vol)** | the regime that broke v1.0.0 |
| `pl_derived_indicators` (27 indicators) | → 2026-04 | → latest | same join |
| `pl_cot_eu_weekly` (Managed Money decomp) | partial | full → latest | keep as a specialist *feature*; do NOT build a reversal veto on it (refuted) |
| `pl_external_indicator` (ENSO + FX) | → 2026-04 | → latest | |
| `pl_article_segment` (sentiment → MacroEventLayer) | → 2026-04 | → latest | the macro signal is weak (`surprise` = article-COUNT z, not magnitude) — see §4.C |
| **`implied_volatility`** (in `pl_contract_data_daily` / chained) | scraped, **wired into 0 specialists** | **consider wiring** (§4.D) | only ~1.4y history (since 2025-01-28) — depth caveat |

**Validation-window coverage (the regimes that matter):** the 2024 cocoa super-spike (close 3381→9835), the 2025 reversal (9148→3783-ish), and **May-2026** (+30%/−16% intra-month). These are the stratification targets in §5.

---

## 4 — The asks for v1.0.1 (ranked)

**A. Retrain the 14 specialists on the extended window (incl. May+June 2026).** The `ensemble.retrain.monthly_retrainer` logic exists; this is a manual retrain producing new `specialist_model` + `specialist_hp` artifacts at the new `training_month`. Keep the **2-cluster / panel structure** (Winter/Spring, the panels in [HEDI_DATA_MAP.md §1](../archive/onboarding/HEDI_DATA_MAP.md) §1) unless the validation says otherwise.

**B. Soft-gate macro-gate retune** — the highest-leverage structural change. Full spec in [SOFTGATE_MACRO_GATE_RETUNE_SPEC.md](../research/SOFTGATE_MACRO_GATE_RETUNE_SPEC.md). In short:
- **Architectural guardrail: cap `alpha_macro < 1.0`** so a contrarian specialist is down-weighted `(1+α·(−1))>0`, never zeroed. (Prod already enforces a 0.9 cap as a stopgap — bake the right value into `soft_gate_config` and we'll align the cap.)
- **Vol-stratified Optuna objective**: evaluate on a walk-forward / holdout that includes the 2024 spike + 2025 reversal + May-2026; add a **decision-collapse penalty** (share of sessions at `|net_score|=1.0`) so the optimizer can't buy calm-regime accuracy by over-coupling to macro.

**C. Re-examine `alpha_anomaly` sign (= +0.7219, positive).** AV-001 found higher anomaly z ↔ higher accuracy on the *training* regime, so anomaly amplifies consensus — which amplifies a *wrong* unanimous consensus in a regime break. Validate the sign on the high-vol holdout. Also reconsider the **macro feature quality** itself: `surprise` is a news-*volume* z-score, not conviction — either improve it (sentiment magnitude / positioning-aware) or lower its ceiling weight; don't put the biggest multiplier on the weakest signal.

**D. (Optional, high-value) Wire implied-volatility features.** IV is scraped daily but consumed by zero specialists. The "IV-crush" pattern is the one reversal signal that flipped sign in our 2025-26 test (but is data-starved at ~1.4y). If you wire `iv_zscore_60d` / `iv_term_slope` / `iv_chg5`, prod is sourcing a multi-year history to validate it ([IV_HISTORY_SOURCING.md](../research/IV_HISTORY_SOURCING.md)) — coordinate so the feature and the data land together.

**E. Wrapper config (`tpw_v1` artifact).** Prod now drives the wrapper via `pl_algorithm_config`. Either (i) ship `tpw_v1` aligned with the live prod values (notably `use_trend_conflict=true`), or (ii) explicitly hand wrapper tuning to prod and ship a minimal/neutral `wrapper_config`. State which in the delivery notes so we don't diverge.

---

## 5 — Explicitly OUT of scope (refuted in production — do not pursue)

- **A 15th "reversal" specialist.** Architecturally muted: `_base_weight` caps at `[0,2]` (`soft_gate.py`) and the wrapper codomain is `{soft-gate decision, MONITOR}` (`transition_wrapper.py:308`) — a rare contrarian vote can never flip a commit. And untrainable: only **12 wrong-commit events** exist in the whole backfill (< ~30 needed).
- **A COT-positioning reversal veto.** Decade test: COT EU managed-money z has **no coherent forward-directional edge** (non-monotonic, ±0.5%/4d noise) and a weekly+3d lag. Keep COT as a *feature*; don't build a *veto* on it.
- **A realized-vol IV proxy.** Sign-fidelity vs true IV = 50.7% (coin flip). Not a substitute for option IV.

(Provenance: `backend/scripts/research/` — `wrapper_levers_decade_backtest.py`, `historical_conditioning_coherence.py`, `zero_cost_ivproxy_coherence.py`, `p0_macro_gate_retune.py`.)

---

## 6 — Acceptance / validation protocol (binding gates for v1.0.1)

1. **Vol-stratified walk-forward** across 2024 spike + 2025 reversal + May-2026.
2. **Commit-accuracy stratified by ATR%-percentile bucket** (NOT pooled) — report before/after per bucket.
3. **Decision-collapse metric**: share of sessions at `|net_score|=1.0` and near-zero committed-specialist dispersion — must drop materially vs v1.0.0.
4. **EV sanity**: the score-grid break-even is ~81% directional accuracy (a wrong call costs ~2× a right one). Don't ship a config that commits in regimes below it — that's what prod's regime-MONITOR lever is for, but the gate shouldn't manufacture false conviction there.
5. **Acceptance**: no unanimous-collapse stretches; the high-vol ATR buckets' commit-accuracy improves **without regressing the calm buckets** (no repeat of the calm-regime over-fit).

---

## 7 — Delivery contract (what R&D ships back — same as v1.0.0)

A `frozen/` directory + `manifest.json`, passing **`tools/verify_delivery.py` (6 gates, exit 0)**:

| Gate | Requirement |
|---|---|
| 1 | `manifest.json` present + valid JSON |
| 2 | every artifact file present on disk |
| 3 | every file's SHA-256 matches the manifest |
| 4 | inventory complete — **38 artifacts**: 14 `specialist_model` + 14 `specialist_hp` + `soft_gate_config` + `wrapper_config` + `long_run_anomaly`/`long_run_priors`/`long_run_regime_clusters` + 5 `canonical_snapshot` |
| 5 | `ensemble` package imports clean |
| 6 | `EnsemblePipeline.from_loader(FrozenDirLoader(frozen_dir), training_month=<new>)` reconstructs |

Each artifact carries provenance (`sha256`, `n_bytes`, `fit_train_start`, `fit_train_end`, `n_train`, `class_balance`, `git_sha`, `python_version`, `lib_versions`) — these flow into `pl_model_artifact`. **Bump `training_month`** (e.g. `2026-04` → `2026-06`); the long-run + canonical artifacts may stay as-is if unchanged (note it in the manifest).

---

## 8 — How PROD ingests v1.0.1 (our side — for coordination)

1. **New `pl_algorithm_version` row** `ensemble_v1_softgate_wrapper` **v1.0.1** (via Alembic migration, merged to `main` per `migrations-prod-via-main-only`).
2. **Seed the v1.0.1 config rows** (clusters + wrapper_* + the 3 Compass levers + soft-gate params incl. the new `alpha_macro`).
3. **Bootstrap the 38 artifacts** into `pl_model_artifact` via `cc-ensemble-bootstrap-artifacts` (re-run for v1.0.1).
4. **`_latest_training_month`** auto-selects the new month → `cc-ensemble-compute` uses the v1.0.1 specialists.
5. **Shadow-validate** on the backfill (prod can re-run `ensemble-compute --historical` across the validation window), then **atomic flip** v1.0.0 → v1.0.1 (the activation procedure in [CAMPAIGN_5_PROD_DEPLOYMENT.md §8.1](../archive/onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md)).

---

## 9 — Open decisions (the handshake)

1. **Retrain window length** — rolling 12/24m as v1.0.0, or extend to capture the full 2024-26 vol cycle? (Trade-off: regime coverage vs staleness.)
2. **`alpha_macro` final value** — R&D sets it in `soft_gate_config`; prod aligns the cap. Agree one number to avoid double-capping.
3. **IV features in v1.0.1 or v1.1.0?** — depends on whether prod has the multi-year IV history sourced by retrain time.
4. **Schedule the monthly retrain job** (`cc-ensemble-monthly-retrain`) as part of v1.0.1, or keep manual? (Frozen specialists can't adapt to regime shifts — this is the recurring version of the May problem.)

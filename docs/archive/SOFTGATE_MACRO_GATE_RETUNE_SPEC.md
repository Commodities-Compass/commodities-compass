# Soft-Gate Macro-Gate Retune — R&D Spec

> **Owner ask:** R&D (Campaign 5 soft-gate tuning driver). **Date:** 2026-06-12.
> **Status:** diagnosis validated against synced prod data (Dec-2025 → Jun-2026). This is a tuning/guardrail
> change to the soft-gate, NOT a wrapper hack and NOT a new model. It is the highest-leverage structural lever
> behind the May-2026 accuracy collapse.

## TL;DR

`alpha_macro = 1.477` (Optuna-tuned, frozen on the 2026-04 window) makes the macro signal a **hard gate**, not a
soft nudge: because α > 1, any specialist voting against `macro_direction` gets weight `(1 − 1.477) → clamped to 0`
and is **excluded**. In May this mechanically produced **unanimous HEDGE (`net_score = −1.000`)** for 9 consecutive
sessions through a +20% short-covering rebound. Two asks: (1) an **architectural guardrail** `alpha_macro < 1.0`
(no specialist ever fully zeroed), independent of any retune; (2) a **volatility-stratified tuning objective** so
the macro coupling isn't optimized purely on the calm/trending Q1 regime.

## The failure mechanism (evidence)

Soft-gate weight (`soft_gate.py:229`):
```
weight_i = base_acc_i · (1 + α_macro·macro_align_i) · (1 + α_prior·prior_align_i) · anomaly_term ; weight = max(0, weight)
```
With `α_macro = 1.477` and `macro_align_i = −1` (specialist votes against macro direction): `(1 − 1.477) = −0.477`
→ `max(0, ·) = 0`. The specialist is silently dropped from `net_score = Σ(w·vote)/Σw`.

Prod data, ensemble row of `pl_orchestrator_decision`, CAN26 (synced 2026-06-12):

| window | `macro_direction` | `net_score` | outcome |
|---|---|---|---|
| 05-05 → 05-14 (rally) | **+1** | +1.000 (unanimous OPEN) | mostly correct |
| **05-15 → 05-27 (rebound)** | **−1** (flipped) | **−1.000 (unanimous HEDGE), 9 sessions** | **7 of the month's PAS-BON** |

The macro layer flipped bearish on 05-15 (news sentiment lags price) and, via the α>1 gate, **muted every bullish
specialist** straight through the rebound. The 14 trend-following specialists were not "all wrong" — the
contrarians were *erased* before the vote. The wrapper could only dampen to MONITOR and was blind (running_acc NULL,
dispersion fired once), so nothing caught it.

Aggravating factor: the macro signal itself is weak. `MacroEventLayer.surprise` is the z-score of daily **article
COUNT** vs a 30d baseline (news *volume*), not sentiment magnitude; `direction = sign(confidence-weighted mean
sentiment)`. A short-covering squeeze is a *positioning* event, not a news-volume event — yet this thin signal
carries the largest multiplier in the gate.

## Root cause

`alpha_macro` was tuned by the soft-gate Optuna driver on the **frozen 2026-04 window** (Jan–Apr: low-vol,
trending). On that regime, leaning hard on macro alignment looks free (macro and trend agreed). The objective had
no high-volatility / reversal holdout, so it selected a macro coupling that is **catastrophic out-of-regime**. The
monotonic accuracy decay (Jan 100% → May 58%) tracks rising volatility, not a data bug.

## Asks for R&D

1. **Architectural guardrail (ship regardless of retune): cap `alpha_macro` (and `alpha_prior`) at `< 1.0`.**
   This keeps `(1 + α·align) > 0` for `align = −1`, so a contrarian specialist is *down-weighted* but never
   *zeroed*. Cheapest possible structural fix; removes the "unanimous −1.000 collapse" failure mode entirely.
   Consider exposing the cap as a `pl_algorithm_config` bound.

2. **Volatility-stratified tuning objective.** The soft-gate Optuna driver must evaluate candidates on a
   vol-stratified walk-forward (or an explicit high-vol holdout that includes the 2024 super-spike, the 2025
   reversal, and May-2026). Add an objective penalty for **decision-distribution collapse** (e.g. share of
   sessions at `|net_score| = 1.0`, or near-zero committed-specialist dispersion) so the optimizer cannot buy
   calm-regime accuracy by over-coupling to macro.

3. **Reconsider macro feature quality before weighting it.** `surprise` = article-count z is a volume proxy, not a
   conviction signal. Either improve the macro feature (sentiment magnitude, positioning-aware inputs) or lower its
   ceiling weight until it's worth trusting. Don't put the biggest multiplier on the weakest signal.

4. **Re-examine `alpha_anomaly = 0.722` (positive sign).** AV-001 found higher anomaly z ↔ higher accuracy on the
   training regime, so anomaly *amplifies* consensus. In a regime break that amplifies a *wrong* unanimous
   consensus. Validate the sign on the high-vol holdout.

## Validation protocol

- Walk-forward across **2024 spike + 2025 reversal + May-2026** with the stratified objective.
- Report commit-accuracy **stratified by ATR%-percentile bucket** (not just pooled), plus the decision-distribution
  collapse metric, before/after.
- Acceptance: no unanimous-collapse stretches; high-vol-bucket commit-accuracy improved without degrading the
  low-vol buckets (the calm months must not regress).

## Explicitly OUT of scope (already falsified — do not pursue)

- **A 15th "reversal" specialist** — architecturally muted: `_base_weight` caps at `[0, 2]` (`soft_gate.py:160`)
  and the wrapper codomain is `{soft-gate decision, MONITOR}` (`transition_wrapper.py:308`); a rare contrarian
  vote can never flip a commit.
- **A learned meta-label veto** — only **12 wrong-commits / 59 committed** exist in the whole backfill; far below
  the ~30+ needed to train. Conditioning rules beat a learned model here.
- **A COT-positioning-based reversal veto** — decade test (`scripts/research/historical_conditioning_coherence.py`)
  shows COT EU managed-money z has **no coherent forward-directional edge** (non-monotonic, ±0.5%/4d noise) and a
  weekly+3d lag. Not a timing lever.
- **An IV-crush conditioning veto** — only signal that flipped sign in 2025-26, but IV history starts 2025-01-28
  (n=9). Promising but unvalidatable until a multi-year IV history is sourced (see the IV-sourcing memo:
  Databento IFEU.IMPACT `C` options + Black-76, 2018+).

## Companion artifacts (this investigation)

- `scripts/research/wrapper_conditioning_backtest.py` — the vol×COT×IV-crush veto (looked good on May, **overfit**).
- `scripts/research/historical_conditioning_coherence.py` — the decade test that **refuted** the COT lever.
- `scripts/research/robustness_fixes_backtest.py` — wrapper robustness fixes (trend-detector re-enable = +1.69 on
  6mo and helps calm too; NaN-inversion = marginal and hurts calm — drop it).

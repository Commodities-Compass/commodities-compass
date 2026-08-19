# Pipeline REGIME + JUDGE (Campaign 6)

> **Status: SERVED, since 2026-08-19.** `pl_algorithm_version.serving_rank = 1`
> for `regime`. This is the only track that decides what a client sees.

LEGACY and ENSEMBLE were retired the same day — schedulers destroyed, code
deleted (−28 617 lines). Their documentation is in
[docs/archive/pipelines/](../archive/pipelines/), written in a present tense that
no longer applies; their tables keep every row.

> ⚠️ **There is no rollback.** Reverting `serving_rank` still executes, but
> ensemble stopped writing on 2026-08-18: it would serve data frozen at that
> date. Its Cloud Run jobs were deleted on 2026-08-19, so going back means
> rebuilding from `git checkout b73005c` — see
> [docs/archive/pipelines/](../archive/pipelines/#how-to-replay-one-of-them-now).

---

## 1. What the track is

Three layers, one nightly job for the first three:

| Layer | What it does | Writes |
|---|---|---|
| **L1 — regime router** | Classifies the session's market regime from trailing trend / vol / RSI. Causal, no lookahead. | — |
| **L2 — condition specialist** | One frozen model per regime, predicts the sign of the next session. | `pl_regime_shadow` |
| **L3 — judge** | LLM macro overlay. Reads press + weather, compares the drift to the technical call, and may confirm / abstain / flip. | `pl_judge_shadow` |
| **projection** | Fuses L2+L3 into the shape the dashboard reads. | `pl_indicator_daily` (regime version) |

**Horizon: J+1.** The regime specialists predict the next trading session. This
differs from the ensemble (J+4-J+5) and it propagates: the brief's "decision
horizon" line, the podcast prompts, and — since it is the number a client reads —
**the scoring itself**.

`eval_horizon_for(algorithm_name)` (`app/services/dashboard_service.py`) maps an
algorithm to the horizon it is scored on: 1 for `regime`, 4 everywhere else. The
YTD headline, the brief's YTD line and the recent-hit-rate tile all go through
it, so the figure and the label above it describe the same thing. Before this,
`YTD_EVAL_HORIZON_DAYS = 4` — tuned on ensemble v1.0.0 — was applied to every
algorithm, which would have printed a four-session score directly under
"Horizon de décision : prochaine séance".

> The judge has **no horizon of its own** — it judges the call it is handed, so
> it inherits regime's. The `J+4` string in `vendor/judge_v0.1/judge/scoring.py`
> is a leftover from when the judge sat above the ensemble; it is a docstring,
> not behaviour.

## 2. Nightly sequence

```
19:15  cc-compute-indicators --stage all
         → pl_derived_indicators           (per contract)
         → pl_indicator_daily              (per compute-enabled power-formula version)
         → pl_dashboard_gauge              (ALGORITHM-INDEPENDENT — see §4)

19:50  cc-regime-shadow                    (one job, three steps, one transaction each)
         1. regime  → pl_regime_shadow
         2. judge   → pl_judge_shadow
         3. adapter → pl_indicator_daily   (decision / confidence / direction, fr + en)

19:55  cc-regime-brief --language both
         per language: read → narrate → persist → render → upload
         → pl_indicator_daily.{conclusion, eco, confidence_rationale}
         → Drive: YYYYMMDD-CompassBrief-Regime{,-EN}.txt
```

## 3. The serving chain — how anything gets served at all

`pl_algorithm_version` now carries four columns with one job each:

| Column | Layer | Meaning |
|---|---|---|
| `algorithm_kind` | schema | which engine can execute this version (`power_formula`, `ml_ensemble`, `ml_regime`, `llm_overlay`) |
| `compute_enabled` | compute | run this power-formula variant nightly |
| `is_active` | compute | the singleton "current" power-formula version |
| `serving_rank` | **serving** | dashboard preference order. NULL = never served |

Before this, the served algorithm was decided by hardcoded constants in Python,
in four separate places, while `is_active` — which looked like the switch — was
read by the *compute* engine. Flipping it would not have changed what users see,
and would have broken `cc-compute-indicators`.

**The rank designates a NAME, not a row.** Within a name, resolution picks the
newest version that has a row for the date — that is what lets a
go-forward-only version serve recent dates while its predecessor keeps the
historical ones. At most one row per name may be ranked (partial unique
indexes).

Everything reads the chain through `app/utils/serving_chain.py`: the date
resolver, the YTD series, the intraday alert's message context, and the
services' default algorithm.

### Flipping (and unflipping)

```sql
-- the only collision-free order: vacate, assign, re-rank
UPDATE pl_algorithm_version SET serving_rank = NULL WHERE name = 'ensemble_v1_softgate_wrapper';
UPDATE pl_algorithm_version SET serving_rank = 1    WHERE name = 'regime';
UPDATE pl_algorithm_version SET serving_rank = 2    WHERE name = 'ensemble_v1_softgate_wrapper';
```

Effective within 5 minutes (resolver cache TTL). No deploy. The reverse UPDATE
is the rollback — and it only works while ensemble is still *writing* rows, which
is why the ensemble jobs must stay scheduled through the stability window.

## 4. Gauges are not part of any algorithm

The five technical gauges (RSI / MACD / %K / ATR / VOL-OI) used to be read from
`pl_indicator_daily.*_norm` — i.e. from whichever algorithm wrote that row. They
would have vanished the moment that algorithm stopped writing.

They now live in `pl_dashboard_gauge`, filled by the gauge stage of
`cc-compute-indicators`, which reads no algorithm table. Three stages are stored:

```
raw_value    ← pl_derived_indicators (rsi_14d, macd, stochastic_k_14, …)
score_value  ← 5-day SMA                (app/engine/smoothing.py)
norm_value   ← rolling 252d z-score ±10 (app/engine/normalization.py)  ← what the gauge plots
```

The stage reuses the engine's own functions rather than reimplementing them —
a second implementation would be free to drift, and the drift would be
invisible: the numbers stay plausible, they just stop matching the `test_range`
calibration and the colours shift.

No colour zone is stored. `test_range` is mutable config; freezing a zone at
write time would pin a stale calibration and force a backfill on every retune.

> ⚠️ **Known: `test_range` has never been recalibrated** since the Sheets →
> engine migration. Measured on 2026 production data, the plotted value sits
> outside its own scale 79-93 % of the time (RSI 18.5 % in range, MACD 6.8 %).
> The frontend clamps the marker to the nearest edge and colours it accordingly,
> so nothing breaks — but the marker position carries little information.
> Recalibrating is a pure `UPDATE test_range`, decided separately.

## 5. No cross-algorithm fallback, anywhere

From this track on, the pipeline behaves as though no other algorithm exists.
Four fallbacks were removed:

| Where | Was | Now |
|---|---|---|
| `get_latest_recommendations` | 4-step cascade relaxing contract **then algorithm** | one read: served algo + contract + language, else empty |
| `_fetch_algo_base_call` (judge window) | `WHERE name = 'ensemble_v1_softgate_wrapper'`, silent `(MONITOR, 0.0, "")` on miss | scoped to the algorithm being overlaid, `PriorBaseCallMissingError` on miss |
| `_decision_aware_front_month_series` | `COALESCE(ensemble, legacy)` on two pinned ids | `LEFT JOIN LATERAL` over the serving chain |
| `compute_ytd_score` (brief) | `COALESCE(ensemble, legacy)` hardcoded | scoped to one algorithm |

The judge one mattered most: it fed the LLM *a fabricated history* — "the
algorithm was neutral that day" for a day the algorithm never spoke. An invented
past is worse than a failed run.

**Operational consequence.** The judge's window needs J-1 and J-2 decisions from
its own algorithm. Backfill the adapter rows over regime's existing shadow
sessions before the flip, or the first run after it fails loudly.

## 6. The conviction panel — `/judge-diagnostics`

The "Conviction" row of the commercial matrix is sold on **6 of the 7 tiers**
(all but Coop Essentiel). It was backed by `/ensemble-diagnostics` +
`/specialist-votes`, both ensemble-specific. Deleting them without a replacement
would remove a billed capability from almost the whole catalogue — silently, as
a 403.

`GET /v1/dashboard/judge-diagnostics` is that replacement. Same row, different
machinery: where the ensemble reported a vote count over 14 specialists, this
reports the routed regime, the model's probability, and what the overlay did
with the call. Gated by `read:feature:judge_overlay`, which joins `_CONVICTION`
alongside the two ensemble keys — so the six tiers keep the row across the flip
with no template edit. Migration `s4j5u6d7g8e9` grants it to every account that
already holds the ensemble key (append-only INSERT; the ensemble keys are left
alone, they are the rollback path).

It 404s unless the **served** algorithm is `regime`, so it stays silent for the
entire shadow period even though regime writes rows every night — a conviction
panel describing a decision nobody is shown would contradict the signal on
screen. `SignalHero` renders whichever breakdown matches `source_algorithm`;
both are hidden when neither does.

**`rationale` is not in the payload.** A test asserts it is absent from the whole
serialised response, not merely as a missing key — a future refactor could just
as easily leak it inside `evidence` or a concatenated summary.

## 7. The brief

`cc-regime-brief` merges what would otherwise be two jobs (an explainer writing
the narrative, a generator rendering the file). The prose is written **once per
language** and lands both in the `.txt` and on the served row, so the dashboard
and the audio cannot disagree.

**Native per language, not translated.** The judge writes its working notes in
English; each language's call composes from them in its own voice.

What crosses into the prompt: `drift_summary`, `key_risk`,
`disconfirming_case`, `evidence`.
What does not: **`rationale`** — the deterministic trace of `policy.fuse`
("ABSTAIN HEDGE->MONITOR: judge contradicts at conf=3"). It is audit material
for the judge's own replay. It never reaches the brief and is never served.

The brief is **the whole of Compass**, not the algorithm's call: six sections
(signal, guaranteed farmgate price, editorial read, eco & press, weather,
technical snapshot, operational recommendations). Only **section II — editorial
read** is track-specific; it names the market regime and how the macro read
arbitrated, in business language. Everything else is shared with the other
tracks through `scripts/_shared/brief_common.py`.

Two guards refuse to publish rather than degrade: a narrative naming the
machinery, and a partial narrative.

Podcast prompts: [notebooklm-podcast-prompt-regime.md](../operations/notebooklm-podcast-prompt-regime.md)
(FR) and [-regime-en.md](../operations/notebooklm-podcast-prompt-regime-en.md).
A contract test asserts every anchor the prompt navigates exists in the rendered
brief — rename a header on one side and NotebookLM silently skips that part of
the podcast, with no error anywhere.

## 8. Files

```
app/utils/serving_chain.py              the chain: get_serving_chain, resolve_serving_version
app/engine/gauges.py                    gauge stage (3 stages + upsert)
app/engine/runner.py                    --stage all|indicators|gauges
scripts/regime_shadow/                  L1+L2, judge orchestration, indicator_adapter.py
scripts/judge_shadow/                   L3 (brief_builder, runner, llm_openai)
scripts/regime_brief/                   config, db_reader, narrator, db_writer, brief_generator, main
scripts/_shared/brief_common.py         press / weather / campaign / technicals / YTD — shared
app/services/judge_diagnostics_service.py   the conviction panel (regime + overlay)
frontend/src/utils/judge-explanation.ts     its business-language rendering
vendor/regime_v1.0.0/                   frozen R&D pack (read-only)
vendor/judge_v0.1/                      frozen R&D pack (read-only)
```

## 9. What is deliberately NOT done

- **regime has no `serving_rank`** — nothing is served. This is the flip.
- **`compute_enabled` / `is_active` untouched for regime and judge.** Setting
  `compute_enabled` on them would feed an ML/LLM version to the power-formula
  engine. `algorithm_kind` now makes that inert rather than fatal, but the flags
  stay FALSE.
- **The ensemble and legacy jobs still run.** They are the rollback path.
- **`production_score` is NULL on every shadow row** — the scoring pass has
  never run, so there is no measured quality on either layer yet.

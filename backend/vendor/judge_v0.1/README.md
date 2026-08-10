# `judge` — macro overlay v0.1 (Layer 3, shadow prototype)

> **What:** a third layer above the technical algorithms (`regime` / ensemble) that reads
> the daily Compass briefs (press review + weather + signal), detects **drift** versus the
> technical call, and — via a deterministic policy — **confirms, abstains (MONITOR), or
> flips** the decision. Built to fix the structural blind spot: the algorithms see no news,
> so a fundamentally-driven move (weather, crop, macro) is invisible to them.
> **Status:** prototype, **shadow only**. The judgment is an LLM read — **not reproducible,
> not backtestable** — validated forward, never on history.

## Why it exists — the 07-31 miss

On the 07-31 close, both `regime` (highvol specialist, P(up)=0.21) and the ensemble
committed a **bearish HEDGE at 2/5 conviction**. Cocoa then ran **+9.75%** into 08-03.
Pure-technical mean-reversion fought a supply-driven continuation it couldn't see.

The press review *did* carry the signal, in time and causally (built off the 07-31 close):
"traders should favor modest long strategies," "prices soaring amid ralentissement des
arrivées portuaires," firming Abidjan spot premiums. The macro picture **contradicted** the
technical HEDGE — and was right.

## What the overlay does on that case (replayable)

```
session      base     judge   final      base_score   overlay_score
2026-07-31   MONITOR   UP/2    MONITOR      +1.000        +1.000     (weak signal → keep)
2026-08-03   HEDGE     UP/3    MONITOR      -0.195        +1.000     ← the miss, rescued
2026-08-04   HEDGE     UP/4    OPEN         (forward)     (forward)  ← escalated drift → flip
```

The bearish HEDGE into +9.75% resolves to **MONITOR** (judge contradicts at conf 3, below
the flip bar) → score **−0.195 → +1.0**. As the bullish drift escalates on 08-04 (Ghana
output −16%, +6.8% NY repricing, conf 4) the overlay **flips to OPEN**.

## Architecture

```
last 2-3 Compass briefs ─▶ brief_parser ─▶ drift (deterministic) ─▶ prompt (versioned)
                                                                        │
                                              LLM judge (the only ▼ non-reproducible seam)
                                              {direction, confidence 1-5, evidence, drift…}
                                                                        │
                                    policy.fuse()  ◀── config thresholds │  (pure code)
                                                                        ▼
                                              final decision + full shadow log
```

Everything except the LLM call is deterministic and unit-tested. The judgment is
quarantined behind `JudgeLLM` (`GoldenJudgeLLM` for replay/CI, `AnthropicJudgeLLM` for the
live path — pinned model, temp 0, structured output).

## The policy (symmetric; knobs in `judge/config.py`)

| Base call | Judge vs base | Conf | → Final |
|---|---|---|---|
| any | agrees, or NONE, or conf ≤ 2 | — | keep base (≈90% of days) |
| OPEN / HEDGE | contradicts | ≥ 4 | **flip** (symmetric — can also open a fresh short) |
| OPEN / HEDGE | contradicts | = 3 | **MONITOR** (abstain) |
| MONITOR | clear direction | ≥ 4 | **commit** that direction |
| MONITOR | clear direction | = 3 | stay MONITOR |

Design choices, all Hedi-confirmed: **symmetric** override, **single** LLM draw, **skill**-first.
MONITOR fires on genuine **conflict**, not on quiet days — so commit-rate is preserved.
Flipping the machine's direction needs conf ≥ 4; abstaining needs only 3 (asymmetric bars,
because a wrong commit is unbounded −2×|move| while MONITOR is rewarded).

## Layout

```
judge/        schema · config · scoring · policy · brief_parser · drift · prompt · llm
              runner · integration (regime->judge->sink, PROD seams)
fixtures/     briefs/ (3 real Compass briefs) · golden_verdicts.json (recorded judgments)
tests/        policy · parser · scoring · regression · integration (36 tests, all green)
SKILL.md      how to invoke / judge by hand
```

## Full system — `regime` (shadow) -> `judge` -> shadow log

`regime` already runs in shadow, so the whole pipeline can be observed end-to-end with zero
prod risk. In the full system the base decision comes from **regime's live call**, not from
the brief's own SIGNAL block — the brief's press/weather content is algorithm-agnostic and
reused as-is. `judge/integration.py` is the seam; every point the product must implement is
tagged `# PROD:`.

```python
from judge.integration import run_shadow      # regime -> judge -> sink, one call/session
from judge.llm import AnthropicJudgeLLM

outcome = run_shadow(
    session_date="2026-08-03",
    regime_decision=regime_pipeline.decide(request),  # regime's shadow RegimeDecision
    store=brief_store,        # PROD: implements BriefStore.load_recent(session_date, n)
    llm=AnthropicJudgeLLM(),  # PROD: pinned model / temp 0 (or o4-mini to match press stack)
    sink=shadow_sink,         # PROD: implements ShadowSink.write(log_fields) -> shadow table
)
```

Three `# PROD:` seams, all Protocols (no hard dependency on the prod codebase):
- **`BriefStore.load_recent`** — return the last N briefs up to the session (parse stored
  text via `parse_brief`, or build `Brief` straight from the structured press/weather rows).
- **`AnthropicJudgeLLM`** — swap provider / enforce the JSON schema; pinned + temp 0.
- **`ShadowSink.write`** — persist `outcome.log_fields` to a shadow table (never
  `pl_indicator_daily.decision`). Regime provenance (`regime`, `specialist`, `prob_up`) is
  folded in for the pipeline analysis.

Verified on regime's real 07-31 call (HEDGE, P(up)=0.2133): overlay -> **MONITOR**, not the
losing HEDGE (`tests/test_integration.py`).

Run: `cd deliverables/judge_v0.1 && ../../.venv/bin/python -m pytest tests/ -q`

## Honest caveats (non-negotiable)

1. **Not reproducible / not backtestable.** LLM judgment drifts with the model; hindsight
   leakage makes any backtest dishonest. The prompt forbids outside price knowledge and
   forces ≥2 grounded quotes, but the *only* valid evaluation is **forward shadow**.
2. **n = 1.** The proof case shows the mechanism fires correctly; it is an anecdote, not a
   measured edge.
3. **It can chase.** The 08-04 flip to OPEN comes after a two-session +9.75% run — buying
   the top is a real failure mode. Shadow calibration is what tells us if the flips pay.

## Shadow-eval spec (go/no-go)

Log `outcome.log_fields` every session. Score both the base and the overlay under the
production rule. After **≥ 30 committed sessions**:

- **Intervention confusion matrix:** avoided-bad-commit (win) vs killed-good-commit (cost)
  vs flips-right vs flips-wrong. Keep the overlay only if wins + flips-right **beat** costs
  + flips-wrong in *score* terms.
- **Calibration curve:** judge confidence vs realized correctness → is "4" really the right
  flip bar? Retune `config.py`, not the prompt.

## Next (prod, in shadow)

The full-system entry point (`run_shadow`) and all three `# PROD:` seams are in place. To go
live in shadow:

1. Implement `BriefStore.load_recent` against the brief store, and `ShadowSink.write` against
   the shadow table.
2. Instantiate `AnthropicJudgeLLM` (or an o4-mini variant matching the press-review stack);
   pinned model, temp 0, ideally schema-enforced output.
3. Call `run_shadow(...)` once per session after regime's shadow decision + the day's brief
   exist. Runs alongside regime's shadow with zero user-facing effect.
4. After ≥30 committed sessions, run the go/no-go above. Until it clears, the overlay
   **advises** — it never controls the live decision.

Optional: feed the structured `theme_sentiments` numbers into `Brief`/`drift` to make the
drift signal fully deterministic (prose drift already works without it).

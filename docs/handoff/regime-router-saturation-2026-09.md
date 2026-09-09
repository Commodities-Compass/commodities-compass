# Handoff — Router saturation in `regime_v1.0.0`: 3 of 6 specialists are unreachable

> **Audience** : Campaign 6 R&D project (owns the freezer, the router config, the specialist HPs).
> **From** : Compass (frozen-artifact consumer — does NOT train).
> **Written** : 2026-09-09.
> **Status** : finding verified against the shipped artifact itself; **no Compass-side change made** to `vendor/regime_v1.0.0`.
> **Nature** : a **routing defect present at freeze time**, not drift. It is reproducible offline on the pack's own canonical snapshot, without any production data.

---

## 1. TL;DR — what we found and what we're asking for

`frozen/router/regime_router.json` gates the `highvol` specialist on an **absolute**
threshold:

```json
"atr_high_pctile": 0.67,
"atr_high_value": 48.6633
```

`atr_14d` is a Wilder ATR in **absolute price units (GBP/tonne)**, so it scales with
the price level. On the pack's own `frozen/canonical_snapshot/reference_tail_120.parquet`
— the last 120 days of the training window — ATR runs **min 98.72 / median 167.43 /
max 378.50**. The threshold is exceeded on **120/120 rows**.

Because `highvol` sits at **priority 3**, above `bull`/`bear`/`transition`, those three
specialists can never be selected. Replaying the shipped router on the shipped
snapshot:

| trend tag computed | | specialist actually selected | |
|---|---|---|---|
| transition | 49 % | **highvol** | **62 %** |
| bull | 28 % | oversold | 19 % |
| bear | 22 % | overbought | 19 % |
| | | **bull / bear / transition** | **0 / 120** |

`bull.pkl`, `bear.pkl` and `transition.pkl` are trained, frozen, shipped — and
structurally unreachable.

**Request**: your read on this, and — if you concur — a router config (or a re-freeze)
where the volatility gate is **scale-free**. We are not proposing the fix; §4 lists the
options we considered so you can reject them from a better-informed position.

---

## 2. Reproduction — offline, on your artifact, no prod access

```python
import pandas as pd, json, collections
df  = pd.read_parquet("frozen/canonical_snapshot/reference_tail_120.parquet")
cfg = json.load(open("frozen/router/regime_router.json"))

a, r = df["atr_14d"].astype(float), df["rsi_14d"].astype(float)
print("ATR  min/med/max :", a.min(), a.median(), a.max())
print("ATR > threshold  :", (a > cfg["atr_high_value"]).mean())   # -> 1.0

def spec(rsi, atr, regime):                      # mirrors regime/router.py priority
    if rsi < cfg["rsi_oversold"]:  return "oversold"
    if rsi > cfg["rsi_overbought"]: return "overbought"
    if atr > cfg["atr_high_value"]: return "highvol"
    return regime

sel = [spec(r.iloc[i], a.iloc[i], df["regime"].iloc[i]) for i in range(len(df))]
print(collections.Counter(sel))                  # bull/bear/transition -> 0
```

This is the whole finding. It needs neither the production database nor a rerun.

---

## 3. What it looks like in production

`pl_regime_shadow` + `pl_judge_shadow`, **28 sessions**, 2026-07-30 → 2026-09-08
(26 scorable after excluding one roll-contaminated day, see §6):

| specialist selected | n |
|---|---|
| `highvol` | 23 |
| `overbought` | 3 |
| `bull` / `bear` / `transition` / `oversold` | **0** |

Two consequences we can measure:

**a. The `regime` tag published to clients is decorative.** The dashboard tile and the
brief say "marché sans direction" / "tendance haussière" from the trend computation,
while the model that actually decided was `highvol` in 88 % of sessions. The label and
the decision are not connected.

**b. A directional bias consistent with a permanently-volatile specialist.**

| | |
|---|---|
| market | **58 %** up sessions (15/26) |
| regime calls | **38 %** bullish (10 OPEN / 16 HEDGE) |

16 HEDGE, of which **10 into rising sessions** — 29.9 points of % taken the wrong way
against 17.7 captured correctly. Directional hit-rate 42.3 % (11/26); HEDGE 38 %,
OPEN 50 %.

We are **not** claiming the router defect causes the whole bias — 26 sessions cannot
support that. We are saying the two are consistent, and that re-tuning a decision
threshold before fixing the routing would be tuning the wrong layer.

---

## 4. Options we considered (all rejected as *ours* to choose)

1. **Normalize the gate**: threshold `atr_14d / close` instead of `atr_14d`. Scale-free,
   minimal config change, but changes the meaning of `atr_high_pctile` and needs a
   re-derivation of the percentile on the training set.
2. **Rolling percentile**: `atr_14d > rolling_quantile(atr_14d, 252, 0.67)`. Also
   scale-free and adapts, but introduces a warm-up and a new stateful feature — a
   train/serve parity surface you own, not us.
3. **Re-order the priority** so `bull`/`bear` outrank `highvol`. Cheapest, but it
   changes the intended semantics ("most specific first") rather than fixing the gate.
4. **Leave it and drop the three models** from the pack. Honest, and arguably correct if
   `highvol` is genuinely the best single model for this market — but then the router,
   the trend tag and half the frozen payload should go with it.

Our instinct is (1) or (2); the choice depends on how the percentile was derived and on
what the specialists were actually trained to separate — both of which are yours.

---

## 5. Two adjacent findings, offered as context

Same 26-session window. Both are **under-powered** and we flag them as signals, not
conclusions.

**`prob_up` appears anti-calibrated.** Accuracy by bucket:

| P(up) | n | correct |
|---|---|---|
| < 0.42 | 8 | 38 % |
| 0.42–0.48 | 6 | 33 % |
| **0.48–0.52** | 3 | **67 %** |
| 0.52–0.58 | 5 | 60 % |
| > 0.58 | 4 | **25 %** |

The model is least right where it is most confident. If this survives a longer window it
matters beyond Compass: we surface `prob_up`-derived conviction to clients.

**Regime reads the market better than the noise.** Hit-rate 33 % on |move| < 0.5 %,
38 % on 0.5–2 %, **56 % on > 2 %**. Whatever it has learned, it is in the direction of
real moves, not chop.

---

## 6. Landmines — Compass-side context you may not have

1. **Regime self-computes its features in production.** It never reads
   `pl_derived_indicators`; `scripts/regime_shadow/feature_engine.py` rebuilds the
   9 passthrough indicators from the raw front-month chain with its own roll-boundary
   neutralization. If you change a feature definition, that is the file that must move
   in lockstep — the pack's `DERIVED_PASSTHROUGH` contract is honoured there, not in the
   shared engine.

2. **Roll splices inject phantom returns and we exclude them by hand.** On 2026-08-24
   the chained view took CAU26 (4253) then CAZ26 (4212), while CAZ26 itself closed 4298
   the same day: the "−0.96 %" is a contract spread, the real move was −2.00 %. Any
   scoring you run against `v_contract_data_chained` inherits this on ~6 sessions a year.

3. **Only one branch of the router has ever executed in production**, so nothing observed
   so far says anything about the other five specialists — including that they are bad.

4. **The judge (L3) reads the press review, and the press review had a hole.** On
   2026-08-26/28 cocoa rallied ~14.5 % on a StoneX surplus downgrade (149kt → 25kt) into
   a near-record fund short. Our press sources are origin-focused and carried none of it;
   the judge reasoned correctly on incomplete input and confirmed HEDGE into the rally.
   Fixed on our side (PR #142, source-level). Mentioned so you do not read those two
   sessions as a model failure — the model was not shown the driver.

5. **`production_score` and `realized_return` are NULL on every shadow row.** The
   scoring pass was never written. Every figure in this document was computed by hand
   from `pl_regime_shadow` / `pl_judge_shadow` joined to `v_contract_data_chained`, with
   the Compass `_score_day` formula. Independently reproducible, but not yet a job.

---

## 7. Out of scope for this handoff

- ❌ No request to retrain or re-tune the specialists. If the routing fix makes five of
  them reachable, evaluating them is a *later* question.
- ❌ No new `pl_algorithm_version`. A router-config change must ship as a re-freeze of
  `regime_v1.0.0` or a `1.0.1` that Compass pins explicitly — splitting the version
  splits the served history.
- ❌ No change to the judge overlay, its prompt, or its flip bar. Separate lane.
- ❌ No opinion from us on whether `highvol` is the right single model. We cannot know:
  we have never seen another one run.

---

## 8. What we need back

1. Do you concur that the gate is saturated by construction?
2. If yes — re-freeze with a scale-free gate, or a deliberate decision to keep one
   specialist and simplify the pack?
3. Either way: is `atr_high_pctile = 0.67` still the intended selectivity? At a correct
   scale it would put ~1 session in 3 on `highvol` instead of ~9 in 10.

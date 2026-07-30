# `regime` — algorithm v1.0.0 (shadow deliverable)

> **From:** Campaign 6 R&D · **To:** Compass (prod) · **Date:** 2026-07-29
> **Ship as:** a **new** `pl_algorithm_version` (`regime` / `1.0.0`), **INERT** (`is_active=FALSE`,
> `compute_enabled=FALSE`), computing in **shadow** next to the live ensemble. No user-facing change.
> **Contract:** same shape as the ensemble deliverable — `frozen/` payload + SHA-256 `manifest.json` +
> an importable package + a seed migration + verification gates.

---

## 1 — What it is

A **two-layer** algorithm:

- **Layer 1 — causal router** (`regime/router.py`). From *trailing* data only (trend / vol / RSI as of
  today's close, no look-ahead) it classifies the market state and resolves it to exactly one specialist
  via a fixed priority (`oversold → overbought → highvol → bull → bear → transition`).
- **Layer 2 — condition specialists** (6 frozen models). Each is trained on **every historical day**
  matching its condition (2016→cutoff), and predicts the **sign of the next trading day (J+1)**.
  `P(up) ≥ 0.5 → OPEN`, else `HEDGE`.

`RegimePipeline.decide(request)` is the single entry point; it mirrors the ensemble's `DecideRequest`
seam so Compass wires it the same way.

## 2 — ⚠️ Honest status: this is a **hypothesis under shadow test**, not a proven edge

The specialists fit 2026 strongly **in-sample**, but on **leakage-safe unseen days they revert to
≈ coin-flip.** The router is genuinely causal and correct; the open question is whether the specialists
have any *forward* edge. **That is exactly what shadow settles** — on live forward data, zero risk, weeks.
**Do not flip it live on the in-sample numbers.**

### Reference results — what a correct integration reproduces

**(a) In-sample 2026 fit** (scored J+1 with the production rule; benchmark, *not* forward):

| specialist | 2026 days | hit-rate | YTD |
|---|---|---|---|
| oversold | 36 | 0.917 | 107.3 |
| bull | 34 | 0.912 | 109.7 |
| overbought | 23 | 0.870 | 104.5 |
| bear | 40 | 0.850 | 99.1 |
| highvol | 141 | 0.837 | 98.7 |
| transition | 67 | 0.716 | 83.1 |
| **routed pipeline (all 2026 days)** | **141** | **0.858** | **101.2** |

Routed monthly hit: Jan 0.95 · Feb 0.86 · Mar 0.86 · Apr 0.80 · May 0.84 · Jun 0.86 · Jul 0.83.

**(b) Leakage-safe forward** (purged/embargoed CV — the honest expectation on *unseen* days):

| specialist | forward hit [95% CI] |
|---|---|
| transition | 0.507 [0.39, 0.62] |
| bull | 0.412 [0.26, 0.58] |
| highvol | 0.426 [0.35, 0.51] |
| oversold | 0.389 [0.25, 0.55] |
| bear | 0.350 [0.22, 0.50] |
| **routed** | **0.44 [0.36, 0.52]** |

**Interpretation for shadow:** live shadow hit-rate should land **somewhere between (b) ≈0.44 and (a) ≈0.86.**
Near **0.86** ⇒ the in-sample fit generalized (real edge, promote). Near **0.44–0.50** ⇒ it was memorization
(reject, pivot to downside-protection). The whole point of shadow is to find out which.

## 3 — Payload (`frozen/`, 14 artifacts) + `manifest.json`

| kind | n | contents |
|---|---|---|
| `regime_specialist_model` | 6 | `bull, bear, transition, highvol, oversold, overbought` (`.pkl`) |
| `regime_specialist_hp` | 6 | model params + feature list per specialist (`.json`) |
| `regime_router` | 1 | causal router thresholds incl. baked `atr_high_value` (`.json`) |
| `canonical_snapshot` | 1 | last-120 reference rows (train/serve parity check) |

Each manifest row carries `sha256`, `n_bytes`, `payload_encoding` + provenance (`fit_train_start/end`,
`n_train`, `class_balance`). Header: `algorithm_version_name="regime"`, `algorithm_version="1.0.0"`,
`git_sha`, `data_cutoff`, `lib_versions`.

## 4 — Reproduce / verify (R&D side)

```sh
DATA_CUTOFF=2026-07-27 python tools/freeze_regime.py     # rebuild frozen/ (deterministic, seed=42)
python tools/verify_regime.py                            # 4 gates: inventory · repro · imports · decide-smoke
```
`verify_regime.py` must exit 0 before delivery (re-freeze yields byte-identical specialist SHA-256s).

**Integration check — a correct build reproduces exactly:**
- `decide(2026-07-27)` → **OPEN**, `regime=transition`, `specialist=highvol`, `P(up)=0.533`.
- Specialist model SHA-256 (first 10): `bull f94e92fff1` · `bear e5bb2142f6` · `transition 608b2491a0` ·
  `highvol 643ca8bfcb` · `oversold 4d3db9a6a7` · `overbought e62896f16d`.
- Manifest header: `algorithm_version=1.0.0`, `data_cutoff=2026-07-27`, libs sklearn 1.6.1 / scipy 1.14.1 /
  lightgbm 4.5.0 / numpy 1.26.4 / pandas 2.2.3. (Outer tarball SHA-256 accompanies the delivery.)

## 5 — Compass integration (shadow)

1. `tar xzvf regime_v1.0.0_2026-07-27.tar.gz` into a **new** `vendor/regime_v1.0.0/` (read-only delivery).
2. `pip install -e vendor/regime_v1.0.0` (or vendor `regime/` per your engine layout). Deps in
   `pyproject.toml`; align `lib_versions` with `manifest.json` (`fit ≡ declared ≡ infer`).
3. Apply the seed: `psql "$DATABASE_URL" -f sql/001_seed_regime_algorithm.sql` — creates the **inert**
   version + router/specialist config. This IS an Alembic-worthy migration (new version row) → land via
   **merge to `main` → CI/CD** (`migrations-prod-via-main-only`).
4. Bootstrap the 6 specialist models + router into `pl_model_artifact` under the new version id (reuse the
   ensemble bootstrap loader; SHA-256 checked in/out).
5. Add a **shadow compute** step: each session, build a `DecideRequest` (front-month `market_history` with
   `date`, `daily_return`, the 9 passthrough derived indicators; ≥60 trailing rows) → `pipe.decide(...)` →
   write to `pl_orchestrator_decision` (or a shadow table) tagged with the `regime` version id. It never
   touches `pl_indicator_daily.decision`.

## 6 — Shadow-eval spec (the go/no-go)

**Log, per session:** `date`, `regime`, `specialist`, `decision`, `prob_up`, and — once the horizon
closes — the realized J+1 move and the production score (`+1.25/+1.0` correct, `−2×|move|` wrong).

**Run for ≥ 30 committed sessions** (respects the n≥30 floor). Then:

- **Promote** iff shadow **hit-rate CI lower bound > 0.50** *and* mean daily score beats the live
  ensemble's shadow score over the same window. (Directional edge, established forward — not in-sample.)
- **Reject** iff hit-rate ≤ 0.50 (CI includes it) — the in-sample fit did not generalize; archive and pivot
  to the downside-protection framing.
- **Rollback** is trivial: the version is inert, so "stop computing it" is the whole rollback. No data loss.

## 7 — What v1.0.0 deliberately excludes

No risk/abstention brake baked in (binary OPEN/HEDGE; MONITOR only as a fail-safe) — downstream gating, if
any, stays a Compass config-lane concern. No macro layer, no soft-gate. Finer sub-specialists and a learned
(probabilistic, hysteretic) router are v1.1 candidates **iff** shadow clears §6.

---
### References
- Contract & persistence model: `docs/plans/ensemble-specialist-retrain-handoff.md`
- Freezer: `tools/freeze_regime.py` · Verifier: `tools/verify_regime.py` · Entry point: `regime/pipeline.py`

# Handoff — Refresh (retrain) of the 14 C5 specialists `ensemble_v1_softgate_wrapper`

> **Audience** : Campaign 5 R&D project (owns the freezer + the HPs + the reproducibility suite).
> **From** : Compass (frozen-artifact consumer — does NOT train).
> **Written** : 2026-07-28. **Decisions integrated** (see §7).
> **Status (2026-07-28)** : ✅ Compass-side prep **DONE** — roll-contamination neutralization implemented + validated (feature branch), training DB **synced (through 2026-07-27) + corrected + flagged**. **R&D can start now** — see **§4** for exactly what you get and how to use it.
> **Nature** : a *refresh* (advance `TRAINING_CUTOFF`) on corrected data + modernized libs. **NOT** re-tuning, **NOT** a new architecture, **NOT** a new `pl_algorithm_version`. Phase 2 (retune / new campaign) is discussed in §3.5.

---

## 1. TL;DR — what we're asking for

The 14 live specialists are **frozen at `TRAINING_CUTOFF = 2026-04-30`** (`training_month = "2026-04"`). Today is 2026-07-28 → **89 days of drift**, and the monthly retrain that was supposed to keep them fresh (`cc-ensemble-monthly-retrain`) has **never run once**.

Request: **re-run `tools/freeze_artifacts.py` with `TRAINING_CUTOFF` advanced to the latest session (~2026-07-27)**, at **identical architecture / HPs / windows**, on (a) a **corrected data snapshot** (§3.7, critical) and (b) a **modernized lib set** (§3.2). Output = a new `frozen/` payload with `training_month = "2026-07"`, **same `algorithm_version = "1.0.0"`**.

**Objective** : maximize the specialists' raw **directional hit-rate / accuracy**. The *risk-gating* (signal → OPEN commit vs stay MONITOR) is handled **on the Compass side** by our own wrapper override that **R&D most likely does not know about** — this is probably the single most impactful item in this handoff: **§3.6 (landmine #6)**.

**Out of scope for this refresh** :
- ❌ no new `pl_algorithm_version` / no "v1.1.0+" flow (§3.1, landmine #1) ;
- ❌ no on-the-fly HP re-search (Optuna not shipped — §3.5) — retuning is an explicit **Phase 2**, not scope creep on the refresh ;
- ❌ no change to the soft-gate / wrapper / `alpha_macro` levers (config-as-data on the Compass side, separate lane) ;
- ❌ no new feature family / new specialist.

---

## 2. What "refresh" means precisely

| Dimension | Frozen v1.0.0 (today) | After refresh |
|---|---|---|
| `TRAINING_CUTOFF` | `2026-04-30` | `~2026-07-27` (latest session — §7-Q4) |
| `training_month` | `2026-04` | `2026-07` |
| Training windows | 12mo (baseline/TB/calibrated-TB), 24mo (GARCH-using) | **unchanged** (they slide with the cutoff) |
| Per-specialist HPs | `frozen/specialist_hps/<name>.json` (top-1 Optuna) | **unchanged** (constant-HP refit) |
| Architecture / horizon | `ControleStackingMeta` 3-bag ; h=6 (h=22 for `exp_optim_006`), business J+4–J+5 | **unchanged** |
| Training data | R&D dataset @ cutoff 2026-04 | **local DB synced from corrected prod** (§3.7, §4) |
| Libs (fit) | sklearn 1.6.1 / scipy 1.14.1 / lightgbm 4.5.0 | **modernized target, `fit ≡ declared ≡ infer`** (§3.2) |
| `algorithm_version` / `_name` | `1.0.0` / `ensemble_v1_softgate_wrapper` | **UNCHANGED** ⚠️ |
| Payload | 38 rows in `pl_model_artifact` @ `training_month=2026-04` | **+38 rows** @ `training_month=2026-07` (append) |

Prod auto-selection (must NOT break) — `ensemble_compute/main.py:154` `_latest_training_month()` : `SELECT MAX(training_month) FROM pl_model_artifact WHERE algorithm_version_id=<ensemble_v1> AND artifact_kind='specialist_model'`. Once the `2026-07` rows are loaded, `cc-ensemble-compute` switches to them **automatically**. Rollback = drop/ignore the `2026-07` rows ⇒ `MAX` falls back to `2026-04`.

---

## 3. The landmines — must transmit (the "be careful" part)

### 🔴 Landmine #1 — A retrain is NOT a new version: the DB persistence system

Compass runs a **3-axis append-only persistence under ONE frozen version identity**. This is what guarantees algo continuity — align on it, don't fight it :

| Axis | Table / mechanism | Evolves via |
|---|---|---|
| **Version identity** | `pl_algorithm_version` = **1 row, v1.0.0** | ❌ NEVER changes (explainer / brief / YTD / wrapper-window all pin it) |
| **Models** | `pl_model_artifact` UNIQUE `(version, kind, name, training_month)` | ➕ APPEND 1 row / `training_month` ; `_latest_training_month()`=`MAX` (migration `i3d4e5f6g7h8`) |
| **Config** | `pl_algorithm_config` temporal (`effective_from`+`active`, view `v_algorithm_config_current`) | ➕ APPEND 1 row `effective_from=date` (migration `g2b3c4d5e6f7`) |

➡️ **The retrain is a pure append on the model axis** (`training_month 2026-04 → 2026-07`), version frozen at `1.0.0`. The `manifest.json` keeps `algorithm_version="1.0.0"` / `_name="ensemble_v1_softgate_wrapper"`.

⚠️ The archived doc `04_ALGORITHM_FROZEN.md` §"New R&D version (v1.1.0+)" (new `pl_algorithm_version` + seed migration + `is_active` switch) is **for a new ARCHITECTURE**. Applying it to a refresh **fights the persistence system** and replays the cascade that broke explainer/brief/YTD/wrapper-window (`f1a2b3c4d5e6` → collapse `g2b3c4d5e6f7`, PR #75→#77).

### 🔴 Landmine #2 — Libs : `fit ≡ declared ≡ infer` (decision: modernize)

The real skew is NOT infer-vs-package : the prod inference container (`backend/pyproject.toml`) **and** the vendored package (`vendor/campaign5_ensemble_v1.0.0/pyproject.toml`) pin the **same** thing :
```
scikit-learn >=1.4,<1.6 · scipy >=1.11,<1.13 · lightgbm >=4.1,<4.5 · numpy ==1.26.4 · pandas >=2.1,<2.3
```
But the artifacts were **fit on libs NEWER than the package declares** (`manifest.lib_versions`) :
```
scikit-learn 1.6.1 · scipy 1.14.1 · lightgbm 4.5.0   ← ABOVE the package's own ceilings
```
→ `fit(1.6.1) ≠ declared(<1.6) ≡ infer(<1.6)`. Known latent skew (accepted for v1.0.0 : *"sklearn 1.5.2 → warnings, identical behavior observed"*, `07_PARQUET_EXPORT.md:36`) — but fragile, and not to be propagated.

➡️ **Decision** : **modernize** and remove the skew. R&D **bumps the declared deps of the `ensemble` package to an agreed current target + refits on that target** ; Compass **pins inference identically**. Final invariant : **`fit ≡ declared(ensemble/pyproject) ≡ infer(backend/pyproject)`**, documented in `manifest.lib_versions`.
- **Ceiling** : `numpy==1.26.4` is a hard pin — numpy 2 is blocked by `arch>=6.3` + `hmmlearn>=0.3` + `lightgbm`. Bump **sklearn / scipy / lightgbm / pandas** to current ; numpy 2 = *stretch*, **only** if R&D first validates arch+hmmlearn+lightgbm on numpy 2. **Do not block the refresh** on numpy 2.

### 🔴 Landmine #3 — macroeco corruption: the corruption window

The specialists read `pl_derived_indicators` as **raw passthrough** (`features.py:_passthrough` — `macd, rsi_14d, atr_14d, stochastic_d_14, close_pivot_ratio, volume_oi_ratio, daily_return`, the GARCH residual derives from `daily_return`), **no isolation layer**. These columns were **corrupted (fanout ×2–5, macroeco LEFT JOIN)** until **2026-07-22**, then corrected. **How to guarantee correct features for the retrain** is covered in **§3.7 (critical section)**.

**Open question (§7-Q1)** : was the **2026-04-30** freeze trained on corrupted or clean features? The v1.0.0 freezer read via `methodology.data_loader` (R&D dataset), not via our buggy prod loaders — *a priori* spared, **but to confirm** (if the R&D dataset derives from a prod dump taken during the corruption window, the live models are train-corrupt / serve-corrected = skew). The refresh on corrected data erases the risk either way.

### 🟠 Landmine #5 — Refit first, retune later (phased)

The Optuna walk-forward (`ensemble.optimizer.objective.build_objective` / `ensemble.validation.walk_forward`) is **not shipped** (`CHANGELOG.md:41`). **Phased plan** :
- **Phase 1 (this refresh)** : **constant-HP refit** (`frozen/specialist_hps/<name>.json`) on corrected data + modern libs. Window slides, objective unchanged.
- **Phase 2 (if Phase 1 disappoints at shadow)** : **selective** campaign — **keep the specialists that outperform**, **refit** the rest, **retune** some (new HP search on R&D side). Possibly a **full new campaign**. Research decides per-specialist (see §7-Q6).

### 🟡 Landmine #6 — The gating layer Compass runs on ITS side (R&D does NOT know about it)

**The most important item to transmit.** After the soft-gate + the vendored wrapper, Compass swaps in **its own override** at runtime (`main.py:248`, `pipeline.wrapper = CompassTransitionWrapper(...)`) — `CompassTransitionWrapper` (`scripts/ensemble_compute/compass_wrapper.py`), a subclass of the R&D `TransitionProtectionWrapper`.

- The **vendored** wrapper OR-combines its 4 detectors (`running_acc`, `trend`, `three_way`, `dispersion`) → **any single fire forces MONITOR**. **Too aggressive** : on the 2026 backfill, `cluster_dispersion` alone vetoed **28/63** soft-gate commits while `running_acc_5d` averaged **0.981** on those days (= it killed commits mid winning-streak). Wrapper coverage = **17%** vs R&D 46.1%.
- The **Compass subclass** relaxes it with an AND-gate : `fired_dispersion` **alone** + `running_acc_5d ≥ threshold` → **RELEASE**. Other detectors still veto. Threshold = `pl_algorithm_config.compass_wrapper_dispersion_with_acc_threshold` = **0.60** (config-as-data). 2026 backfill result : coverage **17% → 49%** (beats R&D 46.1%), accuracy **100% → 76%**.

**Division of labor to transmit :**

| Layer | Owner | Objective |
|---|---|---|
| 14 specialists + soft-gate | **R&D** | **Maximize raw directional hit-rate / accuracy / coverage.** The strongest possible signal. |
| `CompassTransitionWrapper` + `pl_algorithm_config` levers | **Compass** | **Risk-gating / blocking** downstream : *commit (OPEN) vs MONITOR*. **Our brake, driven on our side, no re-training.** |

➡️ **Message to R&D** : do **not** train/tune the specialists (nor the soft-gate) toward **abstention-as-caution** to "avoid false commits". **There is a downstream gating layer you don't see.** Optimize for **raw directional accuracy and hit count** ; the blocking is ours. **Over-tuning the `dispersion` detector** in the vendored wrapper is largely **wasted effort** — Compass releases it whenever rolling accuracy is high.

### 🔴🔴 §3.7 — CRITICAL SECTION: guaranteeing correct features for the retrain

The fundamental invariant = **train/serve feature parity**. At inference, `cc-ensemble-compute` reads `pl_derived_indicators` (produced by `app/engine/`). Two **independent** correctness axes :

**(A) Is the stored table current with the CURRENT engine?**
Fanout is closed in code : `app/engine/runner.py` loads a **one-row-per-date** OHLCV series from `v_contract_data_chained` (front-month by the **canonical roll calendar** `ref_contract.active_from` — no more oi/volume heuristic), with `_assert_unique_dates` at **4 boundaries** (166/221/256/311) and macroeco attached **per-version** (`_attach_version_macroeco`, one row per (date, contract)). PR #74.
**But** `pl_derived_indicators` was corrected on 2026-07-22 via `--derived-only`, and the front-month chaining logic evolved (canonical calendar). A fresh `compute-indicators --all-contracts --full --derived-only` was therefore run on the synced local DB.
➡️ **RESOLVED (2026-07-28)** : the recompute + §3.8 diff showed **`macd` unchanged** → prod was **already on the current roll chain** (no staleness). The only changes are the **roll neutralization** (RSI/ATR/`daily_return`). So there is **no chain re-correction to do** — the prod-side correction that ships with the model swap is purely the neutralization.
⚠️ The recompute **would also shift LIVE inference** (the `2026-04` models read the same table) — which is why it was run **local-first** (prod untouched), per §3.8.

**(B) Does R&D compute features the SAME way inference does?**
Even clean data is useless if `methodology.data_loader` recomputes RSI/ATR/z-scores with different formulas → train/serve skew **independent** of the corruption.
➡️ **R&D must read the corrected `pl_derived_indicators` DIRECTLY from the synced local DB — NOT recompute it.** The specialists consume those columns as raw passthrough ; reading the stored corrected table **IS** the parity guarantee.

**Delivery mechanism (also settles local-DB vs parquet, §4)** : `sync_from_gcp.py` (corrected prod → R&D local DB) ; R&D trains against the **local DB**, reading `pl_derived_indicators` directly. **Local DB beats parquet precisely because it guarantees parity** (same table, same values inference sees).

**⚠️ Audit results (2026-07-28) — raw prod `pl_derived_indicators` was NOT retrain-safe as-is ; the corrected local DB (§4) fixes it.** The macroeco fanout class is confirmed **fully closed** and the per-indicator math (Wilder seeding, trailing 252d z-score ddof/zero-guard, Bollinger, stochastic, NaN→NULL writes) is **correct**. Three residual issues were found — **#1 resolved (no staleness), #2 handled by the neutralization, #3 deferred** :

- **🔴 HIGH — stale history vs the current roll chain → ✅ RESOLVED (no staleness found).** The front-month resolver was swapped on 2026-07-22 (migration `d5e6f7a8b9c0`, `active_from` calendar view), which *moves historical roll boundaries*, and `pl_derived_indicators` is only rewritten under `--full`. **The 2026-07-28 recompute + diff showed `macd` unchanged** → prod was already on the current chain. No chain re-correction needed.
- **🔴 HIGH — raw front-month splice, no back-adjustment → ✅ HANDLED (option (b), implemented).** `v_contract_data_chained` emits the raw close of whichever contract is front-month ; at each roll (~5/yr: H/K/N/U/Z) the series steps A→B by the calendar spread — a **phantom return** the positional math can't distinguish from a real move (RSI `np.diff`, ATR TR, `daily_return` all spiked ; z-scores + the GARCH residual inherited it). **Fix (§7-Q9)**: the roll-day return is now **neutralized at source** — zeroed on `is_roll_boundary` rows — so it no longer enters RSI/ATR/`daily_return` nor their z-scores. The **MACD/Bollinger level residual** is accepted (diff confirmed `macd` unchanged ; full removal = option (c) back-adjust, deferred).
- **🟠 MED — no date-gap detection.** `_assert_unique_dates` catches duplicates, not **gaps**. A missing front-month session (scraper miss, or NULL front-month close while other contracts traded → row dropped by the view) silently makes every subsequent rolling/Wilder/z-score window span non-consecutive dates, **no error**. A cheap fail-loud gap guard is recommended (§7-Q9).

(Minor, non-blocking: 252d z-score uses `min_periods=126` → early rows 126–251 scaled over an expanding window (mild non-uniformity) ; Wilder NaN-gap injects one phantom zero-change day across interior gaps (bounded).)

### 🔵 §3.8 — Correction & deployment workflow: local-first, prod-parity-gated

**The rule : never run the recompute against prod live. But the corrected features MUST eventually reach prod — otherwise the new models serve on stale features (train/serve skew reintroduced).** These two facts are reconciled by a **diff gate** :

1. **Sync prod → local** (`sync_from_gcp.py`). At t0, local `pl_derived_indicators` == prod.
2. **Recompute locally** (`compute-indicators --all-contracts --full --derived-only`) + probe the doubtful parts. **Prod is untouched.**
3. **Diff (local-recomputed) vs (prod-current) `pl_derived_indicators` :**
   - **diff ≈ 0** → prod is already clean → local == prod → **deploy the new `2026-07` models straight to prod ; parity holds. The workflow is plug-and-play.** ✅
   - **diff ≠ 0** → the correction R&D trained on is **not** in prod → shipping models alone = skew. The **validated** correction must **also land in prod**, in the **same deploy window** as the model bootstrap. This is the designed `--derived-only` path (idempotent UPSERT, leaves `pl_indicator_daily` decisions/gauges frozen, `_assert_unique_dates` fail-loud ; exactly how 2026-07-22 was done). "Don't touch the live" becomes "touch it once, validated, atomically with the model swap." ⚠️
4. **R&D trains on the corrected local DB** throughout — it works on local anyway, so this adds no friction.

**RESULT (2026-07-28)** — diff gate **executed**: **diff ≠ 0** (RSI 2604 / atr_14d 854 / daily_return 52 rows changed = the roll neutralization ; macd unchanged = no chain staleness). → the **diff≠0 branch applies**: the validated `--derived-only` correction **lands in prod in the same window as the model bootstrap** (§6 step 5). Not skipped.

**Anti-pattern to avoid** : correct-only-local → deploy models to prod → leave prod features stale. Silent skew, invisible until performance quietly degrades.

---

## 4. What Compass provides to R&D — ✅ READY

**The training DB is prepared** (2026-07-28). R&D trains against the **local DB** (`localhost:5433`), reading `pl_derived_indicators` **directly** — that direct read IS the train/serve parity guarantee (§3.7-B). Do **not** recompute the indicators R&D-side.

1. **Data is current** — synced from prod through **session 2026-07-27** (`sync_from_gcp.py`). All `pl_*/ref_*/aud_*` tables match prod (70k rows). Prod & local at the same schema (`alembic h3c4d5e6f7g8`, +1 local for the flag below).
2. **Features are corrected** — `pl_derived_indicators` recomputed by the current engine with **roll-contamination neutralization** (§3.7 / §7-Q9): at every roll the phantom splice return is zeroed, so RSI/ATR/`daily_return` no longer spike, and the **GARCH residual** (derived from `daily_return`) is clean. `pl_indicator_daily` decisions are left **frozen at prod values** (`--derived-only`). Fanout guards green (self-certified one-row-per-date).
3. **Roll rows are flagged** — new BOOLEAN column **`pl_derived_indicators.is_roll_boundary`** (migration `i4d5e6f7g8h9`) = TRUE on the first row of each new front-month (**53 rolls** across history). **R&D SHOULD exclude or down-weight these rows in training** — `WHERE NOT is_roll_boundary`, or `sample_weight=0` on them. Even neutralized, the roll row is semi-artificial. At inference `CompassTransitionWrapper` applies the symmetric treatment (§3.6) → parity.
   - ⚠️ Roll-safe chain : front-month by the canonical calendar (`ref_contract.active_from`), one row per date, `_assert_unique_dates`-guarded — no oi/volume heuristic.
4. **Target lib set** (agreed R&D↔Compass) for the `fit ≡ declared ≡ infer` invariant (§3.2).
5. **The v1.0.0 manifest contract** (this file + `frozen/manifest.json`) as the template.

> **Why the training features are cleaner than what live prod currently serves** : the neutralization is applied to the **local training DB** and the **Compass engine branch** — **not yet merged to prod**. The §3.8 diff confirmed prod's stored `pl_derived_indicators` differs from the corrected version (**RSI 2604 / atr_14d 854 / daily_return 52** rows changed ; **macd unchanged**). Per §3.8 (diff≠0) that correction **lands in prod together with the model swap** — R&D need not act on it, it is reconciled at deploy. This keeps train/serve parity for the new models.

> **Obtaining the corrected DB** : if R&D reads **this same local DB** (`localhost:5433`, the intended setup) — **it's already done**: the corrected `pl_derived_indicators` + the `is_roll_boundary` column are materialized in the DB now (the branch produced them but is **not** needed to *read* them). Nothing to hand over. ⚠️ **Do NOT re-run `sync_from_gcp.py` on this DB while R&D trains** — it reloads `pl_derived_indicators` from prod's *uncorrected* values and wipes the neutralization ; if you must re-sync, re-run `compute-indicators --all-contracts --full --derived-only --force` right after (sync → recompute, always paired). Only if R&D uses a **separate** local DB do you need a `pg_dump` handoff (or to reproduce via the engine branch). — The engine **branch/commit** is needed only later, for the **prod** deploy (§3.8 / §6 step 5), not for R&D to start.

---

## 5. What R&D must deliver (artifact contract)

A `frozen/` payload **structurally identical** to v1.0.0, produced by `tools/freeze_artifacts.py`, `TRAINING_CUTOFF` advanced, on the modernized lib target :

- **38 rows** : 14 `specialist_model` (.pkl) + 14 `specialist_hp` (.json) + 1 `long_run_anomaly` + 1 `long_run_priors` + 1 `long_run_regime_clusters` + 1 `soft_gate_config` + 1 `wrapper_config` + 5 `canonical_snapshot`. (The refresh only touches the 14 specialists ; long-run / tuned-config artifacts may stay unchanged but must stay manifest-consistent.)
- `manifest.json` per row : `sha256`, `n_bytes`, `payload_encoding`, `training_month="2026-07"`, `fit_train_start`/`fit_train_end`, `window_months`, `class_balance`, `n_train`.
- **Header** : `algorithm_version="1.0.0"`, `algorithm_version_name="ensemble_v1_softgate_wrapper"` (UNCHANGED), `git_sha`, `data_source` (e.g. `compass_prod_2026-07`), **`lib_versions` = the modernized target** (§3.2).
- **Repro** : `tests/test_reproducibility.py` **green** — re-run at identical cutoff ⇒ bit-identical `manifest.json` (modulo `created_at` + `fit_time_seconds`).
- **Freezer guards** (do not bypass) : `_slice_train` *raises* if < 30 rows ; `monthly_retrainer` *raises* on single-class labels. If either fires on an advanced 12/24-month window → **stop and escalate**, do not shrink the window.

Delivery : tarball `campaign5_ensemble_v1.0.0_2026-07.tar.gz` + a comparative performance note (§8).

---

## 6. Compass-side integration (post-delivery)

1. `tar xzvf` into a **new** vendored dir (`vendor/campaign5_ensemble_v1.0.0_2026-07/`) — **never patch the existing pack in-place** ("read-only delivery" rule).
2. Bump `backend/pyproject.toml` : `ensemble = {path = "vendor/campaign5_ensemble_v1.0.0_2026-07"}` + repin the bootstrap wrapper `FROZEN_DIR`.
3. **Align prod lib pins** to `manifest.lib_versions` (§3.2) — the `fit ≡ declared ≡ infer` invariant closes HERE.
4. **No Alembic migration required** (same `pl_algorithm_version`, `pl_model_artifact` already exists) → the `migrations-prod-via-main-only` rule doesn't bite. The `pyproject` bump + redeploy go through **merge to `main` → CI/CD**.
5. **Land the roll-neutralization in prod** (diff≠0 confirmed — §3.8), **in the same window** as step 6: merge the engine branch (neutralization + migration `i4d5e6f7g8h9`) to `main` → CI/CD applies the migration (adds `is_roll_boundary`) + deploys the corrected engine → run `compute-indicators --all-contracts --full --derived-only` on prod (applies the neutralization + populates the flag ; `pl_indicator_daily` decisions stay **frozen**). Now **prod features == training features**.
6. Re-run `cc-ensemble-bootstrap-artifacts` (UPSERT appends `training_month=2026-07`, keeps `2026-04`) :
   ```bash
   poetry run ensemble-bootstrap-artifacts --dry-run   # verify SHA-256 on disk
   gcloud run jobs execute cc-ensemble-bootstrap-artifacts --region=europe-west9 --project=cacaooo
   ```
7. Verify `_latest_training_month()` = `2026-07`, then **control backfill** (`--historical --dry-run`) + **diff** decisions vs the `2026-04` models, **through `CompassTransitionWrapper`** (not the bare vendored wrapper).
8. **Rollback** trivial : drop/ignore the `2026-07` rows ⇒ `MAX(training_month)` falls back to `2026-04`. No loss, no down-migration.

---

## 7. Decisions (✅ settled / ⏳ open)

- ⏳ **Q1 (landmine #3)** : was the `2026-04-30` freeze trained on corrupted or clean `pl_derived_indicators`? → calibrates refresh performance expectations.
- ✅ **Q2 (data)** : **local DB sync** (`sync_from_gcp`), R&D reads `pl_derived_indicators` directly — **no parquet, no R&D recompute** (train/serve parity). §3.7.
- ✅ **Q3 (libs)** : **modernize**, invariant `fit ≡ declared ≡ infer` ; numpy 2 = *stretch* gated by arch/hmmlearn, doesn't block the refresh. §3.2.
- ⏳ **Q4 (cutoff)** : recommended = **latest session (~2026-07-27)**, `training_month=2026-07` (the "90 days" intent). Confirm vs a month-end boundary.
- 🔵 **Q5 (shadow)** : recommended = **shadow-eval on ~20 recent sessions** (coverage/accuracy `2026-07` vs `2026-04`) **through `CompassTransitionWrapper`** before the prod flip. Phase-2 gate.
- ✅ **Q6 (objective / phases)** : **Phase 1 constant-HP refit** ; **Phase 2** (if shadow disappoints) = selective campaign (keep outperformers, refit / retune the rest, try both options). §3.5.
- ✅ **Q8 (correction workflow — NEW)** : **local-first, prod never touched by the recompute during R&D** ; a **diff gate** decides whether prod needs the correction landed alongside the model swap. §3.8.
- ✅ **Q7 (audit — done)** : audit complete (§3.7). Fanout closed + per-indicator math correct ; residual issues = stale-chain history (→ `--full` recompute), raw roll-splice contamination (→ Q9), no gap detection (→ deferred).
- ✅ **Q9 (roll-jump handling — DECIDED (b) + IMPLEMENTED)** : Compass engine change **done + validated** (feature branch ; 15 tests + ruff + pyright green ; **not yet merged to prod**): `mark_roll_boundaries` in the front-month loader (`app/engine/runner.py`), roll-day return neutralization in `DailyReturn` / `WilderRSI` / `TrueRange`, and a persisted **`is_roll_boundary`** column (migration `i4d5e6f7g8h9` + model + writer). At each roll the day-over-day change is zeroed so the phantom spread never enters RSI/ATR/`daily_return` nor their z-scores. **R&D excludes/down-weights flagged rows** in training ; **`CompassTransitionWrapper` handles the symmetric inference treatment** (§3.6) → parity. **Local recompute done** (2656 rows) ; diff confirmed **macd unchanged** = the accepted MACD/Bollinger level residual (full removal = option (c), deferred). Prod correction lands with the model swap (§3.8, diff≠0).
- ⏳ **Gap guard — DEFERRED to Phase 2** : a cheap fail-loud series-continuity check in `app/engine/runner.py` (crash if the loaded series has a calendar gap). Tracked on the Phase-2 track (§3.5) — natural to fold into the roll-flag work.

---

## 8. Acceptance criteria (go / no-go for the prod flip)

- [ ] `manifest.json` : `algorithm_version=1.0.0`, `_name=ensemble_v1_softgate_wrapper`, `training_month=2026-07`, 38 rows, SHA-256 consistent.
- [ ] `tests/test_reproducibility.py` **green** (bit-identical manifest at constant-cutoff re-run).
- [ ] **`fit ≡ declared ≡ infer`** : `manifest.lib_versions` = `ensemble/pyproject.toml` declared deps = `backend/pyproject.toml` pins (§3.2 resolved, not just "accepted warnings").
- [x] Training snapshot = **local DB synced from corrected prod** (2026-07-27) ; `pl_derived_indicators` recomputed by the current engine (2656 rows) + **`_assert_unique_dates` green** ; audit (§7-Q7) closed ; `is_roll_boundary` populated (53 rolls). ✅ **DONE**
- [x] §3.8 **diff gate executed** : diff≠0 (neutralization, no staleness) → correction scheduled to land with the model swap (§6 step 5). ✅ **DONE**
- [ ] Vendored pack test suite (unpickle + `predict_*` smoke) **green** on the target libs.
- [ ] Shadow-eval (Q5) **through `CompassTransitionWrapper`** : coverage/accuracy `2026-07` **≥** `2026-04` baseline (or explained/accepted gap).
- [ ] `cc-ensemble-compute --historical --dry-run` consistent (no unexpected NaN, 14 specialists OK).
- [ ] Rollback verified (drop `2026-07` rows ⇒ clean fallback to `2026-04`).

---

### Internal references
- Ensemble architecture : `docs/archive/pipelines/PIPELINE_ENSEMBLE.md`
- Original R&D handoff : `docs/archive/2026-05-rnd-handoff/handoff_v1.0.0/` (esp. `04_ALGORITHM_FROZEN.md`, `07_PARQUET_EXPORT.md`)
- R&D freezer : `vendor/campaign5_ensemble_v1.0.0/tools/freeze_artifacts.py` ; package deps : `vendor/campaign5_ensemble_v1.0.0/pyproject.toml`
- Compass bootstrap : `backend/scripts/ensemble_bootstrap/` (README + `main.py`)
- **DB persistence (§3.1)** : `pl_algorithm_version` (v1.0.0 identity) + `pl_model_artifact.training_month` (migration `i3d4e5f6g7h8`, auto-select `main.py:154`) + temporal config `pl_algorithm_config`/`v_algorithm_config_current` (migration `g2b3c4d5e6f7`)
- **Features / anti-corruption (§3.7)** : `app/engine/runner.py` (`_assert_unique_dates`, `_attach_version_macroeco`, `load_all_market_data`) + `.claude/rules/timeseries-uniqueness.md` + PR #74 ; `--derived-only` recompute : `app/engine/db_writer.py:272`
- **Roll-neutralization (§3.7 / §7-Q9, implemented)** : `runner.mark_roll_boundaries` + neutralization in `indicators/ratios.py` (`DailyReturn`), `indicators/rsi.py` (`WilderRSI`), `indicators/atr.py` (`TrueRange`) ; column `pl_derived_indicators.is_roll_boundary` (migration `i4d5e6f7g8h9`, model `PlDerivedIndicators`, writer `db_writer.write_derived_indicators`) ; tests `tests/engine/test_roll_neutralization.py`
- **Compass wrapper override (§3.6)** : `scripts/ensemble_compute/compass_wrapper.py` + swap `main.py:248` + tuning `docs/archive/pipelines/wrapper-levers-tuning.md`
- Local-DB sync : `backend/scripts/sync_from_gcp.py` + `docs/runbooks/db-sync-from-gcp.md`
- Version discipline : `.claude/rules/migrations-prod-via-main-only.md` + PR #75→#77 (the collapse not to replay)

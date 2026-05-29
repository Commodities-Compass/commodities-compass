# Campaign 5 Ensemble Orchestrator — Production Deployment Plan

> **Purpose**: ship the Campaign 5 Step 1 winning configuration (`TPW-001`) into the live Commodities Compass production pipeline (the [rnd-algo-integration.md](/Users/hediblagui/Developer/work/RnD_Compass/rnd-algo-integration.md) system).
>
> **What's being deployed (the artifact)**: a 14-specialist soft-gate Bayesian orchestrator wrapped by a 2-detector Transition-Protection meta-gate. Validated in-sample on Jan-Apr 2026 at **82.5% global accuracy, all 4 months ≥65%, 48.8% coverage** — passes the binding gate (`CAMPAIGN_4_ARCHITECTURE_VISION.md` §5).
>
> **Caveat ACCEPTED by Hedi** (2026-05-17): wrapper thresholds are in-sample on Jan-Apr 2026. Production deployment proceeds with parallel running + monitoring before promotion. Out-of-sample replication on subsequent months is part of the rollout, not a blocker.
>
> **What this doc is NOT**: not a cockpit-UI feature (Julien's `NOTE_HEDI_2026-05-16.md` covers the J+1 cockpit prediction). This is **PROD pipeline integration** — get the orchestrator running every weekday, writing its decision into `pl_indicator_daily`.

---

## 1 — Architectural fit assessment

### Does the Campaign 5 system fit Path A / B / C?

The R&D integration doc (§5) defines three paths. **Campaign 5 is Path C + Path B hybrid** — not Path A.

| Path | Why C5 is NOT this path |
|---|---|
| **Path A** (DB config only) | C5 has NO power-formula composite. The 14 specialists each have their own target_fn (Triple-Barrier / calibrated-TB / 3-class ATR), feature_specs (baseline / FX / FX+ENSO / +GARCH / MAXIMAL), and sample_weight_fn (anti-bias balanced × asymmetric class weights). The 8-parameter power formula in `pl_algorithm_config` cannot represent ANY of these — let alone 14 of them composed into a soft-gate + wrapper. |
| **Path B** (new indicator + same composite) | C5 doesn't add indicators to the existing composite — it REPLACES the composite. The orchestrator is itself a multi-stage pipeline (specialists → soft-gate → wrapper), not a single indicator. |
| **Path C** (new data source + new pipeline) | YES for new data (ENSO from NOAA + FX from ECB do not exist in prod). |
| **Path B** (new compute path) | YES for the new compute: new tables for specialist predictions / orchestrator decisions, new Cloud Run Jobs (monthly retrainer + daily compute), new algorithm_version that DOES NOT use the legacy composite path. |

### How C5 plugs into the existing `pl_indicator_daily` contract

`pl_indicator_daily` is keyed on `(date, contract_id, algorithm_version_id)` (R&D doc §3). The legacy power-formula algorithm writes one row per (date, contract, version). The dashboard reads where `is_active=TRUE`.

We introduce a **new `pl_algorithm_version` row** (`name='ensemble_v1_softgate_wrapper'`, `version='1.0.0'`). Our daily compute job writes its own `pl_indicator_daily.decision` for this version_id. The schema is honoured: same column, same key, NO breaking change. The dashboard reads from whichever version is `is_active=TRUE` — we parallel-run for 2-4 weeks, compare to legacy, then flip the activation.

**Key implication**: most columns in `pl_indicator_daily` (e.g. `indicator_value`, `momentum`, `final_indicator`, `macroeco_bonus`, `macroeco_score`) are **specific to the power formula** and meaningless under the ensemble. Per the R&D doc's non-negotiable rule #3 (pipeline-continuity — values must trace to a computation), we write `NULL` for those columns, NOT `0.0`. Only `decision`, `confidence`, `direction`, and our own audit columns get populated.

### Daily-analysis LLM interaction

The R&D doc (§2) notes that `cc-daily-analysis` (20:19 UTC) OVERWRITES `pl_indicator_daily.decision` with an LLM judgement. **The current daily-analysis is keyed by `algorithm_version_id`**. Our orchestrator writes rows under a NEW version_id, so daily-analysis (which targets the legacy version by default) won't touch our row by default.

But: per the existing `--all-versions` flag pattern, if daily-analysis is invoked with `--all-versions`, it WILL overwrite our decision. We must verify daily-analysis's targeting:

- **Recommendation**: configure `cc-daily-analysis` to target ONLY the legacy version_id (not `--all-versions`) so it never overwrites our row. Or have it skip our version explicitly. This is one of the **prerequisites Hedi must confirm before merge** (§4).

---

## 2 — Component inventory (what's being shipped)

All paths below are in `/Users/hediblagui/Developer/work/RnD_Compass/` unless flagged as PROD-PATH (in `commodities-compass`).

### 2.1 Specialist pool (14 architectures)

7 "powerful players" kept from Campaign 4 + 7 supporting:

```
exp_optim_002         (Triple-Barrier baseline)                    — required for soft-gate
exp_optim_005         (GARCH residual)                              — required for cluster dispersion
exp_optim_006         (h=22 baseline)                               — required (Winter, h=22 horizon)
exp_optim_011         (FX+ENSO macro_combined) ★ TOP SCORER         — required (best single)
exp_optim_017_bear_4  (DOWN:3 + FX + calibrated-TB)                  — required (Spring bear)
exp_optim_017_bear_8  (DOWN:2 + FX+ENSO)                             — Spring bear pool
exp_optim_017_bull_4  (UP:2 + FX)                                    — required (Spring bull)
exp_optim_017_bull_5  (UP:3 + Logistic meta)                         — Spring bull pool
exp_optim_017_bull_7  (UP:3 + FX)                                    — Spring bull pool
exp_optim_017_bull_8  (UP:2 + MAXIMAL)                               — Spring bull pool
xpol_W_TB_garch       (Triple-Barrier + GARCH)                       — Winter cluster vote
xpol_W_TB_macro       (Triple-Barrier + FX+ENSO macro)                — Winter cluster vote
xpol_S_bull_garch_fx  (calibrated-TB + UP:3 + GARCH + FX)             — Spring cluster vote
xpol_S_bear_garch_macro (calibrated-TB + DOWN:3 + GARCH + FX+ENSO)   — Spring cluster vote
```

Per-specialist artifact: `output/exp_optim_018c__<name>/top1_config.json` (Optuna top-1 HPs + feature_groups + normalization + tau_conf/tau_diss).

### 2.2 Frozen long-run components (re-used as-is)

| Artifact | Source path | Purpose | Refit cadence |
|---|---|---|---|
| `anomaly_veto.pkl` | `output/exp_optim_020/` | IsolationForest 10y; daily anomaly z-score input. NOTE: `AV-001` polarity-inverted, used as CONTEXT feature (not veto). | Yearly (cocoa structural shift at decade scale; matches `CAMPAIGN_4 §6 Phase 2`) |
| `structural_priors.json` | `output/exp_optim_020/` | Empirical Bayes table over (regime × vol_12m_tercile × ret_12m_tercile). 12 buckets populated. | Yearly |
| `regime_clusters.json` | `output/exp_optim_021b/` | K-means centroids + scaler for monthly state vectors. k=2. | Yearly |
| **`db_master_fundamentals.pkl` (NEW 2026-05-19)** | `data/external_data/Db_Master_*.xlsx` snapshot | **Frozen lookup table** of internal Compass fundamentals (`feves_share`, `processing_ratio`, `procurement_hhi`, `top3_exporter_share`) keyed by `month_date`. Replaces the "live ingest" option for Db_Master ([Q6 resolution](#3--prerequisites-hedi-must-confirm-before-merge)). Engine reads via `merge_asof backward` on month boundaries. **No live scraper** — refreshed ponctually when new XLS delivered. | Yearly + ponctuel (sur livraison XLS interne) |
| Macro layer config | `methodology/macro_events/pipeline.py` (constants) | `MacroEventLayer` thresholds: conf=0.7, dir=0.3, half_life breaks (0.3, 0.6). | Constant (code-level) |

**Storage**: all 4 frozen artifacts live in `pl_model_artifact` table (§4.5 + §7), not on filesystem or GCS. North-star alignment: config + artifacts as data. SHA-256 audited at load.

### 2.3 Soft-gate Bayesian orchestrator config

`output/exp_optim_022/tuned_configs.json` → use the **Fold B params uniformly** (sensitivity-verified stable at 72.2% global per `EXP-OPTIM-024`):

```json
{
  "alpha_macro": 1.4770,
  "alpha_prior": 0.1664,
  "alpha_anomaly": 0.7219,
  "commit_threshold": 0.2493
}
```

### 2.4 Transition-Protection Wrapper config

`output/exp_optim_025/tuned_config.json`:

```json
{
  "use_running_acc": true,
  "tau_run": 0.5931,
  "running_window": 3,
  "min_running_n": 2,
  "use_trend_conflict": false,
  "tau_trend": 0.0301,
  "trend_window": 7,
  "use_cluster_dispersion": true,
  "min_cluster_n": 2,
  "use_three_way_disagreement": false
}
```

Plus the hardcoded specialist→cluster mapping in `methodology/orchestrator/transition_wrapper.py:53` (`WINTER_SPECIALISTS` + `SPRING_SPECIALISTS`).

### 2.5 R&D code modules to port to prod

Module → prod target:

| R&D source | Prod target |
|---|---|
| `methodology/optimizer/specialists.py` (registry of 14 architectures) | `backend/app/engine/ensemble/specialists.py` |
| `methodology/retrain/monthly_retrainer.py` | `backend/app/engine/ensemble/monthly_retrainer.py` |
| `methodology/orchestrator/soft_gate.py` | `backend/app/engine/ensemble/soft_gate.py` |
| `methodology/orchestrator/transition_wrapper.py` | `backend/app/engine/ensemble/transition_wrapper.py` |
| `methodology/long_run/{anomaly_veto,structural_priors,regime_similarity}.py` | `backend/app/engine/ensemble/long_run/` |
| `methodology/macro_events/pipeline.py` | `backend/app/engine/ensemble/macro_events.py` |
| `methodology/external_data.py` (ENSO/FX merge) | New: `backend/app/scripts/enso_scraper/`, `backend/app/scripts/fx_scraper/` |
| `methodology/features_external.py` | `backend/app/engine/ensemble/features_external.py` |
| `methodology/features_garch.py` | `backend/app/engine/ensemble/features_garch.py` |
| Existing R&D models (`methodology/models/`) | `backend/app/engine/ensemble/models/` |

---

## 3 — Prerequisites (Hedi must confirm BEFORE merge)

These are open questions that block deployment until resolved. Status updated 2026-05-19.

- **Q1 — ENSO/FX scrapers**: ✅ **RESOLVED (2026-05-19)** — confirmed no existing feed in prod. New USs prepared: [P1-scraper-enso.md](../user-stories/P1-scraper-enso.md) + [P1-scraper-fx.md](../user-stories/P1-scraper-fx.md). Both target shared agnostic table `pl_external_indicator`. R&D code already snapshot in `docs/onboarding/ingest_{enso,fx}.py` + CSV backfill in `docs/onboarding/{ENSO,FX}/`.
- **Q2 — pl_article_segment freshness in prod**: ✅ **RESOLVED (2026-05-19)** — code evidence shows `press_review_agent/db_writer.py:96-149` (`write_theme_sentiments()`) writes `pl_article_segment` daily at 19:05 UTC via the `inline_v1` extraction embedded in the LLM prompt. Cron: `5 19 * * 1-5`. Provider: OpenAI o4-mini (production). ~4-8 rows/day. The `pl_article_segment` model docstring claiming "MODEL-ONLY" is **stale** (predates the inline extraction merge) — should be updated. **Action**: confirm by SQL `SELECT count(*), max(article_date) FROM pl_article_segment WHERE article_date > now() - interval '7 days';` via bastion.
- **Q3 — daily-analysis targeting**: ✅ **RESOLVED (2026-05-19)** — code evidence: `daily_analysis/db_analysis_engine.py:238-241` scopes to `WHERE is_active = TRUE LIMIT 1`. **MAIS**: day-1 promotion of `ensemble_v1_softgate_wrapper` to `is_active=TRUE` means daily-analysis WILL target the ensemble row and overwrite its decision every night at 19:20 UTC. **Mitigation**: small US [P2-daily-analysis-version-flag.md](../user-stories/P2-daily-analysis-version-flag.md) adds explicit `--algorithm-version <name>` flag, pinned to `legacy` in deploy.yml. Bloquant pour le launch C5 day-1.
- **Q4 — GCS bucket**: ✅ **RESOLVED (2026-05-19)** — **REPLACED by DB table `pl_model_artifact`** (cf. §4.5 + §7). No GCS bucket required. Aligned with north-star "config as data" + simpler ops (one auth, one backup, one rollback). 14 specialist artifacts + 4 long-run artifacts (~50MB/month) fit trivially in PostgreSQL BYTEA.
- **Q5 — DataFrame size for the engine**: today the R&D pipeline runs on a ~2600-row canonical CSV. In prod the engine pulls per-row from `pl_contract_data_daily` via `runner.load_all_market_data()`. Inspect: does the front-month-by-OI continuity logic give us the same time series the R&D pipeline trained on? Critical for forward_return computation parity. **PENDING** — to be checked in Sprint 1 of implementation via `extract_rd_dataset.py` cross-check.
- **Q6 — Db_Master fundamentals**: ✅ **RESOLVED (2026-05-19)** — Db_Master treated as **frozen long-run artifact** in `pl_model_artifact` (§2.2 + §7), refit yearly + ponctuel sur livraison XLS. No live scraper, no monthly ingest pipeline. The engine reads the frozen lookup table at compute-time, joins via `merge_asof backward` on `month_date`. **HEDI 2026-05-19 directive**.
- **Q7 — Compute envelope**: each daily orchestrator run does 14 inference passes (~10ms each) + wrapper (~50ms) + read 5 frozen artifacts from DB BYTEA + write rows. Fits well in 1Gi memory + ~2min wallclock. Monthly retrainer is heavier (~3-5 minutes). Verify Cloud Run Job memory/CPU sufficient. **PENDING** — to be checked in Sprint 1 via local benchmark.
- **Q8 — Reproducibility constraint**: every artifact (LightGBM models, RF, IsolationForest, KMeans) is fit with `deterministic=True`, `num_threads=1`, `random_state=42`. Confirm prod base image has scientific dependencies pinned consistently with R&D (numpy 1.26.4, scipy, scikit-learn ==R&D version, lightgbm ==R&D version) — version drift will break determinism and silently change decisions. **PENDING** — to be checked in Sprint 1 by diffing `pyproject.toml` constraints vs R&D venv.

---

## 4 — Schema migrations

Three new tables. All use idempotent Alembic patterns (`_has_column` guard, NULLable columns, indexed on `(date, contract_id)` per non-negotiable rule #4).

### 4.1 `pl_specialist_prediction` — per-specialist daily vote

```sql
CREATE TABLE IF NOT EXISTS pl_specialist_prediction (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date                 DATE NOT NULL,
    contract_id          UUID NOT NULL REFERENCES ref_contract(id),
    algorithm_version_id UUID NOT NULL REFERENCES pl_algorithm_version(id),
    specialist_name      VARCHAR(64) NOT NULL,        -- e.g. "exp_optim_011"
    window_months        SMALLINT NOT NULL,           -- 3 / 6 / 12 / 24
    pred                 VARCHAR(10) NOT NULL,        -- "OPEN" | "HEDGE" | "MONITOR"
    n_features_used      SMALLINT NULL,               -- post-imputer feature count
    forward_return_6d    NUMERIC(15, 6) NULL,         -- target proxy (forward-computed)
    created_at           TIMESTAMP NOT NULL DEFAULT now(),

    CONSTRAINT uq_specialist_prediction
        UNIQUE (date, contract_id, algorithm_version_id, specialist_name)
);

CREATE INDEX IF NOT EXISTS ix_specialist_prediction_date_version
    ON pl_specialist_prediction (date, algorithm_version_id);
```

### 4.2 `pl_orchestrator_decision` — orchestrator + wrapper audit trail

```sql
CREATE TABLE IF NOT EXISTS pl_orchestrator_decision (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date                     DATE NOT NULL,
    contract_id              UUID NOT NULL REFERENCES ref_contract(id),
    algorithm_version_id     UUID NOT NULL REFERENCES pl_algorithm_version(id),

    -- Soft-gate outputs
    soft_gate_decision       VARCHAR(10) NOT NULL,    -- decision BEFORE the wrapper
    net_score                NUMERIC(15, 6) NOT NULL,
    weights_sum              NUMERIC(15, 6) NOT NULL,
    n_committed_specialists  SMALLINT NOT NULL,

    -- Wrapper outputs
    decision_wrapped         VARCHAR(10) NOT NULL,    -- final decision (this is what pl_indicator_daily.decision mirrors)
    wrapper_active           BOOLEAN NOT NULL,
    fired_running_acc        BOOLEAN NOT NULL,
    fired_trend              BOOLEAN NOT NULL,
    fired_dispersion         BOOLEAN NOT NULL,
    fired_three_way          BOOLEAN NOT NULL,

    -- Context (audit trail) — every column traces to a computation per rule #3
    running_acc_5d           NUMERIC(8, 6) NULL,      -- NaN -> NULL
    realized_return_5d       NUMERIC(15, 6) NULL,
    winter_vote_signed       SMALLINT NULL,
    spring_vote_signed       SMALLINT NULL,
    macro_direction          SMALLINT NULL,           -- -1 / 0 / +1
    macro_surprise           NUMERIC(8, 6) NULL,
    macro_half_life_days     SMALLINT NULL,
    anomaly_score_z          NUMERIC(15, 6) NULL,
    prior_open               NUMERIC(8, 6) NULL,
    prior_hedge              NUMERIC(8, 6) NULL,
    prior_monitor            NUMERIC(8, 6) NULL,

    created_at               TIMESTAMP NOT NULL DEFAULT now(),

    CONSTRAINT uq_orchestrator_decision
        UNIQUE (date, contract_id, algorithm_version_id)
);

CREATE INDEX IF NOT EXISTS ix_orchestrator_decision_date_version
    ON pl_orchestrator_decision (date, algorithm_version_id);
```

### 4.3 `pl_external_indicator` — ENSO + FX daily values

```sql
CREATE TABLE IF NOT EXISTS pl_external_indicator (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date               DATE NOT NULL,
    -- ENSO (monthly publication, date = 1st of month, applied lag policy at compute-time)
    enso_oni_month     NUMERIC(8, 4) NULL,
    enso_nino34_anomaly NUMERIC(8, 4) NULL,        -- renamed from enso_nino34_month for clarity
    -- FX (daily business-days)
    fx_dxy_proxy       NUMERIC(15, 6) NULL,
    fx_gbpusd          NUMERIC(15, 6) NULL,
    fx_eurusd          NUMERIC(15, 6) NULL,         -- audit alias (= 1/usd_per_eur)
    fx_gbpeur          NUMERIC(15, 6) NULL,         -- audit raw
    created_at         TIMESTAMP NOT NULL DEFAULT now(),

    CONSTRAINT uq_external_indicator UNIQUE (date)
);

CREATE INDEX IF NOT EXISTS ix_external_indicator_date ON pl_external_indicator (date);
```

Note: not keyed on `contract_id` because ENSO and FX are commodity-agnostic. Stored once per date, joined to `pl_contract_data_daily` at compute time. **Migration mutualisée par les 2 USs [P1-scraper-enso.md](../user-stories/P1-scraper-enso.md) + [P1-scraper-fx.md](../user-stories/P1-scraper-fx.md)** — créée une fois, écritures partielles UPSERT par chaque scraper sur ses colonnes respectives.

### 4.4 `pl_cot_eu_weekly` (NEW 2026-05-19) — ICE COT EU positioning

Schéma complet documenté dans [P1-scrapers-stock-cot-eu.md §4.1](../user-stories/P1-scrapers-stock-cot-eu.md). Résumé :
- Weekly granularity (UPSERT sur `(release_date, contract_market)`)
- Toutes les catégories de positioning : Producer/Merchant, Managed Money, Other Reportables, Non-Reportable
- Colonnes générées Postgres : `prod_merc_net = prod_merc_long - prod_merc_short`, `m_money_net = m_money_long - m_money_short`
- Total OI pour normalisation %OI
- Z-scores 26w + percentiles **PAS** stockés ici — calculés en compute-time par l'engine ensemble (rule north-star "rolling normalization")
- Multi-market ready via `contract_market` (default 'cocoa')

### 4.5 `pl_model_artifact` (NEW 2026-05-19) — DB-stored ML artifacts (replaces GCS)

```sql
CREATE TABLE IF NOT EXISTS pl_model_artifact (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    algorithm_version_id  UUID NOT NULL REFERENCES pl_algorithm_version(id),
    artifact_type         VARCHAR(50) NOT NULL,
        -- 'specialist' | 'anomaly_veto' | 'structural_priors' | 'regime_clusters' | 'db_master_fundamentals'
    artifact_name         VARCHAR(64) NOT NULL,
        -- 'exp_optim_011' | 'anomaly_veto' | 'db_master_2026Q1' | ...
    period_label          VARCHAR(20) NULL,
        -- '2026-05' (monthly retrains) | 'yearly-2026' (long-run) | 'snapshot-2026-05-19' (Db_Master)
    artifact_format       VARCHAR(20) NOT NULL,
        -- 'pickle' | 'json'
    artifact_data         BYTEA NOT NULL,             -- the model bytes (typically 1-5 MB)
    sha256_hash           CHAR(64) NOT NULL,          -- audited at load
    n_train               INTEGER NULL,
    class_balance         JSONB NULL,
    git_sha               VARCHAR(40) NULL,           -- code SHA at retrain time
    fit_metadata          JSONB NULL,                 -- HPs, window dates, etc.
    created_at            TIMESTAMP NOT NULL DEFAULT now(),

    CONSTRAINT uq_model_artifact UNIQUE (algorithm_version_id, artifact_type, artifact_name, period_label)
);

CREATE INDEX IF NOT EXISTS ix_model_artifact_lookup
    ON pl_model_artifact (algorithm_version_id, artifact_type, period_label);
```

**Why DB and not GCS** (north-star rationale) :
- **Config as data** : artifacts vivent au même endroit que les versions/configs qui les référencent (`pl_algorithm_version` FK)
- **Single auth + backup + rollback** : un seul système (PG), un seul `pg_dump`, un seul `UPDATE pl_algorithm_version SET is_active=FALSE` pour rollback
- **No external coupling** : pas de WIF SA write, pas de bucket à provisionner, pas de manifest.json séparé à maintenir
- **SHA-256 in-band** : audité directement au load via une seule query
- **Volumes négligeables** : 14 specialists × ~3-5MB + 4 long-run × ~5-20MB = ~50-100 MB/mois. PostgreSQL BYTEA gère trivialement (TOAST automatique). 1 GB/an de backup additionnel = peanut.

**Trade-offs** :
- Backups DB un peu plus lourds (acceptable jusqu'à ~5 GB/an d'artifacts).
- Pas le pattern "MLflow-style" → décliné car 14 modèles versionnés mensuellement n'en ont pas besoin.
- Si C5 scale à 50+ modèles ou GB/mois → réévaluer GCS + artifact-registry.

### 4.6 Algorithm version + config seed rows

A single `pl_algorithm_version` row + a handful of `pl_algorithm_config` rows for top-level orchestrator + wrapper params. **Per-specialist HPs + ML model bytes are NOT stored here** — they live in `pl_model_artifact` rows (§4.5 + §7), keyed by the same `algorithm_version_id` (FK). The compute job joins on `algorithm_version_id` to retrieve both the params (config) and the binaries (artifacts) atomically.

```sql
-- NOTE: Hedi 2026-05-17 directive — day-1 promotion, NO parallel run.
-- This INSERT is part of the §8.1 launch transaction (with the existing-version
-- demote UPDATE). See §8.3 for the binding pre-launch gates.
INSERT INTO pl_algorithm_version (id, name, version, horizon, is_active, compute_enabled, description)
VALUES (gen_random_uuid(),
        'ensemble_v1_softgate_wrapper', '1.0.0', 'short_term',
        TRUE, TRUE,                              -- LIVE from day 1 (Hedi 2026-05-17)
        'C4/C5 ensemble: 14 monthly-retrained specialists + soft-gate Bayesian + transition-protection wrapper. In-sample gate-passing config from EXP-OPTIM-025 (2026-05-17). Day-1 promotion.');

INSERT INTO pl_algorithm_config (id, algorithm_version_id, parameter_name, value, description)
SELECT gen_random_uuid(), v.id, kv.k, kv.v, kv.d
FROM pl_algorithm_version v,
     (VALUES
        ('alpha_macro', '1.4770', 'soft-gate macro factor intensity'),
        ('alpha_prior', '0.1664', 'soft-gate prior factor intensity'),
        ('alpha_anomaly', '0.7219', 'soft-gate anomaly factor intensity (AV-001 polarity: positive)'),
        ('commit_threshold', '0.2493', 'soft-gate commit threshold on |net_score|'),
        ('wrapper_use_running_acc', '1', 'TPW-001 detector A active'),
        ('wrapper_tau_run', '0.5931', 'TPW-001 running-accuracy gate threshold'),
        ('wrapper_running_window', '3', 'TPW-001 running-accuracy window (trading days)'),
        ('wrapper_min_running_n', '2', 'TPW-001 minimum committed days in window'),
        ('wrapper_use_cluster_dispersion', '1', 'TPW-001 detector C active'),
        ('wrapper_min_cluster_n', '2', 'TPW-001 minimum committed votes per cluster'),
        ('wrapper_use_trend_conflict', '0', 'TPW-001 detector B INACTIVE'),
        ('wrapper_use_three_way_disagreement', '0', 'TPW-001 detector D INACTIVE'),
        -- Artifact location: replaced GCS bucket with pl_model_artifact DB table (2026-05-19, see §4.5 + §7).
        -- The compute job queries pl_model_artifact WHERE algorithm_version_id = <this version> AND artifact_type = ...
        -- No URI strings stored in config; the FK is the algorithm_version_id itself.
        -- Specialist→cluster mapping (rule #5 compliance; Hedi 2026-05-17 directive).
        -- Replaces the WINTER_SPECIALISTS/SPRING_SPECIALISTS hardcode in
        -- methodology/orchestrator/transition_wrapper.py:53.
        -- Wrapper loader reads these at job start and builds the in-memory mapping.
        ('cluster_exp_optim_002', 'winter', 'specialist cluster membership'),
        ('cluster_exp_optim_005', 'winter', 'specialist cluster membership'),
        ('cluster_exp_optim_006', 'winter', 'specialist cluster membership'),
        ('cluster_exp_optim_011', 'winter', 'specialist cluster membership'),
        ('cluster_xpol_W_TB_garch', 'winter', 'specialist cluster membership'),
        ('cluster_xpol_W_TB_macro', 'winter', 'specialist cluster membership'),
        ('cluster_exp_optim_017_bear_4', 'spring', 'specialist cluster membership'),
        ('cluster_exp_optim_017_bear_8', 'spring', 'specialist cluster membership'),
        ('cluster_exp_optim_017_bull_4', 'spring', 'specialist cluster membership'),
        ('cluster_exp_optim_017_bull_5', 'spring', 'specialist cluster membership'),
        ('cluster_exp_optim_017_bull_7', 'spring', 'specialist cluster membership'),
        ('cluster_exp_optim_017_bull_8', 'spring', 'specialist cluster membership'),
        ('cluster_xpol_S_bull_garch_fx', 'spring', 'specialist cluster membership'),
        ('cluster_xpol_S_bear_garch_macro', 'spring', 'specialist cluster membership')
     ) AS kv(k, v, d)
WHERE v.name = 'ensemble_v1_softgate_wrapper' AND v.version = '1.0.0';
```

---

## 5 — New scrapers (ENSO + FX)

### 5.1 `cc-enso-scraper` (NOAA ONI + Niño 3.4, monthly cadence)

- **Source**: NOAA CPC (`https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt` + Niño 3.4 SST anomaly). Free, public, no auth.
- **Cadence**: NOAA publishes ~mid-month for the previous month. Run **monthly on the 20th day at 22:00 UTC** to ensure publication. Carry-forward the previous month's value to every daily row until the new publication.
- **Memory**: 512 Mi (lightweight HTTP fetch + parse).
- **Writes**: `pl_external_indicator.enso_oni_month`, `enso_nino34_month` (UPSERT — fail loud per rule #1 if response empty or malformed).
- **Scaffold**: `backend/scripts/enso_scraper/{__init__.py, enso_scraper.py, cli.py}`.

### 5.2 `cc-fx-scraper` (ECB SDMX USD/EUR + GBP/EUR, daily cadence)

- **Source**: ECB SDMX 2.1 (`https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A` + `D.GBP.EUR.SP00.A`). Free, public, no auth.
- **Cadence**: daily weekdays at 18:30 UTC (ECB publishes ~16:00 CET — well before).
- **Memory**: 512 Mi.
- **Writes**: `pl_external_indicator.fx_dxy_proxy` (computed from USD/EUR), `fx_gbpusd`, `fx_eurusd`, `fx_gbpeur` (UPSERT).
- **Scaffold**: `backend/scripts/fx_scraper/{__init__.py, fx_scraper.py, cli.py}`.

Both scrapers wire into the deployment pattern from R&D doc §5.C steps 1-7.

---

## 6 — New Cloud Run Jobs

### 6.1 `cc-ensemble-monthly-retrain` (per-month, refit 14 specialists)

**Schedule**: 1st trading day of each month at **17:00 UTC** (before the daily compute window). On non-trading-day 1sts, skip and run on day 2.

```hcl
ensemble_monthly_retrain = {
  description = "Refit Campaign 5 ensemble specialists on rolling N-month windows (N varies per specialist's min_window_months)"
  schedule    = "0 17 1-3 * 1-5"   # try day 1-3 of each month, scraper de-dupes
}
```

**What it does**:
1. Load full historical `pl_contract_data_daily` (front-month-by-OI continuity via the existing `runner.load_all_market_data()` SQL pattern) + ENSO/FX/macro features.
2. For each of the 14 specialists, slice the rolling window per `min_window_months`, refit on the slice using the Optuna top-1 HPs.
3. Serialize via `pickle` → **INSERT into `pl_model_artifact`** with `artifact_type='specialist'`, `artifact_name=<specialist_name>`, `period_label='<YYYY-MM>'`, computed SHA-256 + `fit_metadata` JSONB (n_train, class balance, retrain timestamp, git SHA).
4. UPSERT semantics : refit du même `(algorithm_version, type, name, period)` écrase l'ancien. Pour conserver l'historique → `period_label='<YYYY-MM>-rerun-001'`.
5. Validate non-regression: if any specialist's resulting class balance has any class >70% (per Campaign 5 audit logic), tag the specialist as `imbalanced=true` in `fit_metadata`. Operator alert via Cloud Logging WARN (not ERROR — imbalance is a finding, not a failure).
6. **Fail loud** (rule #1) on any I/O / fit / DB error; exit non-zero.

**Memory**: 2 Gi (LightGBM + RF fits on 4000-row windows × 14 specialists, GARCH refit for 4 specialists).

### 6.2 `cc-ensemble-compute` (daily, run the orchestrator)

**Schedule**: daily weekdays at **18:00 UTC** (between barchart-scraper at 19:00 — wait, BEFORE that. Let me re-check…).

Looking at the R&D doc §2 schedule:
- 19:00 UTC: barchart-scraper writes today's `pl_contract_data_daily` (OHLCV+IV).
- 19:05 UTC: ICE/CFTC scrapers + press_review_agent update.
- 19:15 UTC: compute-indicators writes `pl_derived_indicators` + `pl_indicator_daily` (legacy).
- 19:20 UTC: daily-analysis updates `pl_indicator_daily.decision`.
- 19:30 UTC: compass-brief.

Our orchestrator depends on `pl_derived_indicators` (today's row) + `pl_article_segment` (today's row) + `pl_external_indicator` (today's row, populated by fx-scraper at 18:30). So:

**Schedule**: **19:18 UTC weekdays** (`18 19 * * 1-5`). After compute-indicators (19:15 + ~3 min runtime), before daily-analysis (19:20).

```hcl
ensemble_compute = {
  description = "C5 ensemble: 14-specialist soft-gate + transition-protection wrapper writes pl_indicator_daily for ensemble_v1_softgate_wrapper"
  schedule    = "18 19 * * 1-5"
}
```

**What it does** (top-down):
1. Resolve active contract via `resolve_active_code()` / `resolve_active_contract_id()` (rule #2).
2. Look up `pl_algorithm_version` for `name='ensemble_v1_softgate_wrapper'` AND `compute_enabled=TRUE`. Pull `pl_algorithm_config` rows for soft-gate + wrapper params + artifact URIs.
3. Pull current month's specialist model artifacts from `pl_model_artifact` (`SELECT artifact_data FROM pl_model_artifact WHERE algorithm_version_id = :v AND artifact_type = 'specialist' AND period_label = '<YYYY-MM>'`). Verify SHA-256 against `sha256_hash` column ; fail loud if mismatch (§7.2 loader contract).
4. Pull long-run frozen artifacts from `pl_model_artifact` (`anomaly_veto`, `structural_priors`, `regime_clusters`, `db_master_fundamentals` — `artifact_type` filter, no `period_label` constraint, take latest by `created_at DESC`).
5. Load today's row from `pl_contract_data_daily` + `pl_derived_indicators` + `pl_external_indicator` + the trailing 252 rows for warmup.
6. For each specialist: compute feature matrix, predict_label → vote.
7. Compute context: macro direction/surprise/half-life from `pl_article_segment` aggregation; anomaly z-score from IsolationForest; structural prior from regime/vol/ret terciles; regime cluster weights from monthly state vector.
8. Apply `SoftGateOrchestrator.decide()`: returns net_score + decision + per-specialist weights.
9. Apply `TransitionProtectionWrapper.apply()`: needs prior `pl_orchestrator_decision` rows (running_acc) + today's specialist votes (cluster dispersion) + last-5-day cocoa returns. **Bootstrap**: on day 1 of activation, `running_acc_5d` is NaN → wrapper detector A doesn't fire (matches R&D `_running_acc` logic with `min_running_n=2`).
10. UPSERT `pl_specialist_prediction` (14 rows), `pl_orchestrator_decision` (1 row), `pl_indicator_daily` (1 row: only `decision`, `confidence`, `direction` populated; engine columns NULL).
11. **Fail loud** (rule #1) on any artifact-load / inference / write error.

**Memory**: 1 Gi (14 inferences, no fitting).

### 6.3 Updated overall schedule

| Cron (UTC) | Job | Memory | Notes |
|---|---|---|---|
| `0 17 1-3 * 1-5` | **cc-ensemble-monthly-retrain** | 2 Gi | NEW — 1st trading day of month |
| `30 18 * * 1-5` | **cc-fx-scraper** | 512 Mi | NEW — daily |
| `0 22 20 * 1-5` | **cc-enso-scraper** | 512 Mi | NEW — monthly day-20 |
| `0 19 * * 1-5` | cc-barchart-scraper | 2 Gi | unchanged |
| `0 19 * * 1-5` | cc-meteo-agent | 1 Gi | unchanged |
| `5 19 * * 1-5` | cc-ice-stocks-scraper | 512 Mi | unchanged |
| `5 19 * * 1-5` | cc-cftc-scraper | 512 Mi | unchanged |
| `5 19 * * 1-5` | cc-press-review-agent | 1 Gi | unchanged |
| `15 19 * * 1-5` | cc-compute-indicators | 1 Gi | unchanged (writes legacy + ensemble's `pl_derived_indicators` shared cols) |
| `18 19 * * 1-5` | **cc-ensemble-compute** | 1 Gi | NEW — between compute-indicators and daily-analysis |
| `20 19 * * 1-5` | cc-daily-analysis | 1 Gi | UNCHANGED but must verify it does NOT overwrite ensemble version (Q3) |
| `30 19 * * 1-5` | cc-compass-brief | 1 Gi | unchanged |

---

## 7 — Artifact management strategy (DB-stored, no GCS)

> **REVISED 2026-05-19** : replaces the original GCS bucket approach with DB-stored artifacts in `pl_model_artifact` (§4.5). Aligned with north-star "config as data" + simpler ops.

### 7.1 Storage layout — `pl_model_artifact` rows

Each ML artifact = one row in `pl_model_artifact`, keyed on `(algorithm_version_id, artifact_type, artifact_name, period_label)`. No filesystem, no bucket, no external manifest file.

```
pl_model_artifact rows (logical view) :
┌─────────────────────────────────────────────────────────────────────────────┐
│ Specialists (monthly retrain, 14 rows/month)                                │
│ ┌──────────────────────┬──────────────────┬──────────┬──────────────────┐  │
│ │ algorithm_version_id │ artifact_type    │ ..._name │ period_label     │  │
│ │ <ensemble v1 UUID>   │ 'specialist'     │ exp_optim_002  │ '2026-05'  │  │
│ │ <ensemble v1 UUID>   │ 'specialist'     │ exp_optim_005  │ '2026-05'  │  │
│ │ ...                  │ ...              │ ...            │ ...        │  │
│ │ <ensemble v1 UUID>   │ 'specialist'     │ xpol_S_bear_garch_macro │ '2026-05' │
│ └──────────────────────┴──────────────────┴────────────────┴────────────┘  │
│                                                                             │
│ Long-run frozen (yearly refit, 4 rows/year)                                 │
│ ┌──────────────────────┬──────────────────────────────┬──────────┬─────┐    │
│ │ <ensemble v1 UUID>   │ 'anomaly_veto'               │ ...     │'yearly-2026'│
│ │ <ensemble v1 UUID>   │ 'structural_priors'          │ ...     │'yearly-2026'│
│ │ <ensemble v1 UUID>   │ 'regime_clusters'            │ ...     │'yearly-2026'│
│ │ <ensemble v1 UUID>   │ 'db_master_fundamentals'     │ ...     │'snapshot-2026-05-19'│
│ └──────────────────────┴──────────────────────────────┴─────────┴─────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

Each row contains :
- `artifact_data BYTEA` : the actual pickle/JSON bytes
- `sha256_hash CHAR(64)` : computed at write time, verified at read time
- `fit_metadata JSONB` : HPs, window dates, n_train, class balance, code git SHA
- `created_at TIMESTAMP` : audit trail

### 7.2 Loader contract (compute job)

`cc-ensemble-compute` reads artifacts via :

```python
def load_artifact(session, algo_version_id, artifact_type, artifact_name, period_label):
    row = session.execute(text("""
        SELECT artifact_data, sha256_hash, artifact_format, fit_metadata
        FROM pl_model_artifact
        WHERE algorithm_version_id = :v
          AND artifact_type = :t
          AND artifact_name = :n
          AND (period_label = :p OR (period_label IS NULL AND :p IS NULL))
    """), {"v": algo_version_id, "t": artifact_type, "n": artifact_name, "p": period_label}).fetchone()

    if row is None:
        raise FileNotFoundError(f"Artifact missing: {artifact_type}/{artifact_name}/{period_label}")

    # SHA-256 verification (rule #1 fail-loud)
    actual_sha = hashlib.sha256(row.artifact_data).hexdigest()
    if actual_sha != row.sha256_hash:
        raise IntegrityError(f"SHA-256 mismatch: {artifact_type}/{artifact_name} expected={row.sha256_hash} actual={actual_sha}")

    # Deserialize
    if row.artifact_format == "pickle":
        return pickle.loads(row.artifact_data)
    elif row.artifact_format == "json":
        return json.loads(row.artifact_data.decode("utf-8"))
    raise ValueError(f"Unknown format: {row.artifact_format}")
```

### 7.3 Writer contract (monthly retrain job)

`cc-ensemble-monthly-retrain` writes via :

```python
def write_artifact(session, algo_version_id, artifact_type, artifact_name, period_label, model, format="pickle", metadata=None):
    data = pickle.dumps(model) if format == "pickle" else json.dumps(model).encode("utf-8")
    sha = hashlib.sha256(data).hexdigest()

    session.execute(text("""
        INSERT INTO pl_model_artifact (
            algorithm_version_id, artifact_type, artifact_name, period_label,
            artifact_format, artifact_data, sha256_hash, fit_metadata
        ) VALUES (:v, :t, :n, :p, :f, :d, :h, :m)
        ON CONFLICT (algorithm_version_id, artifact_type, artifact_name, period_label)
        DO UPDATE SET artifact_data = EXCLUDED.artifact_data,
                      sha256_hash = EXCLUDED.sha256_hash,
                      fit_metadata = EXCLUDED.fit_metadata,
                      created_at = now()
    """), {...})
```

UPSERT semantics : refit du même `(version, type, name, period)` écrase l'ancien. Si on veut conserver l'historique → utiliser un `period_label` différent (e.g., `2026-05-rerun-001`).

### 7.4 Bootstrapping (the first month) — manual

Before the first scheduled monthly retrain in prod, manually insert the R&D-trained artifacts into `pl_model_artifact` :

```bash
# Operator runs locally (against prod via bastion tunnel)
poetry run ensemble-bootstrap-artifacts \
  --algorithm-version ensemble_v1_softgate_wrapper@1.0.0 \
  --rd-output-dir /path/to/RnD_Compass/output/ \
  --month 2026-05 \
  [--dry-run] [--verify-sha]
```

The bootstrap script :
1. Reads R&D pickle files from `output/exp_optim_018c__<specialist>/` × 14
2. Reads long-run artifacts from `output/exp_optim_020/`, `output/exp_optim_021b/`
3. Reads Db_Master snapshot from `data/external_data/Db_Master_*.xlsx` (computed to lookup table, pickled)
4. INSERT into `pl_model_artifact` with computed SHA-256
5. Outputs a summary : `14 specialists + 4 long-run = 18 rows inserted, total bytes ~50 MB`

`cc-ensemble-compute --dry-run` against local DB sync verifies end-to-end before flipping `compute_enabled=TRUE`.

### 7.5 Long-run yearly refit (deferred to 2027)

- Yearly refit of `anomaly_veto`, `structural_priors`, `regime_clusters` is scheduled for **2027-01** (first trading day). Db_Master refit happens ponctuellement sur livraison XLS (manual `ensemble-bootstrap-artifacts --period-label snapshot-YYYY-MM-DD`).
- For deployment NOW, the R&D 2026-05-17 artifacts (uploaded at bootstrap §7.4) are sufficient (10y window 2016-2025).
- DEFERRED : scaffold for the yearly job is documented but not built in this deployment.

### 7.6 Storage budget

| Item | Size/unit | Frequency | Annual storage |
|---|---|---|---|
| 14 specialists | ~3-5 MB | Monthly | ~50-70 MB × 12 = ~600-840 MB |
| 3 long-run (anomaly, priors, regime) | ~5-20 MB | Yearly | ~30-60 MB |
| Db_Master fundamentals | ~1 MB | Ponctuel (~2/year) | ~2 MB |
| **Total** | | | **~700 MB/year** |

Retention policy (TBD post-MVP) : conserver les 12 derniers mois + tous les long-run + tous les Db_Master. Purge automatique au-delà via job mensuel (post-MVP).

PostgreSQL stockage actuel (`pl_*` + `ref_*` + `aud_*`) ~5 GB. Ajouter ~700 MB/an = peanut.

---

## 8 — Algorithm versioning + day-1 promotion (Hedi decision 2026-05-17)

> **User mandate**: skip the 20-day parallel-run; promote `is_active=TRUE` on day 1.
>
> The in-sample-tuning caveat is accepted by Hedi as the deployment stakeholder. To compensate for the lack of parallel-run safety net, the binding gates move LEFT to pre-launch (every verification gate in §14 below MUST pass before `is_active=TRUE` is written) AND a wrapper bootstrap pre-seed is added (§8.2) to prevent day-1 underprotection.

### 8.1 Activation procedure

A SINGLE transaction at launch. Rollback is one UPDATE (see §10.2).

```sql
BEGIN;

-- Insert the version with is_active=TRUE from day 1
INSERT INTO pl_algorithm_version (id, name, version, horizon, is_active, compute_enabled, description)
VALUES (gen_random_uuid(),
        'ensemble_v1_softgate_wrapper', '1.0.0', 'short_term',
        TRUE, TRUE,                              -- live from day 1
        'C4/C5 ensemble: 14 monthly-retrained specialists + soft-gate Bayesian + transition-protection wrapper. In-sample gate-passing config from EXP-OPTIM-025 (2026-05-17). Day-1 promotion per Hedi 2026-05-17.');

-- Demote whatever was previously active (typically 'legacy')
UPDATE pl_algorithm_version
   SET is_active = FALSE
 WHERE is_active = TRUE
   AND name <> 'ensemble_v1_softgate_wrapper';

-- Seed config rows (specialist→cluster mapping + soft-gate + wrapper params)
-- See §4.4 (soft-gate + wrapper) + §13.X (cluster mapping)

COMMIT;
```

The dashboard's TanStack Query reads will refresh on next refetch (24h staleTime). After the transaction commits, the next user-load shows the ensemble decision.

### 8.2 Wrapper bootstrap (CRITICAL — day-1 protection)

**The problem**: the wrapper's `running_acc` detector (detector A) needs prior `pl_orchestrator_decision` rows to compute the trailing-5-day committed accuracy. On day 1 in prod, there are zero prior rows → `running_acc_5d = NaN` → detector A doesn't fire → wrapper is partially disabled for the first ~5 trading days. The `cluster_dispersion` detector (C) still works, but Detector A was the dominant signal (fired 32 of 82 days on the Jan-Apr 2026 validation; C fired 12 days).

**The fix**: pre-seed `pl_orchestrator_decision` rows with the R&D-historical orchestrator outputs for the last 5 trading days before launch. The wrapper then has data from day 1.

```sql
-- Operator-driven seed BEFORE the activation transaction.
-- Insert orchestrator decision rows from R&D historical CSVs
-- (output/exp_optim_025/wrapped_decisions.csv columns).
-- IMPORTANT: contract_id must be the contract_id corresponding to the
-- session date (use front-month-by-OI continuity from pl_contract_data_daily).

INSERT INTO pl_orchestrator_decision
    (date, contract_id, algorithm_version_id,
     soft_gate_decision, net_score, weights_sum, n_committed_specialists,
     decision_wrapped, wrapper_active,
     fired_running_acc, fired_trend, fired_dispersion, fired_three_way,
     running_acc_5d, realized_return_5d, winter_vote_signed, spring_vote_signed,
     macro_direction, macro_surprise, macro_half_life_days,
     anomaly_score_z, prior_open, prior_hedge, prior_monitor)
SELECT  -- row-by-row from R&D wrapped_decisions.csv for trailing-5 trading days
        ...
```

Concretely: take the 5 trading days from `output/exp_optim_025/wrapped_decisions.csv` immediately before the launch date, run the front-month-by-OI lookup to bind each to a `contract_id` in prod, INSERT.

This is the ONE non-trivial operational step at launch. Allow 30 min for the operator to assemble + run the seed SQL.

### 8.3 Pre-launch gates (BINDING, replace the parallel-run audit)

All gates in §14 MUST pass before the activation transaction is executed:

1. ✓ Dry-run reproducibility (2 runs, bit-for-bit diff)
2. ✓ 5-day spot-check against R&D outputs
3. ✓ Schema round-trip test (NULLs not zeros)
4. ✓ Fail-loud test (missing artifact → non-zero exit + ERROR log)
5. ✓ Contract-roll dry-run
6. ✓ Daily-analysis non-interference test
7. ✓ Wrapper bootstrap pre-seed completed (§8.2)
8. ✓ Q1-Q8 prerequisites in §3 answered + resolved

If any of these 8 gates fails, deployment is HALTED. Operator addresses + retries.

---

## 9 — Migration plan (step-by-step ordered timeline)

### Day 0 — pre-flight (Hedi answers Q1-Q8)

- Confirm prerequisites §3 (Q1, Q3, Q4, Q6 already resolved 2026-05-19 ; Q5, Q7, Q8 pending Sprint 1 spike).
- Pin scientific dependency versions in `backend/Dockerfile.jobs` to match R&D (`pyproject.toml` constraints).
- ~~Provision GCS bucket~~ — no longer required (replaced by `pl_model_artifact` table, §4.5).

### Day 1-2 — code merge: ensemble engine module + scrapers

**PR 1**: schema migrations (§4 — 4 new tables : `pl_external_indicator`, `pl_cot_eu_weekly`, `pl_model_artifact`, `pl_specialist_prediction` + `pl_orchestrator_decision`) + ENSO scraper + FX scraper + COT EU scraper. Code review against rules #1-5. CI green. Merge → terraform apply provisions the new scheduler entries. **No bucket provisioning** (replaced by DB table).

**PR 2**: `backend/app/engine/ensemble/` module — direct port of the R&D modules (§2.5). Tests:
- Unit tests for each specialist (table-driven, ≥80% coverage).
- Integration test: load fake `pl_contract_data_daily` slice + ENSO + FX + macro + frozen long-run → expect specific decision on a fixture day.
- Reproducibility test: run inference twice on the same fixture, assert bit-for-bit identical outputs.

**PR 3**: `cc-ensemble-monthly-retrain` + `cc-ensemble-compute` jobs (§6) — `backend/scripts/ensemble_monthly_retrain/`, `backend/scripts/ensemble_compute/`. Tests target dry-run mode end-to-end.

### Day 3 — manual artifact bootstrap

- Run `poetry run ensemble-bootstrap-artifacts --algorithm-version ensemble_v1_softgate_wrapper@1.0.0 --rd-output-dir /path/to/RnD_Compass/output/ --month 2026-05 [--verify-sha]` (§7.4).
- This INSERTs into `pl_model_artifact` : 14 specialist rows (period='2026-05') + 3 long-run rows (period='yearly-2026') + 1 Db_Master row (period='snapshot-2026-05-19'). Total ~18 rows, ~50 MB BYTEA.
- SHA-256 captured at write time + audited at first load.
- Local `cc-ensemble-compute --dry-run` against synced prod data: verify decision matches the R&D system's would-be Jan-Apr 2026 output day-by-day for at least 5 spot-checks.

### Day 4 — ENSO + FX backfill

- One-time historical backfill: pull 10y of NOAA ONI + ECB FX → seed `pl_external_indicator`. Validate against R&D CSVs (`data/external_data/ENSO/`, `data/external_data/FX/`) for exact value match.

### Day 5 (or whenever §8.3 gates all green) — LAUNCH

> Day-1 promotion per Hedi 2026-05-17. The 8 pre-launch gates in §8.3 are the ONLY safety net.

1. Verify the 8 pre-launch gates (§8.3) all pass on staging.
2. Run wrapper bootstrap pre-seed (§8.2) — INSERT 5 trailing-day `pl_orchestrator_decision` rows from R&D CSV mapped to prod contract_ids.
3. Execute the activation transaction (§8.1) — INSERT new version row with `is_active=TRUE`, demote legacy.
4. First scheduled `cc-ensemble-compute` runs at 19:18 UTC — produces today's decision row, which IS the user-visible decision from the next dashboard refresh.
5. Operator stands by during the launch-day run; runs the audit query (§10.1) at 19:30 UTC; confirms no Sentry errors; confirms the dashboard renders OPEN/HEDGE/MONITOR correctly.

### Day 6-25 — live operation with intensive monitoring

- Daily audit (§10.1) email/slack to operator at 19:35 UTC.
- Per-day forward-return-rolling accuracy reviewed once forward returns become available (t+6).
- Weekly Hedi review.
- Any FATAL → immediate rollback to L2 (§10.2): flip is_active back to legacy.

### Day 26 — first monthly retrain in prod

- `cc-ensemble-monthly-retrain` runs at 17:00 UTC on the 1st trading day of the next month.
- Verify : 14 new rows inserted into `pl_model_artifact` (`period_label='2026-06'`), all SHA-256 fresh, `fit_metadata.git_sha` matches the deployed code.
- `cc-ensemble-compute` (19:18 UTC) reads the new month's models seamlessly via the DB query (`SELECT WHERE period_label = '2026-06'`).

### Day 27+ — ongoing operation

- Daily audit continues indefinitely.
- Monthly retrain continues monthly.
- Sentry alert configured on any non-zero exit of either job.

---

## 10 — Monitoring + rollback

### 10.1 Monitoring

- **Cloud Run logs**: every job execution. INFO line at start with run-id + active contract code + algorithm version_id + specialist artifact month. INFO at end with decision + n_committed_specialists + wrapper detectors fired (audit trail mirrors `pl_orchestrator_decision`).
- **Sentry**: errors at ERROR level with `service=cc-ensemble-compute` / `cc-ensemble-monthly-retrain` tag. Traces sampled 20% (matches existing pattern).
- **Daily audit query** (cron + email/slack via a new lightweight `cc-ensemble-audit` job, or manual `gcloud sql` query — Hedi's choice):
  ```sql
  -- Drift between ensemble and legacy
  SELECT date, e.decision AS ensemble, l.decision AS legacy,
         (e.decision = l.decision) AS agrees
  FROM pl_indicator_daily e
  JOIN pl_algorithm_version ev ON e.algorithm_version_id = ev.id
  JOIN pl_indicator_daily l ON l.date = e.date AND l.contract_id = e.contract_id
  JOIN pl_algorithm_version lv ON l.algorithm_version_id = lv.id
  WHERE ev.name = 'ensemble_v1_softgate_wrapper'
    AND lv.name = 'legacy' AND lv.is_active = TRUE
    AND e.date >= CURRENT_DATE - 30
  ORDER BY date DESC;
  ```
- **Rolling forward-return correctness** (auditable after day t+6):
  ```sql
  SELECT
    e.decision_wrapped,
    cd.close,
    LEAD(cd.close, 6) OVER (ORDER BY cd.date) AS close_t_plus_6,
    -- correctness derived from sign rule
    CASE
      WHEN e.decision_wrapped = 'HEDGE' AND LEAD(cd.close, 6) OVER (ORDER BY cd.date) < cd.close THEN 1
      WHEN e.decision_wrapped = 'OPEN'  AND LEAD(cd.close, 6) OVER (ORDER BY cd.date) > cd.close THEN 1
      WHEN e.decision_wrapped = 'MONITOR' THEN NULL
      ELSE 0
    END AS correct_or_null
  FROM pl_orchestrator_decision e
  JOIN pl_contract_data_daily cd ON cd.date = e.date AND cd.contract_id = e.contract_id
  WHERE e.date <= CURRENT_DATE - 6
  ORDER BY date DESC;
  ```

### 10.2 Rollback

Three rollback levels — pick the one that fits.

**L1 — Pause compute (operator sees a problem, wants to investigate without disabling)**:
```sql
UPDATE pl_algorithm_version SET compute_enabled = FALSE
 WHERE name = 'ensemble_v1_softgate_wrapper';
```
Next `cc-ensemble-compute` exits immediately (no-op). Job stays scheduled.

**L2 — Demote (post-promotion, ensemble had a bad day, flip dashboard back to legacy)**:
```sql
BEGIN;
UPDATE pl_algorithm_version SET is_active = FALSE
 WHERE name = 'ensemble_v1_softgate_wrapper';
UPDATE pl_algorithm_version SET is_active = TRUE
 WHERE name = 'legacy' AND version = (SELECT version FROM pl_algorithm_version
                                       WHERE name = 'legacy' ORDER BY created_at DESC LIMIT 1);
COMMIT;
```
Dashboard reverts on next refetch. `cc-ensemble-compute` continues running (so we can audit further).

**L3 — Full rollback (something is fundamentally broken, remove the version)**:
- Set both `compute_enabled=FALSE` and `is_active=FALSE` on the ensemble version.
- Pause `cc-ensemble-compute` + `cc-ensemble-monthly-retrain` schedulers via `gcloud scheduler jobs pause`.
- New tables (`pl_specialist_prediction`, `pl_orchestrator_decision`, `pl_external_indicator`) remain but no new rows written. Historical rows preserved for diagnostics.
- Code rollback: revert PRs in reverse order.

---

## 11 — Non-negotiable rules compliance audit

The 5 rules from R&D doc §0 + §8.

| # | Rule | C5 Compliance |
|---|---|---|
| 1 | Fail loud, no silent recovery | The R&D `MonthlyRetrainer.predict_month` raises on degenerate labels (single-class TB on short windows). The Phase 1 driver also raises now (we removed the silent try/except earlier — see `EXP-OPTIM-019` history). The orchestrator uses `min_running_n=2` and returns NaN for tiny windows, but does NOT silently swallow errors. **Need to AUDIT**: every `try/except` in the ported modules, ensure they re-raise or log+exit non-zero. |
| 2 | No hardcoded contract codes | The R&D code uses commodity name `'Cocoa'` not contract codes. Prod port must replace data-loader calls with `resolve_active_contract_id()` reads. The orchestrator decision is keyed on the active contract at job time. |
| 3 | Computed values must trace | All `pl_indicator_daily` columns we write are functions of inputs. `pl_orchestrator_decision` columns are computed in the wrapper/soft-gate. **No `0.0` placeholders**: where a value isn't computed (e.g., `running_acc_5d` on day 1 of activation, `realized_return_5d` on data start), we write `NULL`. Engine columns we don't compute (`indicator_value`, `momentum`, etc.) → `NULL`. Documented in §4.2. |
| 4 | Contract-centric | `pl_specialist_prediction` and `pl_orchestrator_decision` both have `(date, contract_id)` keys. `pl_external_indicator` is commodity-agnostic (keyed on date only — ENSO/FX don't have a contract dimension), joined at compute time. |
| 5 | Config as data | Soft-gate intensities + wrapper detector switches/thresholds → `pl_algorithm_config` rows (§4.6). **Per-specialist HPs + ML model bytes → `pl_model_artifact` rows (§4.5)** (revised 2026-05-19, replaces GCS bucket). All algorithm-related state lives in the DB ; the only "code" reference from `pl_algorithm_config` is to algorithm `name`+`version`. Specialist→cluster mapping (Winter/Spring) is HARDCODED in `transition_wrapper.py:53` in R&D — **moved to `pl_algorithm_config` in PR 2 per Hedi 2026-05-17** (§4.6 seed rows `cluster_<specialist_name>`). The prod port of `transition_wrapper.py` reads these at job start instead of importing the constants. Specialists added in future R&D campaigns are then DB-only no-deploy additions. **Stronger alignment with rule #5** : no external system (no GCS bucket, no manifest.json file) — single source of truth in PG. ✓ |

---

## 12 — Out of scope (this deployment)

- **LLM-on-line bull/bear amplifier**: deferred until `pl_article_segment` has enough bull-direction events to validate (per `MAC-002`).
- **Wrapper-architecture specialists** (MetaLabeling, SelectiveClassifier, ensembles): excluded from C5; future R&D campaign.
- **Multi-commodity generalisation** (coffee, sugar): ROADMAP Phase 5a.
- **Cockpit J+1 visualisation**: Julien's `NOTE_HEDI_2026-05-16.md` separate track.
- **Yearly long-run refit job**: not built in this deployment; manual operator-driven for first year (2027-01).

---

## 13 — Critical file paths reference

R&D source artifacts to port:
- `methodology/orchestrator/{soft_gate.py,transition_wrapper.py,learned_moe.py}` (learned_moe excluded per `ME-001`)
- `methodology/long_run/{anomaly_veto.py,structural_priors.py,regime_similarity.py}`
- `methodology/macro_events/pipeline.py`
- `methodology/retrain/monthly_retrainer.py`
- `methodology/optimizer/specialists.py` (registry of 14)
- `methodology/models/{base,spot,momentum,fundamentals,meta,meta_labeling,sklearn_candidate,multi_horizon_ensemble,selective_classifier,regime_moe}.py`
- `methodology/features.py`, `methodology/features_external.py`, `methodology/features_garch.py`
- `methodology/targets.py`, `methodology/targets_calibrated.py`, `methodology/targets_triple_barrier.py`
- `methodology/training_utils/anti_bias.py`
- `methodology/external_data.py` (for unit-tested ENSO/FX merge logic)
- `methodology/optimizer/objective.py` (the `_build_candidate` factory)

Frozen artifacts to import into `pl_model_artifact` (via `ensemble-bootstrap-artifacts`, §7.4):
- `output/exp_optim_018c__<14_specialists>/top1_config.json` × 14
- `output/exp_optim_020/anomaly_veto.pkl`
- `output/exp_optim_020/structural_priors.json`
- `output/exp_optim_021b/regime_clusters.json`
- `output/exp_optim_022/tuned_configs.json` (use Fold B params only)
- `output/exp_optim_025/tuned_config.json`

Prod target paths (commodities-compass repo):
- `backend/app/engine/ensemble/` (new package mirroring R&D modules)
- `backend/scripts/{enso_scraper,fx_scraper,ensemble_compute,ensemble_monthly_retrain,ensemble_bootstrap_artifacts}/`
- `backend/alembic/versions/<ts>_add_pl_external_indicator.py`
- `backend/alembic/versions/<ts>_add_pl_cot_eu_weekly.py`
- `backend/alembic/versions/<ts>_add_pl_model_artifact.py`
- `backend/alembic/versions/<ts>_add_pl_specialist_prediction_orchestrator_decision.py`
- `infra/terraform/scheduler.tf` (entries from §6.3)
- `.github/workflows/deploy.yml` (4 new `deploy_job` lines, NO new bucket terraform)
- `backend/app/core/config.py` (Pydantic settings if new env vars)
- `backend/app/models/pipeline.py` (4 new ORM models : `PlExternalIndicator`, `PlCotEuWeekly`, `PlModelArtifact`, `PlSpecialistPrediction`, `PlOrchestratorDecision`)
- `CLAUDE.md` (repo root) — append §2 pipeline schedule with the 4 new jobs
- `docs/runbooks/ensemble-recovery.md` (NEW — manual relaunch + rollback)

**REMOVED (versus original plan)** :
- ~~`infra/terraform/{secrets,buckets,iam}.tf` (GCS bucket + WIF SA write)~~ — replaced by `pl_model_artifact` DB table (no GCS provisioning required).

---

## 14 — Verification end-to-end

Before considering deployment complete:

1. **Dry-run reproducibility**: run `cc-ensemble-compute --dry-run` twice on the same synced prod DB snapshot, diff outputs → bit-for-bit identical (excluding timestamps). Same for monthly retrainer.
2. **Spot-check 5 historical days**: for 5 days from Jan-Apr 2026, run the prod compute path on synced data and confirm `decision_wrapped` matches the R&D `output/exp_optim_025/wrapped_decisions.csv` row for the same date. Any mismatch is a porting bug.
3. **Schema round-trip**: write a test that loads a `pl_orchestrator_decision` row back via SQLAlchemy and confirms every NULLable field is properly NULL (not `0.0`) where the computation produced NaN.
4. **Fail-loud test**: deliberately DELETE a specialist row from `pl_model_artifact` in staging (`DELETE FROM pl_model_artifact WHERE artifact_name = 'exp_optim_011' AND period_label = '2026-05'`), run `cc-ensemble-compute` → expect non-zero exit + ERROR-level log naming the missing artifact. Also test SHA mismatch : `UPDATE pl_model_artifact SET sha256_hash = 'wrong' WHERE id = ...` → fail-loud.
5. **Contract-roll dry-run**: simulate a contract roll (UPDATE `ref_contract.is_active` on a staging DB), run compute → verify the new contract_id is on the written rows.
6. **Daily-analysis non-interference**: after running `cc-ensemble-compute`, run `cc-daily-analysis` (assuming Q3 confirms it skips our version_id), verify our `pl_indicator_daily.decision` row is unchanged.

These six gates are the binding "deployment is GO" criteria, in addition to §8.2.

---

## 15 — Post-launch deferred decisions

> Décisions stratégiques reportées après le launch C5, à trancher dans la fenêtre **2026-07** (post-launch + 1 mois d'observation).

### 15.1 Sort de `cc-daily-analysis` post-C5

**Contexte** : aujourd'hui `cc-daily-analysis` (cron `20 19 * * 1-5`, gpt-4-turbo, 2 LLM calls) :
- Call #1 génère `macroeco_bonus` + `eco` (texte narratif macro)
- Call #2 génère `decision`, `confidence`, `direction`, `conclusion` (texte narratif décision)

Une fois C5 ensemble en prod avec `is_active=TRUE` :
- ✅ La **décision** vient du soft-gate + wrapper ensemble (pas LLM)
- ✅ La **confidence** vient du `net_score` magnitude du soft-gate
- ✅ La **direction** est implicite dans la décision
- ⚠️ Le **macroeco_bonus** ensemble vient de `MacroEventLayer` (agrégation `pl_article_segment`, pas un LLM live ; pas la même unité que le bonus daily-analysis)
- ❌ Les **`eco` et `conclusion` (texte narratif)** ne sont **pas produits nativement** par l'ensemble

**Le flag actuel `--algorithm-version legacy`** (cf. [P2-daily-analysis-version-flag.md](../user-stories/P2-daily-analysis-version-flag.md)) est un **Band-Aid tactique** : daily-analysis continue à tourner pour `legacy`, l'ensemble n'est pas écrasé. Mais c'est de la dette technique. Trois options à trancher post-launch :

#### Option A — Disparition complète de `cc-daily-analysis`

- Le job LLM live est supprimé du pipeline
- `eco` + `conclusion` ne sont plus générés
- Le brief audio NotebookLM (`cc-compass-brief`, 19:30 UTC) compense en générant un narratif from scratch depuis les `pl_*` tables (technicals + sentiment + weather)
- Le flag `--algorithm-version legacy` et son code supports sont supprimés
- **Pros** : -1 job cron, -1 dépendance OpenAI, alignement north-star, économie LLM mensuelle (~$30/mois)
- **Cons** : perte des champs `eco`/`conclusion` au niveau row si quelqu'un les consomme (à vérifier côté dashboard)

#### Option B — Refactor en "Narrator-only"

- `cc-daily-analysis` ne touche **plus** `decision`/`confidence`/`direction`/`macroeco_bonus`
- Génère **uniquement** `eco` + `conclusion` (texte explicatif post-hoc, basé sur la décision déjà écrite par compute-indicators ou ensemble-compute)
- Le flag `--algorithm-version` devient obsolète (le narrator peut narrer plusieurs versions)
- Le prompt LLM #2 est refactoré pour expliquer la décision donnée plutôt que la prendre
- **Pros** : conserve la valeur narrative pour le trader, plus de scope confusion, chaque colonne a un seul producteur (rule #3 pipeline-continuity)
- **Cons** : refactor de daily-analysis (~2-3 jours de boulot), prompt à reconcevoir, coût LLM maintenu

#### Option C — Maintien transitoire (statu quo)

- Le flag `--algorithm-version legacy` reste actif indéfiniment
- daily-analysis continue à écrire 5 colonnes pour `legacy` (devenu inactif dashboard-wise)
- L'ensemble C5 écrit ses propres rows sous son version_id, avec `eco`/`conclusion` à NULL
- Le dashboard lit la version active (ensemble) → pas de narratif eco/conclusion affiché côté ensemble
- **Pros** : zéro effort, rollback facile vers legacy si C5 échoue
- **Cons** : dette technique (~150 LOC à dégager), coût LLM maintenu pour rien si les traders ne lisent jamais le narratif legacy

### 15.2 Critères de décision

Mesurer pendant la fenêtre 2026-06 → 2026-07 :

1. **Adoption traders du narratif `eco`/`conclusion`** : est-ce que les utilisateurs lisent ces champs ? Audit via logs / heatmaps dashboard.
2. **Qualité du brief NotebookLM sans daily-analysis** : faire tourner `cc-compass-brief` en dry-run sans les colonnes `eco`/`conclusion` populées → est-ce que le résultat audio reste satisfaisant ?
3. **Coût LLM mensuel daily-analysis** : check Sentry + OpenAI billing → est-ce que le ROI justifie le maintien ?
4. **Sentiment trader sur les décisions ensemble** : feedback qualitatif après 4-6 semaines d'usage.

### 15.3 Owner & deadline

- **Owner** : Hedi (CTO).
- **Deadline soft** : 2026-07-15 (1 mois post-launch C5).
- **Action de tracking** : memory file `project_c5_daily_analysis_alignment.md` dans le système Claude memory pour que les futures sessions rappellent cette décision en attente.
- **Trigger de relance** : (a) C5 validé en prod stable (5+ semaines sans rollback), (b) ou première discussion produit sur les champs narratifs du dashboard.

### 15.4 Lien retour

- [P2-daily-analysis-version-flag.md §11](../user-stories/P2-daily-analysis-version-flag.md) — open questions de l'US tactique
- [HEDI_DATA_MAP.md §3.5](HEDI_DATA_MAP.md) — Db_Master / Option D (frozen artifact)

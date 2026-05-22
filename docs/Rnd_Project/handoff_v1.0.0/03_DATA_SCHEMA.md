# 03 — Schema DB exhaustif

Toutes les tables PostgreSQL utilisées ou écrites par l'ensemble v1.0.0, plus celles ingérées en parallèle (legacy + futures campagnes). Tous les types Postgres ; les types Python equivalents sont via SQLAlchemy ORM (`backend/app/models/pipeline.py`).

## Reference tables (immutable, low-cardinality)

### `ref_exchange`
- **Rôle** : registre des exchanges (ICE Europe, ICE US, CME, ...)
- **Migration originale** : pre-Campaign 5 (`e36e360fb184`)
- **Colonnes** :
  - `id UUID PK`
  - `code VARCHAR(20) UNIQUE NOT NULL`
  - `name VARCHAR(100) NOT NULL`
  - `timezone VARCHAR(50) NOT NULL`
  - `created_at TIMESTAMP DEFAULT now()`

### `ref_commodity`
- **Rôle** : registre des commodités (Cocoa London, Cocoa NY, Sugar #11, ...)
- **Colonnes** :
  - `id UUID PK`
  - `code VARCHAR(20) UNIQUE NOT NULL`
  - `name VARCHAR(100) NOT NULL`
  - `exchange_id UUID FK → ref_exchange.id`

### `ref_contract`
- **Rôle** : contrat tradeable spécifique (e.g., `CAK26` = London Cocoa May 2026). Contract-centric north-star : toutes les data sont keyed sur des contrats, pas sur des commodités.
- **Colonnes** :
  - `id UUID PK`
  - `commodity_id UUID FK → ref_commodity.id`
  - `code VARCHAR(20) UNIQUE NOT NULL` — e.g., `CAK26`
  - `contract_month VARCHAR(10) NOT NULL` — e.g., `K26` (delivery month code)
  - `expiry_date DATE NULLABLE`
  - `is_active BOOLEAN NOT NULL DEFAULT FALSE` — un seul contrat active à la fois (resolved by scrapers + dashboard via `WHERE is_active=TRUE LIMIT 1`)

### `ref_trading_calendar`
- **Rôle** : jours de trading par exchange. Distingue "scraper failed" vs "market closed".
- **Colonnes** :
  - `id UUID PK`
  - `exchange_id UUID FK`
  - `date DATE NOT NULL`
  - `is_trading_day BOOLEAN NOT NULL`
  - `session_type VARCHAR(20) NULLABLE` — `regular`, `early_close`, etc.
  - `reason VARCHAR(100) NULLABLE` — `Christmas`, `Easter Monday`, ...
- **UNIQUE** : `(exchange_id, date)`

## Pipeline tables — données scrapées

### `pl_contract_data_daily`
- **Rôle** : raw daily OHLCV + IV + STOCK_US + STOCK_EU + COM_NET_US, keyed sur `(date, contract_id)`.
- **Migration originale** : `e36e360fb184` (MVP schema)
- **Colonnes Campaign 5 additions** : `stock_eu_bags60kg` (h2c3d4e5f6g7)
- **Toutes colonnes** :
  - `id UUID PK DEFAULT gen_random_uuid()`
  - `date DATE NOT NULL`
  - `contract_id UUID FK → ref_contract.id NOT NULL`
  - `open DECIMAL(15,6) NULLABLE`
  - `high DECIMAL(15,6) NULLABLE`
  - `low DECIMAL(15,6) NULLABLE`
  - `close DECIMAL(15,6) NULLABLE`
  - `volume INTEGER NULLABLE`
  - `oi INTEGER NULLABLE`
  - `implied_volatility DECIMAL(15,6) NULLABLE`
  - `stock_us DECIMAL(15,6) NULLABLE` — ICE US certified stock (tonnes)
  - `stock_eu_bags60kg DECIMAL(15,6) NULLABLE` — ICE Europe certified stock (60kg bags)
  - `com_net_us DECIMAL(15,6) NULLABLE` — CFTC Commercial Net position
  - `display_date DATE NULLABLE` — `next_trading_day(date)`, set by barchart-scraper, used by dashboard masthead
  - `created_at TIMESTAMP DEFAULT now()`
- **Constraints** : `UNIQUE(date, contract_id)`, indexes `ix_contract_data_daily_date`, `ix_contract_data_daily_display_date`
- **Volumétrie prod** : 2615 rows (2016-01-04 → 2026-05-21)
- **Audit** : Hybrid — OHLCV/IV columns are append-only (barchart-scraper inserts), other columns are conditional UPDATE (stock_us / com_net_us / stock_eu_bags60kg / display_date are updated on existing rows). UPSERT idempotent per (date, contract_id).

### `pl_derived_indicators`
- **Rôle** : 27+ technical indicators dérivés calculés par l'engine (`backend/app/engine/`). Keyed sur (date, contract_id).
- **Colonnes** : pivots (r1-r3, pivot, s1-s3), EMA12/26, MACD/MACD_signal, RSI 14d (Wilder), Stochastic K/D 14, ATR + ATR 14d (Wilder), Bollinger (mid/upper/lower/width), ratios (close_pivot, volume_oi), RSI internals (gain_14d, loss_14d, rs), daily_return — tous DECIMAL(15,6) NULLABLE.
- **Volumétrie prod** : 2612 rows.
- **Audit** : UPSERT idempotent. `compute-indicators --full` recomputes tout.

### `pl_external_indicator`
- **Migration** : `f0a1b2c3d4e5` (2026-05-20)
- **Rôle** : commodity-agnostic ENSO + FX indicators. UNIQUE par `date` (un seul row par jour, plusieurs scrapers UPSERT partiel).
- **Colonnes** :
  - `id UUID PK`
  - `date DATE UNIQUE NOT NULL`
  - `enso_oni_month DECIMAL(8,4) NULLABLE` — ENSO Ocean Niño Index (mensuel)
  - `enso_nino34_anomaly DECIMAL(8,4) NULLABLE` — Niño 3.4 SST anomaly (mensuel)
  - `fx_dxy_proxy DECIMAL(15,6) NULLABLE` — `1 / usd_per_eur` (daily)
  - `fx_eurusd DECIMAL(15,6) NULLABLE` — alias of dxy_proxy (audit)
  - `fx_gbpusd DECIMAL(15,6) NULLABLE` — `usd_per_eur / gbp_per_eur` (consumed by specialists)
  - `fx_gbpeur DECIMAL(15,6) NULLABLE` — `gbp_per_eur` raw passthrough (audit)
  - `created_at TIMESTAMP DEFAULT now()`
- **Volumétrie prod** : 3999 rows (1950-01-01 → 2026-05-21 — mix of monthly ENSO row + daily FX rows joined)
- **Audit** : Append-only par date, colonnes indépendantes. ENSO et FX scrapers font partial UPSERT (chacun n'écrase pas les colonnes de l'autre).

### `pl_cot_eu_weekly`
- **Migration** : `g1b2c3d4e5f6` (2026-05-20)
- **Rôle** : ICE Europe COT weekly positioning (Producer/Merchant, Managed Money, Other Reportables, Non-Reportable, OI).
- **Colonnes** :
  - `id UUID PK`
  - `release_date DATE NOT NULL` — date of CSV publication
  - `report_date DATE NOT NULL` — Tuesday of the reported snapshot
  - `contract_market VARCHAR(50) NOT NULL DEFAULT 'cocoa'`
  - `prod_merc_long INTEGER`, `prod_merc_short INTEGER`
  - `prod_merc_net INTEGER GENERATED ALWAYS AS (prod_merc_long - prod_merc_short) STORED`
  - `m_money_long INTEGER`, `m_money_short INTEGER`
  - `m_money_net INTEGER GENERATED ALWAYS AS (m_money_long - m_money_short) STORED` — **R&D signal**
  - `other_rept_long INTEGER`, `other_rept_short INTEGER`
  - `non_rept_long INTEGER`, `non_rept_short INTEGER`
  - `open_interest INTEGER NULLABLE`
  - `created_at TIMESTAMP DEFAULT now()`
- **Constraints** : `UNIQUE(release_date, contract_market)`
- **Volumétrie prod** : 607 rows (2014-10-03 → 2026-05-15, weekly)
- **Audit** : Append-only par (release_date, contract_market). GENERATED columns auto-computed.
- **Status v1.0.0** : ❌ **NON LUE par ensemble-compute** — table préparée pour R&D experiments futures (Phase 5 / v1.1.0).

### `pl_fundamental_article`
- **Rôle** : press review article (1 row per (date, provider))
- **Colonnes principales** : `id`, `date`, `category`, `source`, `summary`, `keywords`, `impact_synthesis`, `llm_provider`, `is_active BOOLEAN`, `source_count`, `total_sources`
- **Volumétrie prod** : ~365 rows (1 article/jour × ~22 jours/mois × ~17 mois actifs)

### `pl_article_segment`
- **Migration** : `a7b8c9d0e1f2`
- **Rôle** : segments structurés (zone × theme) extraits par LLM depuis articles. Consommé par MacroEventLayer.
- **Colonnes** :
  - `id UUID PK`
  - `article_id UUID FK → pl_fundamental_article.id`
  - `article_date DATE NOT NULL` (index)
  - `zone VARCHAR(30) NULLABLE` — `production` / `chocolat` / `transformation` / `economie` (themes in inline_v1)
  - `theme VARCHAR(30) NULLABLE`
  - `facts TEXT NULLABLE`
  - `causal_chains TEXT NULLABLE`
  - `sentiment VARCHAR(20) NULLABLE` — `bullish` / `bearish` / `neutral`
  - `sentiment_score DECIMAL(3,2) NULLABLE` — `[-1.0, +1.0]`
  - `entities TEXT NULLABLE`
  - `confidence DECIMAL(3,2) NULLABLE` — `[0, 1]`
  - `llm_provider VARCHAR(20)`, `llm_model VARCHAR(100)`, `extraction_version VARCHAR(20) DEFAULT 'v1'`
- **Volumétrie prod** : 751 rows (672 v1 + 79 inline_v1)
- **Filtrage côté MacroEventLayer** : `confidence ≥ 0.70` (R&D constant CONF_THRESHOLD)
- **Audit** : Append-only, immutable per (article_id, zone, theme, extraction_version). Re-extraction crée rows avec nouvelle `extraction_version`.

### `pl_weather_observation`, `pl_seasonal_score`, `pl_sentiment_feature`
- Tables data-side existantes, **non lues par ensemble v1.0.0**. Détails dans `06_DATA_NOT_USED.md`.

## Pipeline tables — algorithme

### `pl_indicator_daily`
- **Rôle** : ground-truth decision daily (1 row per `date × contract_id × algorithm_version_id`). Multi-version : legacy / ensemble cohabitent dans cette table.
- **Colonnes principales** :
  - `id UUID PK`
  - `date DATE NOT NULL`
  - `contract_id UUID FK NOT NULL`
  - `algorithm_version_id UUID FK NOT NULL`
  - `decision VARCHAR(10)` — `OPEN`, `HEDGE`, `MONITOR` (= `decision_wrapped` for ensemble, = score-based for legacy)
  - `composite_score`, `composite_score_z`, `score`, `score_z` (raw indicator scores)
  - `macroeco_score`, `macroeco_bonus`, `eco`, `conclusion`, `confiance`, `direction` (LLM-generated text, written by `cc-daily-analysis` legacy)
  - + per-indicator z-scores (rsi_z, macd_z, etc.)
- **Constraints** : `UNIQUE(date, contract_id, algorithm_version_id)`
- **Volumétrie prod** : 5224 rows total (2612 legacy 1.0.1 + 2612 power10years 2.0.0 + 105 ensemble_v1)
- **Audit** : UPSERT per (date, contract, algo_version). Ensemble's row is written by `cc-ensemble-compute`; legacy's row by `cc-compute-indicators` + augmented by `cc-daily-analysis`.

### `pl_signal_component`
- **Rôle** : per-indicator contribution decomposition for legacy power formula.
- **Used by** : Dashboard "Compass Gauges" UI (5 ruler gauges per date).
- **NOT used by** : ensemble (ensemble produces a single decision, not a decomposed score).

### `pl_algorithm_version`
- **Rôle** : registre des algorithmes (legacy / power10years / ensemble_v1).
- **Colonnes** :
  - `id UUID PK`
  - `name VARCHAR(100) NOT NULL` — `legacy`, `power10years`, `ensemble_v1_softgate_wrapper`
  - `version VARCHAR(20) NOT NULL` — `1.0.0`, `1.0.1`, `2.0.0`
  - `horizon VARCHAR(20)` — `short_term`, `medium_term`
  - `is_active BOOLEAN NOT NULL DEFAULT FALSE` — dashboard reads `WHERE is_active=TRUE LIMIT 1`
  - `compute_enabled BOOLEAN NOT NULL DEFAULT FALSE` — `cc-compute-indicators --all-versions` filter
  - `description TEXT NULLABLE`
- **Rows prod actuels** :
  | id | name | version | is_active | compute_enabled |
  |----|------|---------|-----------|-----------------|
  | `c41df922-...` | legacy | 1.0.0 | FALSE | FALSE |
  | **`cad68027-...`** | **legacy** | **1.0.1** | **TRUE** | **TRUE** ← prod active |
  | `6189256c-...` | power10years | 2.0.0 | FALSE | TRUE |
  | **`84adf719-...`** | **ensemble_v1_softgate_wrapper** | **1.0.0** | **FALSE** (shadow) | **FALSE** (own job) |

### `pl_algorithm_config`
- **Rôle** : config-as-data per algorithm_version. Parameters tunables via DB sans redeploy (north-star rule #4).
- **Colonnes** :
  - `id UUID PK`
  - `algorithm_version_id UUID FK`
  - `parameter_name VARCHAR(100) NOT NULL`
  - `value TEXT` (string-encoded value, parsed by reader)
  - `description TEXT`
- **Rows pour ensemble_v1 (23 total)** :
  - **Soft-gate (5)** : `alpha_macro=1.4770`, `alpha_prior=0.1664`, `alpha_anomaly=0.7219`, `commit_threshold=0.2493`, `anomaly_clip_abs=2.5`
  - **Wrapper R&D (10)** : `wrapper_use_running_acc=1`, `wrapper_tau_run=0.5931`, `wrapper_running_window=3`, `wrapper_min_running_n=2`, `wrapper_use_cluster_dispersion=1`, `wrapper_min_cluster_n=2`, `wrapper_use_trend_conflict=0`, `wrapper_tau_trend=0.03`, `wrapper_trend_window=7`, `wrapper_use_three_way_disagreement=0`
  - **Cluster mapping (14)** : `cluster_exp_optim_002=winter`, ..., `cluster_xpol_S_bear_garch_macro=spring`
  - **Compass override (1)** : `compass_wrapper_dispersion_with_acc_threshold=0.60`

### `pl_model_artifact`
- **Migration** : `i3d4e5f6g7h8` (2026-05-21)
- **Rôle** : Registry BYTEA des artifacts ML (specialists, configs, snapshots).
- **Colonnes** :
  - `id UUID PK`
  - `algorithm_version_id UUID FK NOT NULL`
  - `artifact_kind VARCHAR(64) NOT NULL` — `specialist_model`, `specialist_hp`, `long_run_anomaly`, `long_run_priors`, `long_run_regime_clusters`, `soft_gate_config`, `wrapper_config`, `canonical_snapshot`
  - `artifact_name VARCHAR(128) NOT NULL` — e.g., `exp_optim_002`, `softgate_v1_foldB`
  - `training_month VARCHAR(7) NULLABLE` — `YYYY-MM` (only for specialist_model + specialist_hp)
  - `payload BYTEA NOT NULL` — raw bytes (.pkl, .json, .csv, .parquet)
  - `payload_encoding VARCHAR(16) NOT NULL` — `pickle`, `json-utf8`, `csv-utf8`, `parquet`
  - `sha256 CHAR(64) NOT NULL` — content checksum, revalidated at load time
  - `n_bytes INTEGER NOT NULL`
  - `fit_train_start DATE NULLABLE`, `fit_train_end DATE NULLABLE`
  - `n_train INTEGER NULLABLE`, `class_balance JSONB NULLABLE`
  - `git_sha VARCHAR(40) NULLABLE`, `python_version VARCHAR(16) NULLABLE`, `lib_versions JSONB NULLABLE`
  - `source_path TEXT NULLABLE`
  - `created_at TIMESTAMP DEFAULT now()`
- **Constraints** : `UNIQUE(algorithm_version_id, artifact_kind, artifact_name, training_month)`
- **Volumétrie prod** : **38 rows** v1.0.0
  - 14 specialist_model
  - 14 specialist_hp
  - 3 long_run (anomaly, priors, regime_clusters)
  - 2 tuned_config (soft_gate, transition_wrapper)
  - 5 canonical_snapshot (pl_contract_data_daily, pl_derived_indicators, pl_article_segment, ref_contract — parquet — + regime_tags csv)
- **Total payload size** : ~12 MB (TOAST compressed)
- **Audit** : Append-only via UPSERT, immutable per unique key.

### `pl_specialist_prediction`
- **Migration** : `j4e5f6g7h8i9` (2026-05-21)
- **Rôle** : per-specialist vote (14 rows par décision).
- **Colonnes** :
  - `id UUID PK`
  - `date DATE NOT NULL`
  - `contract_id UUID FK NOT NULL`
  - `algorithm_version_id UUID FK NOT NULL`
  - `specialist_name VARCHAR(64) NOT NULL` — e.g., `exp_optim_002`
  - `window_months SMALLINT NULLABLE` — `12` ou `24` (training window of the specialist)
  - `pred VARCHAR(10) NOT NULL` — `OPEN` / `HEDGE` / `MONITOR`
  - `n_features_used INTEGER NULLABLE`
  - `created_at TIMESTAMP DEFAULT now()`
- **Constraints** : `UNIQUE(date, contract_id, algorithm_version_id, specialist_name)`
- **Volumétrie prod** : 1470 rows ensemble_v1 (= 105 dates × 14 specialists)
- **Audit** : Append-only immutable per unique key.

### `pl_orchestrator_decision`
- **Migration** : `k5f6g7h8i9j0` (2026-05-21)
- **Rôle** : 1 row per (date × contract × algo_version). Capture soft-gate decision raw + wrapped decision + all diagnostics.
- **Colonnes principales** :
  - `id UUID PK`
  - `date DATE NOT NULL`
  - `contract_id UUID FK NOT NULL`
  - `algorithm_version_id UUID FK NOT NULL`
  - **Soft-gate output** :
    - `soft_gate_decision VARCHAR(10) NOT NULL` — `OPEN` / `HEDGE` / `MONITOR`
    - `net_score DECIMAL(8,4) NULLABLE`
    - `weights_sum DECIMAL(8,4) NULLABLE`
    - `n_committed_specialists INTEGER NULLABLE`
    - `prior_open DECIMAL(8,4) NULLABLE`, `prior_hedge DECIMAL(8,4)`, `prior_monitor DECIMAL(8,4)`
    - `anomaly_score_z DECIMAL(8,4) NULLABLE`
  - **Wrapper output** :
    - `decision_wrapped VARCHAR(10) NOT NULL` — final decision (= what gets written to `pl_indicator_daily.decision`)
    - `wrapper_active BOOLEAN NOT NULL` — TRUE iff wrapper changed the SG decision
    - `fired_running_acc BOOLEAN NOT NULL`, `fired_trend BOOLEAN`, `fired_dispersion BOOLEAN`, `fired_three_way BOOLEAN`
    - `running_acc_5d DECIMAL(6,3) NULLABLE` — NaN si insufficient window (NULL in SQL)
    - `realized_return_5d DECIMAL(8,5) NULLABLE`
    - `winter_vote_signed SMALLINT NULLABLE` — (open count - hedge count) parmi winter cluster
    - `spring_vote_signed SMALLINT NULLABLE` — idem spring
  - **Macro context** :
    - `macro_direction SMALLINT NULLABLE` — `-1`, `0`, `+1`
    - `macro_surprise DECIMAL(6,3) NULLABLE`
    - `macro_half_life_days SMALLINT NULLABLE`
  - `created_at TIMESTAMP DEFAULT now()`
- **Constraints** : `UNIQUE(date, contract_id, algorithm_version_id)`
- **Volumétrie prod** : 105 rows ensemble_v1.
- **Audit** : Append-only par unique key. Important : tous les NULLABLE pour permettre `NULL = "not computed"` (jamais 0.0 placeholder, cf rule `pipeline-continuity.md`).
- **Caveat audit-trail** : `wrapper_active` est dérivé de `decision_wrapped != soft_gate_decision` (pas du OR de fired_* flags). Permet d'avoir Compass-released rows = wrapper_active=FALSE même si fired_dispersion=TRUE.

## VIEWs

### `v_contract_data_chained` (PR 2)
- **Migration** : `n8i9j0k1l2m3` (2026-05-21)
- **Définition** :
  ```sql
  CREATE OR REPLACE VIEW v_contract_data_chained AS
  SELECT DISTINCT ON (date)
      date, display_date, contract_id,
      open, high, low, close, volume, oi, implied_volatility,
      stock_us, stock_eu_bags60kg, com_net_us
  FROM pl_contract_data_daily
  WHERE close IS NOT NULL
  ORDER BY date ASC,
           COALESCE(oi, 0) DESC,
           COALESCE(volume, 0) DESC,
           contract_id ASC;
  ```
- **Rôle** : Série continue front-month-by-OI à travers les rolls de contrat. Lue exclusivement par `cc-ensemble-compute` pour market_history et forward_return (PR 2 + PR 3).
- **Audit-friendly** : `contract_id` exposé en colonne → on peut prouver quel contrat sous-jacent a produit chaque ligne.
- **NOT MATERIALIZED** : recompute à chaque SELECT. ~600 rows lookup → sub-1s en pratique. Pas de REFRESH à gérer.
- **Frontend N'utilise PAS cette VIEW** : dashboard backend continue de lire `pl_contract_data_daily` filtered par contract_id. Multi-contract sémantique préservée.

## Indexes critiques

| Table | Index | Raison |
|-------|-------|--------|
| `pl_contract_data_daily` | `ix_contract_data_daily_date` | Queries par date (lookback) |
| `pl_contract_data_daily` | `ix_contract_data_daily_display_date` | Dashboard masthead lookup |
| `pl_contract_data_daily` | `UNIQUE(date, contract_id)` | UPSERT scrapers idempotent |
| `pl_derived_indicators` | `UNIQUE(date, contract_id)` | JOIN avec contract_data + UPSERT |
| `pl_article_segment` | `ix on article_date` | MacroEventLayer lookback 90d |
| `pl_orchestrator_decision` | `UNIQUE(date, contract_id, algorithm_version_id)` | Recent decisions lookback |
| `pl_specialist_prediction` | `UNIQUE(date, contract_id, algorithm_version_id, specialist_name)` | Recent votes lookback |
| `pl_indicator_daily` | `UNIQUE(date, contract_id, algorithm_version_id)` | Multi-version coexistence |
| `pl_external_indicator` | `date UNIQUE` | Partial UPSERT scrapers |
| `pl_cot_eu_weekly` | `UNIQUE(release_date, contract_market)` | Weekly UPSERT |
| `pl_model_artifact` | `UNIQUE(algo_version, artifact_kind, artifact_name, training_month)` | Bootstrap idempotent |

## Volumétrie globale prod (snapshot 2026-05-22)

| Table | Rows | Date range | Growth rate |
|-------|------|------------|-------------|
| `pl_contract_data_daily` | 2615 | 2016-01-04 → 2026-05-21 | +1/jour ouvré (multi-contracts à certaines dates) |
| `pl_derived_indicators` | 2612 | Same | +1/jour ouvré × contracts compute_enabled |
| `pl_indicator_daily` | 5224 | Same | +N/jour ouvré (N = nombre versions compute_enabled) |
| `pl_external_indicator` | 3999 | 1950-01-01 → 2026-05-21 | +1/jour ouvré (FX) + 1/mois (ENSO) |
| `pl_cot_eu_weekly` | 607 | 2014-10-03 → 2026-05-15 | +1/semaine |
| `pl_article_segment` | 751 | 2025-04-30 → 2026-05-21 | +4/jour ouvré (themes) |
| `pl_model_artifact` | 38 | One-shot 2026-05-21 | Additive on monthly retrains |
| `pl_orchestrator_decision` (ensemble_v1) | 105 | 2025-12-15 → 2026-05-21 | +1/jour ouvré |
| `pl_specialist_prediction` (ensemble_v1) | 1470 | Same | +14/jour ouvré |

Storage total estimé : ~80-100 MB rows + ~12 MB BYTEA artifacts = sub-1GB Cloud SQL (db-f1-micro suffit pour les 12 prochains mois).

## SQL queries types

### Lecture market_history pour ensemble-compute (db_loader.py)
```sql
-- _MARKET_HISTORY_SELECT
SELECT pd.date, pd.contract_id, pd.open, pd.high, pd.low, pd.close,
       pd.volume, pd.oi, pd.implied_volatility, pd.stock_us, pd.com_net_us,
       pi.r3, pi.r2, ..., pi.daily_return
FROM v_contract_data_chained pd
JOIN pl_derived_indicators pi ON pi.date = pd.date AND pi.contract_id = pd.contract_id
WHERE pd.date BETWEEN :start_date AND :end_date
ORDER BY pd.date ASC;
-- Returns ~600 rows for 600d lookback.
```

### Lecture recent_decisions (avec forward_return computed via LATERAL)
```sql
-- _RECENT_DECISIONS_SELECT
SELECT o.date, o.soft_gate_decision AS decision,
       o.decision_wrapped, o.net_score, o.macro_direction,
       o.prior_open, o.prior_hedge, o.prior_monitor,
       (o.soft_gate_decision <> 'MONITOR' AND ...) AS committed,
       (SELECT (fut.close / cur.close) - 1.0
        FROM v_contract_data_chained cur
        JOIN LATERAL (
            SELECT close FROM v_contract_data_chained f
            WHERE f.date > cur.date ORDER BY f.date ASC OFFSET 5 LIMIT 1
        ) fut ON TRUE
        WHERE cur.date = o.date) AS forward_return
FROM pl_orchestrator_decision o
WHERE o.contract_id = :contract_id
  AND o.algorithm_version_id = :algorithm_version_id
  AND o.date < :end_date
ORDER BY o.date DESC LIMIT :lookback;
```

### Lecture macro segments
```sql
-- _MACRO_SEGMENTS_SELECT (90d window)
SELECT article_date, sentiment_score, confidence
FROM pl_article_segment
WHERE article_date BETWEEN :start_date AND :end_date
  AND sentiment_score IS NOT NULL
  AND confidence IS NOT NULL
ORDER BY article_date ASC;
```

## Audit-trail principles

| Type d'écriture | Pattern utilisé | Exemples |
|-----------------|-----------------|----------|
| INSERT immutable | append-only, jamais d'UPDATE | `pl_specialist_prediction`, `pl_orchestrator_decision`, `pl_article_segment` |
| INSERT idempotent | UPSERT par unique key | `pl_external_indicator`, `pl_cot_eu_weekly`, `pl_model_artifact` |
| INSERT puis UPDATE conditionnel | scrapers chaînés (barchart insère, ice-stocks update une colonne, cftc update une autre) | `pl_contract_data_daily` |
| GENERATED columns | Postgres computed | `pl_cot_eu_weekly.prod_merc_net`, `m_money_net` |
| VIEW non-matérialisée | read-only, recompute | `v_contract_data_chained` |

**Convention NULL = "not computed yet"** (rule `pipeline-continuity.md`) : tous les diagnostics dans `pl_orchestrator_decision` sont NULLABLE. Jamais de 0.0 placeholder qui serait indistinguable d'un vrai 0 computed.

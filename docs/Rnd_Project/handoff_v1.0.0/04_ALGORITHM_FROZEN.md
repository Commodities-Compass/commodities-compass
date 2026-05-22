# 04 — Algorithm ensemble v1.0.0 (figé)

Spec exhaustive de la version v1.0.0 telle qu'elle tourne en prod. Tout est figé au **2026-04-30** (training_cutoff dans `frozen/manifest.json`). Compass **ne fait pas de training** ; seulement load + run + log + write.

## Vendor delivery structure

`backend/vendor/campaign5_ensemble_v1.0.0/` (read-only par convention)

```
campaign5_ensemble_v1.0.0/
├── pyproject.toml                  # Vendor's own package definition (name="ensemble")
├── README.md                       # R&D delivery notes
├── CHANGELOG.md                    # R&D version history
├── LICENSE
├── ensemble/                       # Vendor R&D library (Python)
│   ├── __init__.py
│   ├── config.py                   # AlgorithmConfig dataclasses
│   ├── data_loader_protocol.py     # DecideRequest, MacroSignal, EnsembleDataLoader Protocol
│   ├── data_loader.py              # FrozenDirLoader (file-based, dev/test only)
│   ├── artifact_io.py              # DBArtifactLoader (Postgres BYTEA) + load_json/pickle/parquet
│   ├── ensemble_pipeline.py        # EnsemblePipeline (orchestrates everything)
│   ├── features.py                 # FEATURE_COLUMNS (canonical 50+ feature set)
│   ├── features_maximal.py         # All features for OPTIM search space
│   ├── features_garch.py           # GARCH-specific features
│   ├── external_data.py            # Helpers for FX, ENSO loading
│   ├── targets.py                  # Target definitions (OPEN/HEDGE/MONITOR labels)
│   ├── targets_calibrated.py       # Confidence-calibrated targets
│   ├── targets_triple_barrier.py   # Triple-barrier labeling helper
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── soft_gate.py            # SoftGateOrchestrator (Bayesian vote)
│   │   └── transition_wrapper.py   # TransitionProtectionWrapper (4 detectors)
│   ├── long_run/
│   │   ├── anomaly_veto.py         # AnomalyVetoModel (10y baseline)
│   │   ├── structural_priors.py    # StructuralPriors (regime+vol/ret buckets)
│   │   └── regime_similarity.py    # RegimeSimilarityModel (cluster weights)
│   ├── macro_events/
│   │   └── pipeline.py             # MacroEventLayer (sentiment aggregation)
│   ├── models/                     # Specialist base classes (LGB/RF/Logistic + GARCH wrappers)
│   ├── optimizer/                  # Optuna training (R&D-only, not used at runtime)
│   ├── retrain/                    # Monthly retrainer stub (future)
│   ├── training_utils/             # Anti-bias, calibration helpers (R&D-only)
│   └── evaluation/                 # Backtest metrics (R&D-only)
├── frozen/                         # Artifacts (BYTEA, loaded into pl_model_artifact)
│   ├── manifest.json               # SHA-256 + provenance
│   ├── specialist_models/          # 14 .pkl
│   ├── specialist_hps/             # 14 .json
│   ├── tuned_configs/
│   │   ├── soft_gate.json
│   │   └── transition_wrapper.json
│   ├── long_run/
│   │   ├── anomaly_veto.pkl
│   │   ├── structural_priors.json
│   │   └── regime_clusters.json
│   └── canonical_snapshot/         # R&D test data (deterministic)
│       ├── pl_contract_data_daily.parquet
│       ├── pl_derived_indicators.parquet
│       ├── pl_article_segment.parquet
│       ├── ref_contract.parquet
│       └── regime_tags.csv
├── tools/                          # R&D tooling
│   ├── freeze_artifacts.py         # Build frozen/ from R&D experiments
│   ├── load_artifacts_to_pg.py     # Bootstrap to Postgres (wrapped by cc-ensemble-bootstrap-artifacts)
│   └── verify_delivery.py          # Checksum validation
├── sql/                            # Original R&D SQL migration sources
└── tests/                          # Vendor test suite
    ├── conftest.py
    ├── fixtures/
    ├── test_imports.py
    ├── test_artifact_roundtrip.py
    ├── test_orchestrator_smoke.py
    ├── test_reproducibility.py
    ├── test_schema_dry_run.py
    └── test_cluster_mapping.py
```

## Manifest figé (référence R&D)

`frozen/manifest.json` :
```json
{
  "manifest_version": "1.0",
  "algorithm_version": "1.0.0",
  "algorithm_version_name": "ensemble_v1_softgate_wrapper",
  "training_cutoff": "2026-04-30",
  "training_month": "2026-04",
  "data_source": "rd_local",
  "git_sha": "d6c0ec766a393bbf182a926a767eccdaea4438cd",
  "seed": 42,
  "lib_versions": {
    "python": "3.12.8",
    "lightgbm": "4.5.0",
    "scikit-learn": "1.6.1",
    "numpy": "1.26.4",
    "pandas": "2.2.3",
    "scipy": "1.14.1"
  },
  "artifacts": [...],            // 38 entries with SHA-256
  "cluster_mapping": {...}       // 14 mappings
}
```

**Convention de reproducibility** : R&D doit utiliser ces versions exactes pour reproduire les modèles. Compass prod runs on sklearn 1.5.2 (warning seulement, comportement identique observé sur 105 dates backfill).

## 14 specialists (frozen pool)

Tous trained sur window endant `2026-04-30`. Pickle objets sklearn/LightGBM directement consommés via `pickle.loads()` au boot du job.

### Winter cluster (6 specialists)

| Name | Window | Model Arch | n_train | Size | class_balance (DOWN/FLAT/UP) |
|------|--------|-----------|---------|------|------------------------------|
| `exp_optim_002` | 12m | 3-stack (Spot=LGB, Mom=RF, Fund=Logistic) → Meta=LGB | 247 | 1.1 MB | 67.2 / 8.9 / 23.9 |
| `exp_optim_005` | 24m | 3-stack (Spot=RF, Mom=LGB, Fund=LGB) → Meta=LGB | 485 | 3.8 MB | 45.2 / 19.0 / 35.9 |
| `exp_optim_006` | 12m | 3-stack (Spot=LGB, Mom=RF, Fund=Logistic) → Meta=LGB | 247 | 1.3 MB | (similar Winter) |
| `exp_optim_011` | 12m | 3-stack (Spot=LGB, Mom=RF, Fund=Logistic) → Meta=LGB | 247 | 3.2 MB | (similar Winter) |
| `xpol_W_TB_garch` | 24m | GARCH + 3-stack (Spot=RF, Mom=LGB, Fund=LGB) → Meta=LGB | 485 | 1.7 MB | balanced |
| `xpol_W_TB_macro` | 12m | GARCH + 3-stack (Spot=LGB, Mom=RF, Fund=Logistic) → Meta=LGB | 247 | 1.6 MB | balanced |

### Spring cluster (8 specialists)

| Name | Window | Model Arch | n_train | Size |
|------|--------|-----------|---------|------|
| `exp_optim_017_bear_4` | 12m | 3-stack LGB | 247 | 1.4 MB |
| `exp_optim_017_bear_8` | 12m | 3-stack LGB | 247 | 2.2 MB |
| `exp_optim_017_bull_4` | 12m | 3-stack LGB | 247 | 2.4 MB |
| `exp_optim_017_bull_5` | 12m | 3-stack LGB | 247 | 342 KB |
| `exp_optim_017_bull_7` | 12m | 3-stack LGB | 247 | 4.7 MB |
| `exp_optim_017_bull_8` | 12m | 3-stack LGB | 247 | 884 KB |
| `xpol_S_bear_garch_macro` | 24m | GARCH + 3-stack | 485 | 4.2 MB |
| `xpol_S_bull_garch_fx` | 24m | GARCH + 3-stack | 485 | 470 KB |

**Cluster mapping prod** (seeded by migration `l6g7h8i9j0k1`) :
```python
# pl_algorithm_config WHERE parameter_name LIKE 'cluster_%'
{
  "exp_optim_002": "winter",
  "exp_optim_005": "winter",
  "exp_optim_006": "winter",
  "exp_optim_011": "winter",
  "xpol_W_TB_garch": "winter",
  "xpol_W_TB_macro": "winter",
  "exp_optim_017_bear_4": "spring",
  "exp_optim_017_bear_8": "spring",
  "exp_optim_017_bull_4": "spring",
  "exp_optim_017_bull_5": "spring",
  "exp_optim_017_bull_7": "spring",
  "exp_optim_017_bull_8": "spring",
  "xpol_S_bear_garch_macro": "spring",
  "xpol_S_bull_garch_fx": "spring"
}
```

**Inference mode** : chaque specialist appelé avec `features_dict` (dict des 50+ features dérivées : technical, COT, sentiment, fundamentals_ops) → renvoie `dict[str, float]` proba normalisée sur 3 classes (`OPEN`, `HEDGE`, `MONITOR`). L'argmax est utilisé comme vote.

**Vote `MONITOR`** = specialist s'abstient ce jour-là (compte 0 dans le `n_committed_specialists` et dans le `net_score` numerator + denominator).

## Soft-gate orchestrator (SG-001 Fold B)

**File** : `backend/vendor/campaign5_ensemble_v1.0.0/ensemble/orchestrator/soft_gate.py`
**Config** : `frozen/tuned_configs/soft_gate.json` :
```json
{
  "alpha_anomaly": 0.7218905885571766,
  "alpha_macro": 1.4770120936326114,
  "alpha_prior": 0.16637118046802363,
  "commit_threshold": 0.24926406400500623
}
```
(Aussi `anomaly_clip_abs = 2.5` hardcoded.)

**Formule de pondération** :
```
weight_i = base_acc_i 
         × (1 + α_macro × is_macro_aligned_i) 
         × (1 + α_prior × is_prior_aligned_i) 
         × (1 + α_anomaly × clip(anomaly_z, ±2.5))

net_score = Σ_i (weight_i × vote_sign_i) / Σ_i weight_i

decision = OPEN     if net_score  ≥  +commit_threshold
         = HEDGE    if net_score  ≤  -commit_threshold
         = MONITOR  else
```

Avec :
- `vote_sign_i = +1` if specialist_i = OPEN, `-1` if HEDGE, `0` if MONITOR
- `is_macro_aligned_i = +1` if specialist vote matches `macro_direction`, `-1` if opposite, `0` if no event
- `is_prior_aligned_i = +1` if specialist vote = `argmax(prior_open, prior_hedge, prior_monitor)`, `0` else
- `base_acc_i` = specialist's rolling 30-day accuracy ∈ [0, 2] (linear mapped). Default `1.0` (neutral) if no history.
- `anomaly_z` = standardized anomaly_veto score, clipped à `±2.5`.

**Inputs** :
- `specialist_votes: dict[str, str]` (14 entries)
- `OrchestratorContext` :
  - `date, macro_direction, macro_surprise, macro_confidence`
  - `prior_open, prior_hedge, prior_monitor` (probability distribution from `StructuralPriors`)
  - `anomaly_score_z` (from `AnomalyVetoModel`)
  - `cluster_weights` (from `RegimeSimilarityModel`)

**Output** : `SoftGateDecision` dataclass :
- `decision ∈ {OPEN, HEDGE, MONITOR}`
- `net_score: float`
- `weights_sum: float`
- `n_committed_specialists: int`
- `per_specialist_votes: dict[str, str]`
- `per_specialist_weights: dict[str, float]`
- `context: OrchestratorContext` (audit trail)

**Tuning notes** (from R&D EXP-OPTIM-022 Fold B) :
- `alpha_macro` (highest intensity ×1.477) → macro alignment has biggest impact
- `alpha_anomaly = 0.72` positive → high anomaly z = TRUST MORE (per AV-001 polarity finding)
- `commit_threshold = 0.25` low → algo committed-by-default

## Transition Protection Wrapper (TPW-001 R&D)

**File** : `backend/vendor/campaign5_ensemble_v1.0.0/ensemble/orchestrator/transition_wrapper.py`
**Config R&D frozen** : `frozen/tuned_configs/transition_wrapper.json` :
```json
{
  "use_running_acc": true,
  "tau_run": 0.5931087687626067,
  "running_window": 3,
  "min_running_n": 2,
  "use_trend_conflict": false,
  "tau_trend": 0.030054688827855922,
  "trend_window": 7,
  "use_cluster_dispersion": true,
  "min_cluster_n": 2,
  "use_three_way_disagreement": false
}
```

### 4 detectors (2 ACTIVE en v1.0.0, 2 OFF)

#### Detector A — Running-accuracy gate (ACTIVE)
- **Code** : `_running_acc(decisions_df, idx) → (acc, n)`
- **Logic** :
  ```
  prior = decisions_df.iloc[max(0, idx-3):idx]
  committed = prior[prior.committed]
  if len(committed) < 2: return NaN, n
  acc = mean(committed.correct)
  ```
- **Fires** : `running_acc < 0.5931` AND `n_committed ≥ 2`
- **Interprétation** : Si la lancée récente du soft-gate est faible (<59%), veto le prochain commit.
- **NB causal** : `idx` est strictement la date courante ; `prior` ne contient que des dates passées (pas de look-ahead).

#### Detector B — Trend-consensus conflict (INACTIVE)
- **Code** : `_realized_return_5d(returns_by_date, date, sorted_dates) → r5`
- **Logic** :
  ```
  cum = prod(1 + r_i) - 1 over prior trend_window=7 trading days
  ```
- **Fires** : `sign(r5) ≠ sign(net_score)` AND `|r5| > 0.030`
- **Disabled** : `use_trend_conflict=false` en v1.0.0.

#### Detector C — Cluster dispersion (ACTIVE — la plus controversée)
- **Code** : `_cluster_votes(votes_by_date, date) → (w_n, w_signed, s_n, s_signed)`
- **Logic** :
  ```
  winter_signed = (open count - hedge count) in winter cluster
  spring_signed = (open count - hedge count) in spring cluster
  ```
- **Fires** : `sign(winter_signed) ≠ sign(spring_signed)` AND both clusters have `min_cluster_n=2` committed votes.
- **Interprétation** : Quand les 2 pools saisonnières divergent directionnellement, veto.
- **R&D observation** : sur backfill 2026 Compass, ce détecteur fire 46/63 (73%) des commits soft-gate — beaucoup à tort (running_acc=0.98 simultanément). C'est pourquoi Compass override (path 2 subclass).

#### Detector D — 3-way disagreement (INACTIVE)
- **Code** : `_three_way_disagreement(row) → bool`
- **Logic** :
  ```
  macro_sgn = sign(macro_direction)
  prior_sgn = +1 if prior_open strongest, -1 if prior_hedge, 0 else
  gate_sgn = sign(net_score)
  signs = [s for s in (macro_sgn, prior_sgn, gate_sgn) if s != 0]
  majority = sign(sum(signs))
  return n_agree_with_majority ≤ 1
  ```
- **Disabled** : `use_three_way_disagreement=false` en v1.0.0.

### Logique de combinaison R&D (PURE OR)

```python
any_fired = fired_a or fired_b or fired_c or fired_d
new_decision = "MONITOR" if (any_fired and orig != "MONITOR") else orig
```

Si **n'importe quel** détecteur fire → `MONITOR`. C'est cette logique OR qui rend le wrapper trop agressif en pratique (observed : cluster_dispersion alone veto 73% commits).

## Compass Override (CompassTransitionWrapper)

**File** : `backend/scripts/ensemble_compute/compass_wrapper.py`
**Classe** : `CompassTransitionWrapper(TransitionProtectionWrapper)` (subclass, path 2 d'override)
**Threshold** : `compass_wrapper_dispersion_with_acc_threshold = 0.60` (config-as-data, migration `o9j0k1l2m3n4`)

### Logique modifiée

```python
def apply(self, decisions_df, votes_long_df, returns_series):
    wrapped, diag_df = super().apply(decisions_df, votes_long_df, returns_series)
    if wrapped.empty: return wrapped, diag_df
    wrapped = wrapped.copy()  # defensive
    
    threshold = self.dispersion_with_acc_threshold  # 0.60
    
    # Release condition : only dispersion fired AND running_acc OK (or NaN bootstrap)
    running_acc_ok = wrapped["running_acc_5d"].isna() | (wrapped["running_acc_5d"] >= threshold)
    release_mask = (
        (~wrapped["fired_running_acc"])
        & (~wrapped["fired_trend"])
        & (~wrapped["fired_three_way"])
        & wrapped["fired_dispersion"]
        & running_acc_ok
    )
    
    # Apply : restore soft-gate decision on released rows
    wrapped.loc[release_mask, "decision_wrapped"] = wrapped.loc[release_mask, "decision"]
    wrapped.loc[release_mask, "wrapper_active"] = False
    
    # Re-derive committed/correct_wrapped on released rows
    wrapped["committed_wrapped"] = wrapped["decision_wrapped"] != "MONITOR"
    if "forward_return" in wrapped.columns:
        wrapped["correct_wrapped"] = (...)  # OPEN AND fwd>0 OR HEDGE AND fwd<0
    
    # Mirror in diag_df for audit consistency
    diag_df.loc[..., "any_fired"] = False
    
    return wrapped, diag_df
```

### Décision matrix Compass

| fired_running_acc | fired_dispersion | running_acc_5d | Vendor (R&D OR) | Compass (AND-gated) |
|---|---|---|---|---|
| False | False | (any) | passthrough soft-gate | passthrough soft-gate |
| False | True | ≥ 0.60 | **MONITOR** (veto) | **RELEASE soft-gate** ✅ |
| False | True | < 0.60 | MONITOR | MONITOR (veto kept) |
| False | True | NaN (bootstrap) | MONITOR | **RELEASE** (default-allow on cold-start) |
| True | (any) | (any) | MONITOR | MONITOR (running_acc rule kept) |

**Rationale** : Sur backfill 2026, dispersion fire seul (without running_acc fire) corresponds presque toujours à des situations où l'algo est sur une lancée saine mais les 2 pools cluster divergent — fausse alarme. Local backfill confirme : sur 28 cas dispersion-only, avg running_acc = 0.981 (lancée excellente).

### Audit trail post-Compass-release

| Champ DB | Vendor row | Compass-released row |
|---|---|---|
| `soft_gate_decision` | (unchanged) | (unchanged) |
| `decision_wrapped` | `MONITOR` | `= soft_gate_decision` (e.g., OPEN) |
| `wrapper_active` | `TRUE` | **`FALSE`** (Compass fix : dérivé de `wrapped != soft_gate`, pas de OR fired_*) |
| `fired_dispersion` | `TRUE` | `TRUE` (audit kept — détecteur a bien fire) |
| `running_acc_5d` | (e.g., 0.98) | (unchanged) |

## MacroEventLayer (MAC-001)

**File** : `backend/vendor/campaign5_ensemble_v1.0.0/ensemble/macro_events/pipeline.py`
**Compass wrapper** : `backend/scripts/ensemble_compute/db_loader.py::load_macro_signal`

### Constants R&D
```python
CONF_THRESHOLD = 0.70           # confidence filter for high-trust segments
DIRECTION_THRESHOLD = 0.30      # |sentiment_wmean| > 0.30 → direction != 0
SURPRISE_BASELINE_DAYS = 30     # rolling baseline for surprise z-score
HALF_LIFE_BREAKS = (0.30, 0.60) # piecewise half-life
```

Compass override : `MACRO_FIT_LOOKBACK_DAYS = 90` (window de fit envoyée au layer, plus large que les 30 baseline).

### Pipeline interne
```python
1. Filter pl_article_segment WHERE confidence ≥ 0.70 AND sentiment_score IS NOT NULL
2. Group by article_date, compute:
   - sentiment_wmean = Σ(conf_i × score_i) / Σ conf_i  (confidence-weighted daily mean)
   - n_segments = count
   - mean_confidence = Σ conf_i / n_segments
3. Rolling 30d baseline:
   - rolling_n_mean = mean(n_segments over prior 30d)
   - rolling_n_std = std(n_segments over prior 30d, fillna(1.0))
4. Surprise z-score:
   - z = (n_segments - rolling_n_mean) / rolling_n_std
   - surprise = sigmoid(z) ∈ [0, 1]
5. Direction for `today`:
   - s = today's sentiment_wmean
   - direction = +1 if s > +0.30
              = -1 if s < -0.30
              = 0 else
6. Half-life from |surprise|:
   - 1 day if |surprise| < 0.30
   - 3 days if 0.30 ≤ |surprise| < 0.60
   - 7 days if |surprise| ≥ 0.60
```

### Output `MacroSignal`
```python
@dataclass(frozen=True)
class MacroSignal:
    direction: int        # ∈ {-1, 0, +1}
    surprise: float       # ∈ [0, 1]
    confidence: float     # ∈ [0, 1]
```

Note : `half_life_days` is computed mais pas dans `MacroSignal` (Compass ne l'utilise pas — info uniquement dans `pl_orchestrator_decision.macro_half_life_days` pour audit).

### Compass fail-loud sur empty window
Si `pl_article_segment` est vide sur les 90 jours, `load_macro_signal` raise `EnsembleLoaderError` (pas de stub neutre `MacroSignal(0,0,0)`). Le job exit non-0 et il faut diagnose en amont (cf rule `pipeline-error-handling.md`).

Le **MacroEventLayer** lui-même retourne `MacroSignal(0,0,0)` si `today` n'a pas de segments mais que le 90d window en a d'autres — c'est la sémantique "real macro-quiet day", distincte de "data missing".

## Long-run models (frozen)

### AnomalyVetoModel (AV-001)
- **File pkl** : `frozen/long_run/anomaly_veto.pkl`
- **Training** : 10 ans de data (~2014-2024), IsolationForest sklearn
- **Output** : per-day anomaly z-score (clipped à `±2.5` par soft-gate avant scaling)
- **Polarité** : POSITIVE (haut z = trust more, R&D finding AV-001)

### StructuralPriors
- **File** : `frozen/long_run/structural_priors.json`
- **Schema** :
  - Regime buckets (16 + 1 global fallback) keyed sur quantiles (vol×ret×macro_quartile)
  - Per-bucket : `prior_open, prior_hedge, prior_monitor` (probabilités sommant à 1)
- **Used by** : soft-gate's `prior_alignment` computation

### RegimeSimilarityModel
- **File** : `frozen/long_run/regime_clusters.json`
- **Schema** : Cluster definitions (KMeans-like) on regime_tags (16 regimes identified by R&D)
- **Output** : per-day cluster_weights (smoothing over neighborhoods) → fed to soft-gate `cluster_weights`

## EnsemblePipeline orchestration (vendor)

**File** : `backend/vendor/campaign5_ensemble_v1.0.0/ensemble/ensemble_pipeline.py`

```python
class EnsemblePipeline:
    @classmethod
    def from_loader(cls, loader: DBArtifactLoader, training_month: str, cluster_mapping: dict):
        # 1. Load 14 specialist_model + 14 specialist_hp from pl_model_artifact BYTEA
        specialists = {name: pickle.loads(loader.load("specialist_model", name, training_month).payload)
                       for name in cluster_mapping.keys()}
        # 2. Load anomaly_veto + structural_priors + regime_clusters
        anomaly = pickle.loads(loader.load("long_run_anomaly", "av_v1", None).payload)
        priors = StructuralPriors.from_payload(load_json(loader, "long_run_priors", "priors_v1"))
        regime_sim = RegimeSimilarityModel.from_payload(load_json(loader, "long_run_regime_clusters", "regime_clusters_10y"))
        # 3. Load tuned configs
        sg_cfg = SoftGateConfig(**load_json(loader, "soft_gate_config", "softgate_v1_foldB"))
        wr_cfg = WrapperConfig(**load_json(loader, "wrapper_config", "tpw_v1"))
        soft_gate = SoftGateOrchestrator(config=sg_cfg)
        wrapper = TransitionProtectionWrapper(config=wr_cfg, cluster_mapping=cluster_mapping)
        # 4. Load regime_tags canonical_snapshot (CSV)
        regime_tags = pd.read_csv(BytesIO(loader.load("canonical_snapshot", "regime_tags_*", None).payload))
        return cls(specialists, anomaly, priors, regime_sim, soft_gate, wrapper, regime_tags)
    
    def decide(self, request: DecideRequest) -> EnsembleDecision:
        # 1. Run 14 specialists in parallel on market_history → per_specialist_votes
        # 2. Compute anomaly_z_today, priors_today, cluster_weights_today
        # 3. Build OrchestratorContext + run soft_gate.decide() → SoftGateDecision
        # 4. Append today's row to recent_decisions + recent_votes
        # 5. Build trailing returns_series + run wrapper.apply() → wrapped_decision (last row)
        # 6. Return EnsembleDecision (dataclass with all diagnostics)
```

## Bootstrap procedure

### Initial deployment (one-shot, déjà fait 2026-05-21)
```bash
# Trigger manuel
gcloud run jobs execute cc-ensemble-bootstrap-artifacts --region=europe-west9 --project=cacaooo
```

Le job :
1. Lit `vendor/campaign5_ensemble_v1.0.0/frozen/manifest.json`
2. Pour chaque artifact dans `artifacts[]` :
   - Read file from disk (`pkl`, `json`, `csv`, `parquet`)
   - Validate SHA-256 vs manifest
   - INSERT (UPSERT) into `pl_model_artifact` with BYTEA + provenance JSONB
3. Validate 38 rows total (raise si mismatch)

### New R&D version (v1.1.0+)
1. R&D livre un nouveau tarball : `campaign5_ensemble_v1.1.0.tar.gz`
2. Compass : `tar xzvf` dans `backend/vendor/campaign5_ensemble_v1.1.0/`
3. Update `backend/pyproject.toml` :
   ```toml
   ensemble = {path = "vendor/campaign5_ensemble_v1.1.0", develop = false}
   ```
4. New Alembic migration to seed new `pl_algorithm_version` row + config rows
5. Re-deploy backend + jobs (CI/CD auto)
6. Trigger `cc-ensemble-bootstrap-artifacts` manuellement contre le nouveau version_id
7. Switch `is_active` à new version via downgrade migration shadow→live (cf `m7h8i9j0k1l2`)

## Pipeline d'exécution complet (de pl_* à decision)

```
[Daily 18:30-19:15 UTC] Scrapers + cc-compute-indicators populate:
   - pl_contract_data_daily (OHLCV + IV + stock_us + stock_eu + com_net_us)
   - pl_derived_indicators (27 technical indicators)
   - pl_article_segment (4 themes × 1 article per provider)
   - pl_external_indicator.{enso_*, fx_*}
   - pl_cot_eu_weekly (weekly, late)

[19:18 UTC] cc-ensemble-compute runs:
   ┌─────────────────────────────────────────────────────────────────┐
   │ 1. Resolve contract_id (active) + algo_version_id (ensemble_v1) │
   │ 2. EnsemblePipeline.from_loader() — loads 38 BYTEA artifacts    │
   │    from pl_model_artifact                                        │
   │ 3. Swap pipeline.wrapper = CompassTransitionWrapper(threshold)   │
   │ 4. load_market_history (v_contract_data_chained × indicators)    │
   │ 5. load_recent_decisions (pl_orchestrator_decision LIMIT 10)     │
   │ 6. load_recent_votes (pl_specialist_prediction window 10d)       │
   │ 7. load_macro_signal (pl_article_segment 90d → MacroEventLayer)  │
   │ 8. pipeline.decide(DecideRequest{...}):                          │
   │    a. Run 14 specialists → per_specialist_votes                  │
   │    b. Compute anomaly + priors + regime → OrchestratorContext    │
   │    c. SoftGateOrchestrator.decide() → SoftGateDecision           │
   │    d. CompassTransitionWrapper.apply() → wrapped_decision        │
   │ 9. write_decision() : 14 rows pl_specialist_prediction +         │
   │    1 row pl_orchestrator_decision + 1 UPSERT pl_indicator_daily  │
   │ 10. session.commit() + Sentry context                            │
   └─────────────────────────────────────────────────────────────────┘
```

Runtime moyen prod : ~40-60s/execution (charge 38 BYTEA + 600d × 14 specialists + recent windows).

## R&D vendor tests (références)

`backend/vendor/campaign5_ensemble_v1.0.0/tests/` — utilisables comme regression suite quand R&D livre une nouvelle version.

- `test_imports.py` — Sanity : tous modules importable
- `test_artifact_roundtrip.py` — Load frozen/ → save → SHA-256 match
- `test_orchestrator_smoke.py` — SoftGateOrchestrator basic voting
- `test_reproducibility.py` — Frozen models produce same votes given canonical_snapshot
- `test_schema_dry_run.py` — Schema validation for decision tables (pl_orchestrator_decision etc.)
- `test_cluster_mapping.py` — Cluster assignments match manifest

À tourner avec `poetry run pytest backend/vendor/campaign5_ensemble_v1.0.0/tests/` après chaque mise à jour vendor.

## Known gotchas en prod

| # | Gotcha | Mitigation |
|---|--------|-----------|
| 1 | sklearn version drift : pickle frozen avec 1.6.1, runtime Compass 1.5.2 | Warning seulement, comportement identique observé sur 105 dates |
| 2 | First ~5 dates du cron : running_acc_5d = NaN (insufficient priors) | Compass NaN-default-allow sur dispersion-only ; running_acc fire just skip silent |
| 3 | LATERAL forward_return = NULL si < 6 dates futures dispo en DB | Acceptable, ces dates restent "pending" jusqu'à ce que le marché avance |
| 4 | macro_direction = 0 si pas de segments aujourd'hui mais 90d window non-vide | Sémantique "real macro-quiet day", pas un bug |
| 5 | macro_direction = 0 si tous segments < 0.70 confidence | Idem |
| 6 | Contract roll au milieu du backfill | VIEW chaînée gère, contract_id changeant transparent pour le pipeline |
| 7 | `cc-daily-analysis` pinné `--algorithm-version legacy` | Empêche d'écraser ensemble's pl_indicator_daily.decision |
| 8 | `ensemble_v1.is_active=FALSE` (shadow) | Dashboard ne voit jamais ensemble decisions ; flip = downgrade migration |

# 07 — Procédure d'export `.parquet` pour expérimentations R&D

R&D travaille en local Python sur des `.parquet` (pas d'accès direct à Cloud SQL). Cette procédure dump les tables nécessaires depuis prod en local, et fournit l'environnement reproducible R&D.

## Prérequis local

- Python 3.12 (matches frozen lib_versions per `manifest.json`)
- `gcloud` CLI configuré (auth + ADC)
- Bastion tunnel UP : `./.local/db-prod.sh up`
- `pyarrow` ≥ 14.0 + `pandas` 2.2.3 + `psycopg2-binary` (déjà dans `backend/pyproject.toml`)

## Environment R&D figé

Pour reproduire exactement l'environnement qui a produit les artifacts v1.0.0 :

```bash
# Recommandé : pyenv + venv isolé pour R&D experiments
pyenv install 3.12.8
pyenv local 3.12.8
python -m venv .rnd-env-v1.0.0
source .rnd-env-v1.0.0/bin/activate
pip install \
  "lightgbm==4.5.0" \
  "scikit-learn==1.6.1" \
  "numpy==1.26.4" \
  "pandas==2.2.3" \
  "scipy==1.14.1" \
  "psycopg2-binary>=2.9" \
  "pyarrow>=14.0" \
  "matplotlib>=3.8" \
  "seaborn>=0.13" \
  "jupyter" \
  "ipykernel"
```

Sources : `frozen/manifest.json.lib_versions`. Toute reproduction du training doit utiliser ces versions exactes (sklearn 1.5.2 produit des warnings mais comportement identique observé).

## Script d'export complet

Créer `/path/to/rnd_workspace/export_compass_data.py` :

```python
"""Export tous les snapshots Compass utiles pour R&D experimentation.

Prérequis :
  - Tunnel bastion UP : ./.local/db-prod.sh up
  - PYTHONPATH inclut le repo Compass (pour les models SQLAlchemy si besoin)

Usage :
  python export_compass_data.py --output-dir ./compass_v1.0.0_snapshot
"""
import argparse
import os
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

# --- Connection (via tunnel local :5434, bastion to GCP Cloud SQL) ---
DATABASE_URL = os.environ.get(
    "COMPASS_DB_URL",
    "postgresql+psycopg2://cc_app:H8B7t5pJcCR4Sh9BxRWCBRT3zlgZveb9@127.0.0.1:5434/commodities_compass",
)
ENSEMBLE_VERSION_ID = "84adf719-e8c3-4ad8-83b7-0dfea8b805fc"  # ensemble_v1_softgate_wrapper 1.0.0
LEGACY_VERSION_ID = "cad68027-da3f-4d8a-ba9d-b27dd3cfe947"  # legacy 1.0.1 (current prod active)


TABLES_TO_EXPORT = {
    # (table_or_view, optional_where_clause)
    "pl_contract_data_daily": None,
    "v_contract_data_chained": None,
    "pl_derived_indicators": None,
    "pl_indicator_daily": None,
    "pl_external_indicator": None,
    "pl_cot_eu_weekly": None,
    "pl_article_segment": None,
    "pl_fundamental_article": None,
    "pl_weather_observation": None,
    "pl_seasonal_score": None,
    "pl_sentiment_feature": None,
    "pl_orchestrator_decision": f"WHERE algorithm_version_id = '{ENSEMBLE_VERSION_ID}'",
    "pl_specialist_prediction": f"WHERE algorithm_version_id = '{ENSEMBLE_VERSION_ID}'",
    "pl_algorithm_version": None,
    "pl_algorithm_config": None,
    "ref_commodity": None,
    "ref_contract": None,
    "ref_exchange": None,
    "ref_trading_calendar": None,
}


def export_table(engine, table: str, where: str | None, out_dir: Path) -> int:
    """Dump a table or view to parquet. Returns row count."""
    where_clause = f" {where}" if where else ""
    sql = f"SELECT * FROM {table}{where_clause}"
    print(f"  Reading {table}{where_clause}...")
    df = pd.read_sql(text(sql), engine)
    out_path = out_dir / f"{table}.parquet"
    df.to_parquet(out_path, engine="pyarrow", compression="snappy", index=False)
    print(f"    {len(df):,} rows → {out_path.name} ({out_path.stat().st_size / 1e6:.1f} MB)")
    return len(df)


def export_model_artifacts(engine, out_dir: Path):
    """Dump pl_model_artifact rows + extract BYTEA payloads to individual files."""
    print("  Reading pl_model_artifact...")
    metadata_df = pd.read_sql(
        text(
            "SELECT id, algorithm_version_id, artifact_kind, artifact_name, training_month, "
            "       payload_encoding, sha256, n_bytes, fit_train_start, fit_train_end, "
            "       n_train, class_balance, git_sha, python_version, lib_versions, created_at "
            "FROM pl_model_artifact WHERE algorithm_version_id = :av"
        ),
        engine,
        params={"av": ENSEMBLE_VERSION_ID},
    )
    metadata_df.to_parquet(out_dir / "pl_model_artifact_metadata.parquet", index=False)
    print(f"    {len(metadata_df)} artifact rows → metadata")

    payloads_dir = out_dir / "artifacts_payloads"
    payloads_dir.mkdir(exist_ok=True)
    for _, row in metadata_df.iterrows():
        ext = {"pickle": "pkl", "json-utf8": "json", "csv-utf8": "csv", "parquet": "parquet"}.get(
            row["payload_encoding"], "bin"
        )
        artifact_id = str(row["id"])
        path = payloads_dir / f"{row['artifact_kind']}__{row['artifact_name']}.{ext}"
        # Stream BYTEA out for one row
        payload_bytes = engine.connect().execute(
            text("SELECT payload FROM pl_model_artifact WHERE id = :id"), {"id": artifact_id}
        ).scalar()
        path.write_bytes(payload_bytes)
        print(f"    {row['artifact_name']:<30} → {path.name} ({len(payload_bytes) / 1e6:.2f} MB)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--skip-artifacts", action="store_true", help="Don't extract BYTEA payloads (saves ~12 MB)")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(DATABASE_URL)

    print(f"Exporting Compass v1.0.0 snapshot to {args.output_dir}/")
    print("-" * 60)

    total_rows = 0
    for table, where in TABLES_TO_EXPORT.items():
        n = export_table(engine, table, where, args.output_dir)
        total_rows += n

    if not args.skip_artifacts:
        print("-" * 60)
        print("Extracting pl_model_artifact BYTEA payloads...")
        export_model_artifacts(engine, args.output_dir)

    print("-" * 60)
    print(f"Total : {total_rows:,} rows across {len(TABLES_TO_EXPORT)} tables")
    print(f"Snapshot saved to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
```

## Usage

```bash
# 1. Open tunnel
cd /path/to/commodities-compass
./.local/db-prod.sh up

# 2. Run export
mkdir -p ~/compass_data/v1.0.0_snapshot_$(date +%Y%m%d)
python export_compass_data.py --output-dir ~/compass_data/v1.0.0_snapshot_$(date +%Y%m%d)

# 3. Verify
ls -lh ~/compass_data/v1.0.0_snapshot_*/
```

**Output expected** :
```
pl_contract_data_daily.parquet           (2615 rows, ~280 KB)
v_contract_data_chained.parquet          (3300 rows, ~250 KB)
pl_derived_indicators.parquet            (2612 rows, ~720 KB)
pl_indicator_daily.parquet               (5224 rows, ~900 KB)
pl_external_indicator.parquet            (3999 rows, ~310 KB)
pl_cot_eu_weekly.parquet                 (607 rows, ~80 KB)
pl_article_segment.parquet               (751 rows, ~290 KB)
pl_fundamental_article.parquet           (~365 rows, ~3 MB)
pl_weather_observation.parquet           (~370 rows, ~600 KB)
pl_seasonal_score.parquet                (~5 rows, ~20 KB)
pl_sentiment_feature.parquet             (~100 rows, ~30 KB)
pl_orchestrator_decision.parquet         (105 rows, ~50 KB)
pl_specialist_prediction.parquet         (1470 rows, ~120 KB)
pl_algorithm_version.parquet             (4 rows, ~10 KB)
pl_algorithm_config.parquet              (~70 rows, ~25 KB)
ref_commodity.parquet                    (1-5 rows)
ref_contract.parquet                     (~50 rows)
ref_exchange.parquet                     (3-5 rows)
ref_trading_calendar.parquet             (~3000 rows)
pl_model_artifact_metadata.parquet       (38 rows)
artifacts_payloads/                      (~12 MB)
  specialist_model__exp_optim_002.pkl
  specialist_model__exp_optim_005.pkl
  ... (14 specialist models)
  specialist_hp__*.json                  (14 HP files)
  long_run_anomaly__av_v1.pkl
  long_run_priors__priors_v1.json
  long_run_regime_clusters__regime_clusters_10y.json
  soft_gate_config__softgate_v1_foldB.json
  wrapper_config__tpw_v1.json
  canonical_snapshot__*.parquet/.csv     (5 files)
```

Total snapshot : **~20 MB compressed**.

## Loading dans Python R&D

```python
import pandas as pd
import pickle

snap_dir = "/home/rnd/compass_data/v1.0.0_snapshot_20260522"

# Market data
market = pd.read_parquet(f"{snap_dir}/v_contract_data_chained.parquet")
indicators = pd.read_parquet(f"{snap_dir}/pl_derived_indicators.parquet")

# Article segments for macro signal
segments = pd.read_parquet(f"{snap_dir}/pl_article_segment.parquet")

# Cot EU (signal Managed Money for v1.1 experiments)
cot_eu = pd.read_parquet(f"{snap_dir}/pl_cot_eu_weekly.parquet")

# Decisions audit (compare prod ensemble vs your experiment)
prod_decisions = pd.read_parquet(f"{snap_dir}/pl_orchestrator_decision.parquet")
prod_votes = pd.read_parquet(f"{snap_dir}/pl_specialist_prediction.parquet")

# Specialist model (load with sklearn 1.6.1 to match frozen manifest)
with open(f"{snap_dir}/artifacts_payloads/specialist_model__exp_optim_002.pkl", "rb") as f:
    spec_002 = pickle.load(f)
# spec_002.predict_proba(features_df) → 3-class proba

# Specialist HPs (Optuna trial config)
import json
with open(f"{snap_dir}/artifacts_payloads/specialist_hp__exp_optim_002.json") as f:
    hp_002 = json.load(f)
# hp_002["config_summary"] → feature groups + base/meta family + hyperparams
```

## Canonical snapshot R&D (5 fichiers parquet/csv référence)

`pl_model_artifact` contient aussi 5 `canonical_snapshot` rows. Ces parquets sont **les data exactes utilisées par R&D pour leur training v1.0.0** (cutoff 2026-04-30). Utiles pour reproduire exactement les training conditions :

| Fichier | Contenu | Rôle |
|---------|---------|------|
| `canonical_snapshot__pl_contract_data_daily.parquet` | OHLCV jusqu'au 2026-04-30 | Training input |
| `canonical_snapshot__pl_derived_indicators.parquet` | Indicators dérivés au 2026-04-30 | Training features |
| `canonical_snapshot__pl_article_segment.parquet` | Segments article au 2026-04-30 | MacroEventLayer training |
| `canonical_snapshot__ref_contract.parquet` | Contract registry au 2026-04-30 | Contract lookup |
| `canonical_snapshot__regime_tags.csv` | Regime tagging (16 regimes) | Long-run + cluster_weights |

Pour test deterministic : `pytest backend/vendor/campaign5_ensemble_v1.0.0/tests/test_reproducibility.py` charge ces parquets + frozen specialists, run inference, vérifie SHA-256 des outputs vs reference.

## Schéma de nommage workspace R&D

Convention recommandée :
```
~/compass_data/
├── v1.0.0_snapshot_20260522/           # ce dossier
│   ├── *.parquet
│   └── artifacts_payloads/
├── v1.0.0_snapshot_20260615/           # snapshot mensuel update
├── v1.0.0_snapshot_20260722/           # ...
└── experiments/
    ├── exp_018_cot_eu/                 # one folder per R&D experiment
    │   ├── notebook.ipynb
    │   ├── frozen_artifacts/
    │   └── results.parquet
    └── exp_019_stock_eu_signal/
```

R&D experiments écrivent leurs `frozen_artifacts/` ici, et quand un experiment est promu en delivery, on tar.gz et on update `backend/vendor/campaign5_ensemble_vX.Y.0/`.

## Re-export incremental

Pour rafraîchir un snapshot sans tout re-tirer (par ex. mensuel) :

```python
# Restreindre par date
TABLES_TO_EXPORT_INCR = {
    "pl_contract_data_daily": "WHERE date >= '2026-05-22'",
    "pl_derived_indicators": "WHERE date >= '2026-05-22'",
    "pl_article_segment": "WHERE article_date >= '2026-05-22'",
    "pl_orchestrator_decision": f"WHERE algorithm_version_id='{ENSEMBLE_VERSION_ID}' AND date >= '2026-05-22'",
    "pl_specialist_prediction": f"WHERE algorithm_version_id='{ENSEMBLE_VERSION_ID}' AND date >= '2026-05-22'",
    # ref tables, model_artifact : pas besoin sauf si changements
}
```

Append to existing parquet via :
```python
new_df = pd.read_sql(...)
old_df = pd.read_parquet("snap/pl_contract_data_daily.parquet")
combined = pd.concat([old_df, new_df]).drop_duplicates(subset=["date", "contract_id"]).sort_values("date")
combined.to_parquet("snap/pl_contract_data_daily.parquet", index=False)
```

## Sanity checks post-export

Une fois l'export terminé, vérifier :

```python
import pandas as pd
import json

snap = "~/compass_data/v1.0.0_snapshot_20260522"

# 1. Volumétries doivent matcher prod
assert len(pd.read_parquet(f"{snap}/pl_orchestrator_decision.parquet")) == 105  # ensemble_v1 only
assert len(pd.read_parquet(f"{snap}/pl_specialist_prediction.parquet")) == 1470  # 105 × 14

# 2. Date range pl_article_segment
seg = pd.read_parquet(f"{snap}/pl_article_segment.parquet")
print(f"Article segments: {seg.article_date.min()} → {seg.article_date.max()}")
# Expected: 2025-04-30 → today

# 3. SHA-256 vs manifest
with open(f"{snap}/artifacts_payloads/../pl_model_artifact_metadata.parquet", "rb"):
    meta = pd.read_parquet(f"{snap}/pl_model_artifact_metadata.parquet")
# Compare meta.sha256 vs SHA-256 of corresponding payload file

# 4. Reproducibility test
# Run vendor's test_reproducibility.py against the canonical_snapshot files
```

## Quelques requêtes utiles pour R&D

### Performance par macro_direction
```python
prod = pd.read_parquet(f"{snap}/pl_orchestrator_decision.parquet")
view = pd.read_parquet(f"{snap}/v_contract_data_chained.parquet").set_index("date")

# Compute forward_return per row
prod["fwd_ret"] = prod.apply(
    lambda r: (view.loc[view.index > pd.Timestamp(r["date"])].iloc[5]["close"] / view.loc[pd.Timestamp(r["date"]), "close"] - 1.0)
    if (view.index > pd.Timestamp(r["date"])).sum() >= 6 else None,
    axis=1
)

# Accuracy by macro direction
for direction in [-1, 0, 1]:
    sub = prod[(prod.macro_direction == direction) & (prod.decision_wrapped != "MONITOR") & prod.fwd_ret.notna()]
    correct = ((sub.decision_wrapped == "OPEN") & (sub.fwd_ret > 0)).sum() + \
              ((sub.decision_wrapped == "HEDGE") & (sub.fwd_ret < 0)).sum()
    print(f"macro_dir={direction:+d}: {correct}/{len(sub)} ({100*correct/len(sub):.1f}%)")
```

### Distribution per specialist (which ones are "loud")
```python
votes = pd.read_parquet(f"{snap}/pl_specialist_prediction.parquet")
print(votes.groupby("specialist_name")["pred"].value_counts(normalize=True).unstack())
```

### Date analytics — when does dispersion fire vs is released by Compass
```python
prod = pd.read_parquet(f"{snap}/pl_orchestrator_decision.parquet")
print("Compass releases (fired_dispersion=True but wrapper_active=False) :")
released = prod[(prod.fired_dispersion == True) & (prod.wrapper_active == False)]
print(released[["date", "running_acc_5d", "decision_wrapped"]])
```

## Snapshot freshness policy

Recommandation R&D :
- **Snapshot complet** : 1x / mois (le 1er, donc capturer 22 jours ouvrés de nouvelles décisions)
- **Snapshot incremental** : 1x / semaine si experiments rapides
- **Snapshot before new vendor delivery** : OBLIGATOIRE — pour comparer apples-to-apples old vs new

À chaque snapshot, archiver le dossier complet (compressed `.tar.gz` ≈ 6 MB) sur GCS bucket private `cacaooo-rnd-snapshots/` pour traceability.

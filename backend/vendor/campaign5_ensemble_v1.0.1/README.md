# Campaign 5 ensemble — production deliverable v1.0.0

Two-part deliverable that closes the R&D-side TODOs in
`experiments/CAMPAIGN_5_PROD_DEPLOYMENT.md §4.1`:

1. **D1 — code package** (`ensemble/`): orchestrator + wrapper + 14 specialist
   factories + monthly retrainer + long-run components + macro layer + runtime
   artifact loader.
2. **D2 — artifact package** (`frozen/` + SQL): `pl_model_artifact` table DDL,
   Python loader script, 14 frozen specialist models + 5 long-run / canonical
   artifacts, manifest with SHA-256 per row.

The shipping payload (D2) is produced by running `tools/freeze_artifacts.py`
once, then staged under `frozen/` for the tarball.

---

## Layout

```
campaign5_ensemble_v1.0.0/
├── ensemble/                # the pip-installable Python package (D1)
├── frozen/                  # the artifact payload (D2 — produced by the freezer)
│   ├── manifest.json
│   ├── specialist_models/   # 14 × <name>.pkl
│   ├── specialist_hps/      # 14 × <name>.json
│   ├── long_run/            # anomaly_veto.pkl, structural_priors.json, regime_clusters.json
│   ├── tuned_configs/       # soft_gate.json, transition_wrapper.json
│   └── canonical_snapshot/  # 5 reference rows (parquet + csv)
├── sql/                     # 4 migrations to apply in order (001 → 004)
├── tools/                   # operator scripts
├── tests/                   # 6 verification gates
├── pyproject.toml           # pip install -e . in prod's monorepo
├── CHANGELOG.md
├── LICENSE
└── README.md                # you are here
```

---

## Quick start (prod operator)

1. **Apply SQL migrations** in order:
   ```sh
   psql "$DATABASE_URL" -f sql/001_create_pl_model_artifact.sql
   psql "$DATABASE_URL" -f sql/002_create_pl_specialist_prediction.sql
   psql "$DATABASE_URL" -f sql/003_create_pl_orchestrator_decision.sql
   psql "$DATABASE_URL" -f sql/004_seed_pl_algorithm_version.sql
   ```
   All 4 are idempotent (`IF NOT EXISTS` + `WHERE NOT EXISTS` guards).

2. **Load the artifact payload** into `pl_model_artifact`:
   ```sh
   pip install psycopg2-binary
   DATABASE_URL="postgres://..." FROZEN_DIR=./frozen \
     python tools/load_artifacts_to_pg.py
   ```
   The loader pre-flight-checks every SHA-256 against `manifest.json`,
   UPSERTs in a single transaction, then re-reads every row and verifies the
   SHA matches end-to-end. Fail-loud on any mismatch.

3. **Install the ensemble package** in the prod monorepo:
   ```sh
   pip install -e ./deliverables/campaign5_ensemble_v1.0.0
   ```
   Or vendor `ensemble/` directly into `backend/app/engine/ensemble/` —
   whichever matches the existing layout convention.

4. **Hook up the daily compute job** per
   `experiments/CAMPAIGN_5_PROD_DEPLOYMENT.md §6.2`. The public API is:
   ```python
   from ensemble.artifact_io import DBArtifactLoader
   from ensemble.ensemble_pipeline import EnsemblePipeline
   from ensemble.data_loader_protocol import DecideRequest, MacroSignal

   loader = DBArtifactLoader(session, algorithm_version_id)
   pipeline = EnsemblePipeline.from_loader(
       loader,
       training_month="2026-04",
       cluster_mapping=load_cluster_mapping_from_pl_algorithm_config(session, algorithm_version_id),
   )

   request = DecideRequest(
       today=today,
       contract_id=contract_id,
       market_history=load_market_panel(session, contract_id, end=today, lookback_days=600),
       recent_decisions=load_recent_orchestrator_decisions(session, contract_id, end=today, lookback=10),
       recent_votes=load_recent_specialist_votes(session, contract_id, end=today, lookback=10),
       macro=load_macro_signal(session, today),
   )
   decision = pipeline.decide(request)
   ```

5. **Day-1 bootstrap** — pre-seed `pl_orchestrator_decision` with 5 trailing
   rows from R&D's `wrapped_decisions.csv` per
   `CAMPAIGN_5_PROD_DEPLOYMENT.md §8.2`, otherwise the wrapper's
   `running_acc` detector cannot fire on day 1.

---

## R&D-side regeneration

```sh
cd deliverables/campaign5_ensemble_v1.0.0
TRAINING_CUTOFF=2026-04-30 \
DATA_SOURCE=rd_local \
OUTPUT_DIR=./frozen \
  python tools/freeze_artifacts.py
python tools/verify_delivery.py --frozen-dir ./frozen --training-month 2026-04
```

`verify_delivery.py` runs 6 gates (manifest presence, file presence, SHA
match, inventory completeness, package imports, end-to-end pipeline load). All
6 must PASS before tarballing.

---

## Non-negotiable rules (rule §0)

This package was authored under the 5 production rules from
`docs/onboarding/rnd-algo-integration.md`:

| # | Rule | Where to find it |
|---|------|------------------|
| 1 | Fail loud, no silent recovery | every SHA-256 mismatch raises `ArtifactCorruptionError`; freezer raises on any fit error; loader pre-flights before any DB write |
| 2 | No hardcoded contract codes | `EnsemblePipeline.decide` takes `contract_id` from the caller; no `LCC` / `LCN` literals |
| 3 | Computed values trace back | `pl_orchestrator_decision` has every diagnostic column as NULLABLE so day-1 `running_acc_5d` is written as NULL, never `0.0` |
| 4 | Contract-centric `(date, contract_id)` | both new tables (`pl_specialist_prediction`, `pl_orchestrator_decision`) key on `(date, contract_id, algorithm_version_id)` |
| 5 | Config as data | wrapper cluster mapping moved out of code into `pl_algorithm_config` rows; constructor reads them at job start |

---

## Out of scope

- **Monthly retrain ON PROD beyond day 1**: handled by `cc-ensemble-monthly-retrain`
  per `CAMPAIGN_5_PROD_DEPLOYMENT.md §6.1`, re-running freezer logic with
  `ensemble.retrain.MonthlyRetrainer` on prod's `pl_contract_data_daily`.
- **Yearly long-run refit** (anomaly_veto / structural_priors / regime_similarity):
  not in v1.0.0. Manual operator-driven for 2027-01.
- **Cockpit V3 J+1 prediction**: separate track.
- **COT EU + Stock EU integration**: deferred to C6 — the prod scrapers ship
  the data but the 14 v1.0.0 specialists don't consume it yet.

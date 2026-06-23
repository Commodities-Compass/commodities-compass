# Changelog

## 1.0.0 — 2026-05-20

Initial production delivery — closes the two ❌ R&D-side TODOs from
`experiments/CAMPAIGN_5_PROD_DEPLOYMENT.md §4.1`.

### Added

- `ensemble/` package (D1) — orchestrator + transition-protection wrapper +
  14 specialist factories + monthly retrainer + long-run components + macro
  layer.
- `ensemble/artifact_io.py` — `DBArtifactLoader` (prod) + `FrozenDirLoader`
  (R&D / tests) with mandatory SHA-256 verification on every load.
- `ensemble/data_loader_protocol.py` — `EnsembleDataLoader` Protocol,
  `MacroSignal` + `DecideRequest` dataclasses.
- `ensemble/ensemble_pipeline.py` — `EnsemblePipeline.from_loader(...)` +
  `decide(request) -> EnsembleDecision`.
- `from_payload` classmethods on `AnomalyVetoModel`, `StructuralPriors`,
  `RegimeSimilarityModel` so the runtime loader doesn't need temp files.
- `sql/001..004` — pl_model_artifact DDL, pl_specialist_prediction DDL,
  pl_orchestrator_decision DDL, algorithm_version + algorithm_config seed
  (incl. 14 cluster-mapping rows for rule §0 #5 compliance).
- `tools/freeze_artifacts.py` — R&D-side bootstrap: trains 14 specialists at
  TRAINING_CUTOFF, copies 5 long-run + 5 canonical-snapshot artifacts,
  generates `manifest.json` with SHA-256 + provenance.
- `tools/load_artifacts_to_pg.py` — prod-side: reads `frozen/` + UPSERTs
  `pl_model_artifact` with end-to-end SHA verification.
- `tools/verify_delivery.py` — 6-gate R&D self-check.
- `tests/` — 6 verification gates (imports, cluster mapping, artifact
  round-trip, reproducibility, orchestrator smoke, schema dry-run).

### Changed (vs R&D `methodology/`)

- Module rename: `methodology.X` → `ensemble.X` throughout.
- `TransitionProtectionWrapper`: replaced module-level
  `WINTER_SPECIALISTS` / `SPRING_SPECIALISTS` tuple constants with
  `DEFAULT_CLUSTER_MAPPING: dict[str, str]`. Constructor now accepts
  `cluster_mapping: dict[str, str] | None`; production reads the mapping
  from `pl_algorithm_config` rows (rule §0 #5).
- `ensemble.optimizer.objective`: stripped to just the factory maps +
  `_build_candidate`. `build_objective` / `_evaluate_config` (Optuna
  walk-forward runner) removed — depended on `ensemble.validation.walk_forward`
  which is intentionally not shipped (R&D-only).
- `ensemble.optimizer.specialists`: dropped the `load_dataset` helper +
  `from ensemble import data_loader` import — production loads data via the
  `EnsembleDataLoader` Protocol, not via R&D's local Parquet helper.

### Removed

- `methodology/abstention/`, `methodology/cli.py`,
  `methodology/data_loader.py`, `methodology/ensemble/`,
  `methodology/evaluation/{campaign,stratification (then re-added)}.py`,
  `methodology/models/{baselines,meta_labeling,multi_horizon_ensemble,regime_moe,selective_classifier}.py`,
  `methodology/optimizer/{baseline_config,campaign_runner,study}.py`,
  `methodology/orchestrator/learned_moe.py` (failed Phase 5 per `ME-001`),
  `methodology/reports/`, `methodology/training_utils/threshold_tuner.py`,
  `methodology/validation/`.

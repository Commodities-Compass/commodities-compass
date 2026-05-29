# Handoff R&D — Campaign 5 ensemble v1.0.0

> **Audience** : équipe R&D Compass + ML engineer Compass (présent et futur).
> **Date** : 2026-05-22. Snapshot figé de l'état prod au lendemain du go-live.
> **Statut algo** : shadow mode prod, cron `cc-ensemble-compute` à 19:18 UTC, dashboard frontend toujours sur legacy.

Ce dossier est le **point de départ canonique** pour toutes les expérimentations R&D des prochaines campagnes (v1.1.0, v2, …). Il documente intégralement la configuration figée v1.0.0, les data ingérées par la pipeline Compass, l'algorithme tel qu'il tourne en prod, et fournit la procédure pour reproduire un environnement local R&D depuis les `.parquet` exportés.

## Statut prod (référence)

| Item | Valeur | Source |
|------|--------|--------|
| Algo version | `ensemble_v1_softgate_wrapper` v1.0.0 | `pl_algorithm_version` |
| Frozen cutoff | **2026-04-30** | `frozen/manifest.json` |
| Cron quotidien | `18 19 * * 1-5` UTC | `infra/terraform/scheduler.tf` |
| Tables produites/jour | `pl_specialist_prediction` (14) + `pl_orchestrator_decision` (1) + `pl_indicator_daily` (1 UPSERT) | `db_writer.py` |
| Shadow mode actif | `is_active=FALSE, compute_enabled=FALSE` | Migration `m7h8i9j0k1l2` |
| Backfill 2026 | **96 dates** (2026-01-02 → 2026-05-21), **90 scorables** | Probe prod 2026-05-22 |

## KPI YTD 2026 (scorable-only, 90 dates)

| KPI | **Compass prod** | R&D reference |
|-----|------------------|---------------|
| Soft-gate accuracy | 40/64 = **62.5%** | 50/77 = 64.9% |
| Soft-gate coverage | 64/90 = **71.1%** | 77/89 = 86.5% |
| Wrapper accuracy | 30/42 = **71.4%** | 34/41 = 82.9% |
| **Wrapper coverage** | 42/90 = **46.7% ✅** | 41/89 = 46.1% (we beat) |

Détail mensuel + méthodologie : `05_PERFORMANCE.md`.

## Index des fichiers

| # | Fichier | Sujet |
|---|---------|-------|
| 01 | `01_ARCHITECTURE.md` | Infra GCP + Cloud Run Jobs + scheduler + pipeline order + migrations Alembic |
| 02 | `02_DATA_SOURCES.md` | 14 scrapers/agents : source, cron, output, idempotence, fail-loud, backfill history |
| 03 | `03_DATA_SCHEMA.md` | Toutes les tables/VIEW utilisées par l'ensemble : colonnes, contraintes, audit, volumétrie |
| 04 | `04_ALGORITHM_FROZEN.md` | 14 specialists + soft-gate + R&D wrapper TPW-001 + Compass override + MacroEventLayer + bootstrap |
| 05 | `05_PERFORMANCE.md` | KPI baseline prod + méthodologie scorable-only + comparaison R&D + analyse local-vs-prod |
| 06 | `06_DATA_NOT_USED.md` | Data ingérées non consommées par v1.0.0 (potentiel pour v1.1+) |
| 07 | `07_PARQUET_EXPORT.md` | Procédure d'export `.parquet` pour expérimentations R&D offline |

## Glossaire (lecture rapide)

| Terme | Signification |
|-------|---------------|
| **SG** (soft-gate) | Orchestrateur Bayesian qui pondère les 14 votes specialists par alignement macro/prior/anomaly. Sort `decision ∈ {OPEN, HEDGE, MONITOR}` selon `\|net_score\| ≥ commit_threshold`. |
| **WR** (wrapper) | Transition Protection Wrapper (TPW-001) appliqué après SG. 4 détecteurs (running_acc / trend / cluster_dispersion / three_way). Si un détecteur fire ET decision ≠ MONITOR → force MONITOR. |
| **Compass override** | Subclass Compass-side du wrapper R&D qui relâche le veto dispersion-only quand `running_acc_5d ≥ threshold` (0.60). |
| **scorable** | Date dont le forward_return 6 trading-days est réalisé (donc dont l'accuracy est mesurable). Inverse = pending (horizon non clos). |
| **coverage** | (# dates committées non-MONITOR) / (# dates totales) — taux d'utilisation de l'algo. |
| **accuracy** | (# decisions correctes) / (# decisions committées scorables) — qualité des decisions. |
| **vendor** | `backend/vendor/campaign5_ensemble_v1.0.0/` — package R&D figé, read-only par convention. |
| **chained VIEW** | `v_contract_data_chained` Postgres VIEW exposant une série continue front-month-by-OI à travers les rolls de contrat. |
| **bootstrap** | Job `cc-ensemble-bootstrap-artifacts` qui charge 38 artifacts BYTEA (specialists pkl + HPs JSON + configs + long_run models + canonical snapshots) depuis `frozen/` dans `pl_model_artifact`. |
| **CL-001** | Spec R&D : clustering des 14 specialists en 2 pools "winter" (6) et "spring" (8) pour le détecteur `cluster_dispersion`. |
| **SG-001 Fold B** | Tuned configuration soft-gate retenue (alpha_macro=1.4770, alpha_prior=0.1664, alpha_anomaly=0.7219, commit_threshold=0.2493). |
| **TPW-001** | Tuned configuration wrapper R&D figée (tau_run=0.5931, running_window=3, min_running_n=2, min_cluster_n=2). |
| **MAC-001** | Macro Event Layer R&D : agrège sentiments `pl_article_segment` (90d window, confidence ≥ 0.70) → `MacroSignal{direction, surprise, confidence}`. |

## Pointers utiles

- **Vendor delivery** : `backend/vendor/campaign5_ensemble_v1.0.0/` (lire `frozen/manifest.json` pour SHA-256 + lib versions)
- **Code Compass-side** : `backend/scripts/ensemble_compute/` (main.py, db_loader.py, db_writer.py, compass_wrapper.py, cluster_mapping_loader.py)
- **Runbook ops** : `docs/runbooks/ensemble-failure-recovery.md` (diagnostic + relaunch)
- **Rules projet** : `.claude/rules/pipeline-error-handling.md`, `.claude/rules/north-star-alignment.md`, `.claude/rules/migrations-prod-via-main-only.md`
- **Bastion DB prod** : `./.local/db-prod.sh {up|status|exec|csv|down}` (procédure tunnel IAP)

## Versioning de ce dossier

Ce dossier est **figé pour v1.0.0**. Quand R&D livre une nouvelle version (v1.1.0, v2, …), un nouveau dossier `handoff_v1.X.0/` est créé en miroir — celui-ci reste l'historique de référence.

Commit ref initial : `<sera-ajouté-au-commit>`. Diffs subséquents → corrections factuelles uniquement (KPI re-mesurés, typos), pas d'évolution structurelle.

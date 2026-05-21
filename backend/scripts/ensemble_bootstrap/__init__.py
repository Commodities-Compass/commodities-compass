"""Cloud Run Job — one-shot loader for C5 ensemble frozen artefacts.

Loads the 38 artefacts from ``vendor/campaign5_ensemble_v1.0.0/frozen/``
into ``pl_model_artifact``. Idempotent (UPSERT). Run once after each new
R&D release.
"""

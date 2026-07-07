"""Artifact serialization round-trip.

Each kind of artifact must be serializable to bytes and reconstructable from
those bytes. The pipeline's load path (``DBArtifactLoader``) returns bytes
out of pl_model_artifact; the same bytes must produce equivalent live objects
when piped through the new ``from_payload`` classmethods.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ensemble.artifact_io import (
    ArtifactRecord,
    FrozenDirLoader,
    load_json,
    load_pickle,
)
from ensemble.long_run.anomaly_veto import AnomalyVetoConfig, AnomalyVetoModel
from ensemble.long_run.regime_similarity import (
    RegimeSimilarityConfig,
    RegimeSimilarityModel,
)
from ensemble.long_run.structural_priors import StructuralPriors


def _synthetic_market_df(n: int = 400, seed: int = 7, horizon: int = 6) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-02", periods=n, freq="B")
    returns = rng.normal(0.0, 0.012, size=n)
    close = 4000 * np.cumprod(1 + returns)
    atr = pd.Series(close).pct_change().abs().rolling(14).mean().fillna(0.01)
    df = pd.DataFrame({
        "date": dates,
        "close": close,
        "high": close * 1.005,
        "low": close * 0.995,
        "open": close,
        "daily_return": returns,
        "volume": rng.integers(1000, 5000, size=n),
        "atr_14d": atr.to_numpy(),
    })
    # StructuralPriors expects a forward_return_<h>d column (its target proxy).
    df[f"forward_return_{horizon}d"] = (
        df["close"].shift(-horizon) / df["close"] - 1.0
    ).fillna(0.0)
    return df


# ---------------------------------------------------------------------------
# AnomalyVetoModel — pickle round-trip via from_payload
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_anomaly_veto_from_payload_roundtrip(tmp_path: Path) -> None:
    df = _synthetic_market_df()
    model = AnomalyVetoModel(AnomalyVetoConfig())
    # The default ANOMALY_FEATURES list expects 9 production columns; constrain
    # to the synthetic-df columns so the test is self-contained.
    model._feature_cols = ("daily_return", "atr_14d")
    model.fit(df)

    save_path = tmp_path / "anomaly.pkl"
    model.save(save_path)

    payload = save_path.read_bytes()
    sha = hashlib.sha256(payload).hexdigest()
    record = ArtifactRecord(
        artifact_kind="long_run_anomaly",
        artifact_name="test",
        training_month=None,
        payload=payload,
        payload_encoding="pickle",
        sha256=sha,
    )
    reloaded_dict = pickle.loads(record.payload)
    reloaded = AnomalyVetoModel.from_payload(reloaded_dict)

    assert reloaded._score_mean == pytest.approx(model._score_mean)
    assert reloaded._score_std == pytest.approx(model._score_std)
    np.testing.assert_allclose(
        reloaded.anomaly_score(df),
        model.anomaly_score(df),
    )


# ---------------------------------------------------------------------------
# StructuralPriors — JSON round-trip via from_payload
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_structural_priors_from_payload_roundtrip(tmp_path: Path) -> None:
    df = _synthetic_market_df()
    regime_tags = pd.DataFrame({
        "date": df["date"],
        "regime_id": (df.index % 4),
    })
    priors = StructuralPriors(horizon=6, min_n_per_bucket=5)
    priors.fit(df, regime_tags)

    save_path = tmp_path / "priors.json"
    priors.save(save_path)
    payload = save_path.read_bytes()

    reloaded_dict = json.loads(payload.decode("utf-8"))
    reloaded = StructuralPriors.from_payload(reloaded_dict)

    assert reloaded.horizon == priors.horizon
    assert set(reloaded._table) == set(priors._table)
    for key, bucket in priors._table.items():
        rb = reloaded._table[key]
        assert rb.p_open == pytest.approx(bucket.p_open)
        assert rb.p_hedge == pytest.approx(bucket.p_hedge)
        assert rb.p_monitor == pytest.approx(bucket.p_monitor)


# ---------------------------------------------------------------------------
# RegimeSimilarityModel — JSON round-trip via from_payload
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_regime_similarity_from_payload_roundtrip(tmp_path: Path) -> None:
    df = _synthetic_market_df(n=600)
    regime_tags = pd.DataFrame({
        "date": df["date"],
        "regime_id": (df.index % 4),
    })
    model = RegimeSimilarityModel(RegimeSimilarityConfig(k_min=2, k_max=4, seed=42))
    model.fit(df, regime_tags)

    save_path = tmp_path / "regime.json"
    model.save_json(save_path)
    payload = save_path.read_bytes()
    payload_dict = json.loads(payload.decode("utf-8"))

    reloaded = RegimeSimilarityModel.from_payload(payload_dict)
    assert reloaded._k_final == model._k_final
    np.testing.assert_allclose(reloaded._scaler.mean_, model._scaler.mean_)
    np.testing.assert_allclose(reloaded._kmeans.cluster_centers_, model._kmeans.cluster_centers_)

    # Identical cluster_weights output on the same input:
    w_orig = model.cluster_weights(df, regime_tags)
    w_reloaded = reloaded.cluster_weights(df, regime_tags)
    cluster_cols = [c for c in w_orig.columns if c.startswith("cluster_")]
    for col in cluster_cols:
        np.testing.assert_allclose(w_reloaded[col].to_numpy(), w_orig[col].to_numpy())


# ---------------------------------------------------------------------------
# FrozenDirLoader — manifest + filesystem round-trip
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_frozen_dir_loader_roundtrip(tmp_path: Path) -> None:
    """Write a minimal frozen/ tree by hand, load it back, check SHA verification."""
    fd = tmp_path / "frozen"
    (fd / "tuned_configs").mkdir(parents=True)
    payload = json.dumps({"alpha_macro": 1.477, "commit_threshold": 0.249}).encode("utf-8")
    (fd / "tuned_configs" / "soft_gate.json").write_bytes(payload)
    manifest = {
        "manifest_version": "1.0",
        "artifacts": [{
            "artifact_kind": "soft_gate_config",
            "artifact_name": "softgate_v1_foldB",
            "training_month": None,
            "filename": "tuned_configs/soft_gate.json",
            "payload_encoding": "json-utf8",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "n_bytes": len(payload),
        }],
    }
    (fd / "manifest.json").write_text(json.dumps(manifest))

    loader = FrozenDirLoader(fd)
    parsed = load_json(loader, "soft_gate_config", "softgate_v1_foldB", None)
    assert parsed["alpha_macro"] == pytest.approx(1.477)


@pytest.mark.unit
def test_frozen_dir_loader_detects_corruption(tmp_path: Path) -> None:
    fd = tmp_path / "frozen"
    (fd / "tuned_configs").mkdir(parents=True)
    correct_payload = b'{"x":1}'
    (fd / "tuned_configs" / "soft_gate.json").write_bytes(correct_payload)
    manifest = {
        "manifest_version": "1.0",
        "artifacts": [{
            "artifact_kind": "soft_gate_config",
            "artifact_name": "softgate_v1_foldB",
            "training_month": None,
            "filename": "tuned_configs/soft_gate.json",
            "payload_encoding": "json-utf8",
            "sha256": "deadbeef" * 8,   # wrong on purpose
            "n_bytes": len(correct_payload),
        }],
    }
    (fd / "manifest.json").write_text(json.dumps(manifest))

    from ensemble.artifact_io import ArtifactCorruptionError, FrozenDirLoader as _FDL

    loader = _FDL(fd)
    with pytest.raises(ArtifactCorruptionError):
        loader.load("soft_gate_config", "softgate_v1_foldB", None)

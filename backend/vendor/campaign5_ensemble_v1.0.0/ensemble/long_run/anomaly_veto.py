"""AnomalyVetoModel — long-run anomaly detection for the Campaign 4 orchestrator.

Trained on full 10-year cocoa data. Answers one binary question per day:

    "Given everything the cocoa market has ever shown, is today's combination
    of features (price, vol, momentum, regime) anomalous?"

Implementation: scikit-learn IsolationForest (Liu, Ting, Zhou 2008). Returns
a calibrated anomaly_score ∈ [-1, +1] where MORE NEGATIVE = MORE ANOMALOUS
(sklearn convention; we flip the sign so MORE POSITIVE = MORE ANOMALOUS for
intuition).

Veto rule used by the orchestrator (Phase 4-5):
    if anomaly_score(t) > τ_anomaly AND orchestrator wants to commit:
        force MONITOR
        (today's state is too rare for the duality-aware specialists to be
         trusted; defer to abstention).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import pickle

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


# Features the IsolationForest will use. Selected per established `FI-002`
# (top permutation importance ranking, EXP-008) plus regime context.
ANOMALY_FEATURES: tuple[str, ...] = (
    "atr_14d",
    "macd",
    "macd_signal",
    "rsi_14d",
    "daily_return",
    "bollinger_width",
    "stochastic_d_14",
    "close_pivot_ratio",
    "volume_oi_ratio",
)


@dataclass(frozen=True)
class AnomalyVetoConfig:
    contamination: float = 0.05  # assume 5% of historical days are "rare"
    n_estimators: int = 200
    max_features: float = 0.75
    random_state: int = 42


class AnomalyVetoModel:
    """IsolationForest-backed anomaly detector for the orchestrator's veto rule.

    The MODEL itself does not decide the veto threshold — it produces an
    anomaly_score per day. The orchestrator owns the threshold (configurable
    so that Phase 4-5 can tune it on val data).

    Sign convention here: ``anomaly_score > 0`` means MORE ANOMALOUS than
    typical (we flip sklearn's convention so the orchestrator threshold is
    natural: "if score > τ_anom, day is anomalous").
    """

    def __init__(self, config: AnomalyVetoConfig | None = None) -> None:
        self.config: AnomalyVetoConfig = config or AnomalyVetoConfig()
        self._model: IsolationForest | None = None
        self._feature_cols: tuple[str, ...] = ANOMALY_FEATURES
        self._imputer_medians: dict[str, float] = {}
        self._score_mean: float = 0.0
        self._score_std: float = 1.0

    def _build(self, df: pd.DataFrame) -> np.ndarray:
        """Select + impute features. Returns (n_rows, n_features) matrix."""
        missing = [c for c in self._feature_cols if c not in df.columns]
        if missing:
            raise ValueError(f"AnomalyVetoModel: missing feature columns {missing}")
        X = df[list(self._feature_cols)].astype(float).copy()
        # Impute with column median if missing (only on FIT; on PREDICT use stored medians).
        if not self._imputer_medians:
            for c in self._feature_cols:
                med = float(X[c].median(skipna=True))
                if not np.isfinite(med):
                    med = 0.0
                self._imputer_medians[c] = med
        for c in self._feature_cols:
            X[c] = X[c].fillna(self._imputer_medians[c])
        return X.to_numpy(dtype=float)

    def fit(self, df: pd.DataFrame) -> "AnomalyVetoModel":
        """Fit IsolationForest on the full historical window provided.

        Standardizes the score distribution: stores mean + std of raw scores
        so calibration is consistent across (train, score-2026) calls.
        """
        X = self._build(df)
        self._model = IsolationForest(
            contamination=self.config.contamination,
            n_estimators=self.config.n_estimators,
            max_features=self.config.max_features,
            random_state=self.config.random_state,
            n_jobs=1,
        ).fit(X)
        # Calibrate: compute the distribution of (-score) on train so that
        # threshold semantics are stable.
        raw_scores_train = -self._model.score_samples(X)  # flip sign: higher = more anomalous
        self._score_mean = float(raw_scores_train.mean())
        self._score_std = float(raw_scores_train.std()) or 1.0
        return self

    def anomaly_score(self, df: pd.DataFrame) -> np.ndarray:
        """Z-scored anomaly score. Sign: higher = more anomalous."""
        if self._model is None:
            raise RuntimeError("AnomalyVetoModel not fit")
        X = self._build(df)
        raw = -self._model.score_samples(X)
        return (raw - self._score_mean) / self._score_std

    def should_veto(self, df: pd.DataFrame, *, threshold_anomaly: float = 1.5) -> np.ndarray:
        """Returns boolean array: True where anomaly_score > threshold_anomaly."""
        return self.anomaly_score(df) > threshold_anomaly

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save(self, path: Path) -> None:
        if self._model is None:
            raise RuntimeError("nothing to save: AnomalyVetoModel not fit")
        payload = {
            "config": self.config.__dict__,
            "feature_cols": list(self._feature_cols),
            "imputer_medians": dict(self._imputer_medians),
            "score_mean": float(self._score_mean),
            "score_std": float(self._score_std),
            "model": self._model,
        }
        path.write_bytes(pickle.dumps(payload))

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "AnomalyVetoModel":
        """Rebuild from the pickle payload dict (bypasses the filesystem).

        The production loader reads bytes out of ``pl_model_artifact`` and
        deserializes via ``pickle.loads`` — no path is available. This
        classmethod accepts the resulting dict directly so we don't need a
        temp file detour at job start.
        """
        m = cls(AnomalyVetoConfig(**payload["config"]))
        m._feature_cols = tuple(payload["feature_cols"])
        m._imputer_medians = dict(payload["imputer_medians"])
        m._score_mean = float(payload["score_mean"])
        m._score_std = float(payload["score_std"])
        m._model = payload["model"]
        return m

    @classmethod
    def load(cls, path: Path) -> "AnomalyVetoModel":
        return cls.from_payload(pickle.loads(path.read_bytes()))

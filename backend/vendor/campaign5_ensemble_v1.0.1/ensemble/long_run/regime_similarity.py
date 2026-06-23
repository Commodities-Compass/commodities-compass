"""RegimeSimilarityModel — Campaign 4 Phase 3.5.

Given today's market state, returns the softmax-similarity of today's
month-state to past month-state clusters discovered on the 10y history.

The orchestrator (Phase 4-5) uses this to compute its `month_pattern_factor`:
each specialist's historical accuracy per cluster gets weighted by today's
similarity to that cluster, so specialists strong in similar past months
are upweighted.

Method:
    1. Aggregate the 10y daily dataset into MONTHLY feature vectors
       (mean return, daily-return vol, ATR percentile, momentum, regime share).
    2. Standardize features (z-score) over the historical monthly distribution.
    3. K-means cluster the past months (default k=4 — covers
       low-vol-bull, low-vol-bear, high-vol-bull, high-vol-bear).
       Smaller k = blunt; larger k = noisy.
    4. For a target date / month, compute its feature vector and the
       softmax-similarity to each cluster centroid (negative L2 distance →
       softmax).
    5. Output a (date → cluster_weights) DataFrame.

The clustering itself is unsupervised (no leakage); k is the only
hyperparameter, selected by silhouette on past months.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler


MONTHLY_FEATURE_COLS: tuple[str, ...] = (
    "month_mean_return",
    "month_vol_return",
    "month_max_drawdown",
    "month_mean_atr_14d",
    "month_momentum_22d",  # cumulative return over the last 22 trading days of the month
    "month_share_normal",
    "month_share_elevated",
    "month_share_bull",
    "month_share_crash",
)


@dataclass(frozen=True)
class RegimeSimilarityConfig:
    k_min: int = 2
    k_max: int = 6
    softmax_temperature: float = 1.0   # higher => more uniform similarity weights
    seed: int = 42


class RegimeSimilarityModel:
    """Cluster historical month-states; expose per-day similarity to each cluster.

    Public API:
        model.fit(df_10y_daily, regime_tags) -> self
        model.score_dates(df_daily, regime_tags) -> DataFrame[
            date, cluster_0_weight, cluster_1_weight, ...
        ]
    """

    def __init__(self, config: RegimeSimilarityConfig | None = None) -> None:
        self.config: RegimeSimilarityConfig = config or RegimeSimilarityConfig()
        self._kmeans: KMeans | None = None
        self._scaler: StandardScaler | None = None
        self._silhouette_by_k: dict[int, float] = {}
        self._k_final: int = 0
        self._feature_cols: tuple[str, ...] = MONTHLY_FEATURE_COLS

    # ------------------------------------------------------------------
    # Monthly feature builder
    # ------------------------------------------------------------------
    @staticmethod
    def _build_monthly_features(
        df_daily: pd.DataFrame,
        regime_tags: pd.DataFrame,
    ) -> pd.DataFrame:
        d = df_daily.copy()
        d["date"] = pd.to_datetime(d["date"])
        if "regime_id" not in d.columns:
            rt = regime_tags.copy()
            rt["date"] = pd.to_datetime(rt["date"])
            d = d.merge(rt[["date", "regime_id"]], on="date", how="left")
        d["ym"] = d["date"].dt.to_period("M")

        rows: list[dict] = []
        for ym, grp in d.groupby("ym"):
            if len(grp) < 5:
                continue
            ret = grp["daily_return"].astype(float)
            cum = (1.0 + ret).cumprod() - 1.0
            mom22 = float(cum.iloc[-1] - (cum.iloc[-23] if len(cum) >= 23 else cum.iloc[0]))
            row = {
                "ym": str(ym),
                "month_end_date": pd.to_datetime(grp["date"].max()),
                "n_days": int(len(grp)),
                "month_mean_return": float(ret.mean()),
                "month_vol_return": float(ret.std(ddof=0)),
                "month_max_drawdown": float((cum - cum.cummax()).min()),
                "month_mean_atr_14d": float(grp["atr_14d"].mean()) if "atr_14d" in grp.columns else 0.0,
                "month_momentum_22d": mom22,
                "month_share_normal": float((grp["regime_id"] == 1).mean()),
                "month_share_elevated": float((grp["regime_id"] == 2).mean()),
                "month_share_bull": float((grp["regime_id"] == 3).mean()),
                "month_share_crash": float((grp["regime_id"] == 0).mean()),
            }
            rows.append(row)
        return pd.DataFrame(rows).sort_values("month_end_date").reset_index(drop=True)

    # ------------------------------------------------------------------
    # Fit / predict
    # ------------------------------------------------------------------
    def fit(self, df_daily: pd.DataFrame, regime_tags: pd.DataFrame) -> "RegimeSimilarityModel":
        monthly = self._build_monthly_features(df_daily, regime_tags)
        X = monthly[list(self._feature_cols)].fillna(0.0).to_numpy(dtype=float)
        self._scaler = StandardScaler().fit(X)
        Xz = self._scaler.transform(X)

        best_k = self.config.k_min
        best_sil = float("-inf")
        for k in range(self.config.k_min, self.config.k_max + 1):
            km = KMeans(n_clusters=k, n_init=10, random_state=self.config.seed).fit(Xz)
            sil = float(silhouette_score(Xz, km.labels_)) if len(set(km.labels_)) > 1 else float("nan")
            self._silhouette_by_k[k] = sil
            if np.isfinite(sil) and sil > best_sil:
                best_sil = sil
                best_k = k

        self._k_final = int(best_k)
        self._kmeans = KMeans(n_clusters=self._k_final, n_init=10, random_state=self.config.seed).fit(Xz)
        # Attach the monthly feature table + cluster labels to the model
        # for downstream audit (orchestrator can ask "which past months
        # belong to cluster 2?").
        monthly = monthly.copy()
        monthly["cluster_id"] = self._kmeans.labels_
        self.monthly_features_ = monthly
        return self

    def cluster_weights(
        self,
        df_daily: pd.DataFrame,
        regime_tags: pd.DataFrame,
    ) -> pd.DataFrame:
        """For each MONTH in ``df_daily``, return softmax cluster-similarity weights.

        Returns: DataFrame indexed implicitly by row, with columns
            ``ym``, ``month_end_date``, ``cluster_0_weight``, ..., ``cluster_{k-1}_weight``.
        """
        if self._kmeans is None or self._scaler is None:
            raise RuntimeError("RegimeSimilarityModel not fit")
        monthly = self._build_monthly_features(df_daily, regime_tags)
        if monthly.empty:
            return pd.DataFrame(columns=["ym", "month_end_date"] + [f"cluster_{c}_weight" for c in range(self._k_final)])
        X = monthly[list(self._feature_cols)].fillna(0.0).to_numpy(dtype=float)
        Xz = self._scaler.transform(X)
        # Distance to each centroid
        centers = self._kmeans.cluster_centers_                       # (k, d)
        dists = np.linalg.norm(Xz[:, None, :] - centers[None, :, :], axis=2)   # (n, k)
        # softmax(-dist / temperature)
        T = max(float(self.config.softmax_temperature), 1e-6)
        logits = -dists / T
        logits -= logits.max(axis=1, keepdims=True)
        exp = np.exp(logits)
        weights = exp / exp.sum(axis=1, keepdims=True)
        out = pd.DataFrame({
            "ym": monthly["ym"].astype(str).values,
            "month_end_date": monthly["month_end_date"].values,
        })
        for c in range(self._k_final):
            out[f"cluster_{c}_weight"] = weights[:, c]
        return out

    # ------------------------------------------------------------------
    # Persistence — keep the kmeans + scaler so the orchestrator can
    # call score_dates on new days without retraining.
    # ------------------------------------------------------------------
    def save_json(self, path: Path) -> None:
        if self._kmeans is None or self._scaler is None:
            raise RuntimeError("nothing to save: model not fit")
        payload = {
            "config": self.config.__dict__,
            "feature_cols": list(self._feature_cols),
            "scaler_mean": list(map(float, self._scaler.mean_)),       # type: ignore[union-attr]
            "scaler_scale": list(map(float, self._scaler.scale_)),     # type: ignore[union-attr]
            "k_final": int(self._k_final),
            "silhouette_by_k": {int(k): float(v) for k, v in self._silhouette_by_k.items()},
            "centers": [list(map(float, c)) for c in self._kmeans.cluster_centers_],
        }
        path.write_text(json.dumps(payload, indent=2))

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "RegimeSimilarityModel":
        """Reconstruct a fitted model from a ``save_json`` payload dict.

        The pipeline reads ``regime_clusters.json`` out of ``pl_model_artifact``
        and calls this constructor — no temp file needed. Only the parts used
        by ``cluster_weights`` are rehydrated: the StandardScaler's
        mean_/scale_, and a KMeans-like object exposing ``cluster_centers_``
        (the distance computation does not need ``predict()``).
        """
        cfg = RegimeSimilarityConfig(**payload["config"])
        model = cls(cfg)
        model._feature_cols = tuple(payload.get("feature_cols", MONTHLY_FEATURE_COLS))
        model._silhouette_by_k = {int(k): float(v) for k, v in payload.get("silhouette_by_k", {}).items()}
        k_final = int(payload["k_final"])
        model._k_final = k_final

        scaler = StandardScaler()
        scaler.mean_ = np.asarray(payload["scaler_mean"], dtype=float)
        scaler.scale_ = np.asarray(payload["scaler_scale"], dtype=float)
        scaler.var_ = scaler.scale_ ** 2
        scaler.n_features_in_ = int(len(scaler.mean_))
        model._scaler = scaler

        # The KMeans estimator only needs cluster_centers_ for the orchestrator's
        # distance computation; we hand-set it instead of calling .fit (which
        # would require the training data we no longer have).
        kmeans = KMeans(n_clusters=k_final, n_init=10, random_state=int(cfg.seed))
        kmeans.cluster_centers_ = np.asarray(payload["centers"], dtype=float)
        model._kmeans = kmeans
        return model

    @classmethod
    def load_json(cls, path: Path) -> "RegimeSimilarityModel":
        """Filesystem convenience wrapper around ``from_payload``."""
        return cls.from_payload(json.loads(Path(path).read_text()))

"""ControleStackingMeta — Contrôle layer.

Spec §4.7. Stacks base candidate probabilities + regime hints via a meta
estimator (logistic or LightGBM), with MONITOR abstention.

TSOOF stacking (time-series out-of-fold):
    For each base model:
        1. Split train into ``n_splits`` ordered TimeSeriesSplit folds.
        2. For each inner fold, fit base on inner-train, predict_proba on inner-val
           -> OOF probas covering the entire training window (causally).
        3. Re-fit base on FULL training window (used at inference time).
    Meta is trained on the OOF probas + regime/derived features.

MONITOR rule:
    if max(P) < tau_conf:                              -> MONITOR
    if |P_spot_DOWN - P_mom_DOWN| > tau_diss:          -> MONITOR
    else: HEDGE if P_down > P_up else OPEN
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit

from ensemble.models.base import CLASS_INDEX, CLASS_ORDER, CandidateModel, target_to_decision
from ensemble.models.sklearn_candidate import make_estimator


@dataclass(frozen=True)
class MetaInputs:
    p_down_spot: np.ndarray
    p_down_mom: np.ndarray
    p_down_fund: np.ndarray
    p_up_spot: np.ndarray
    p_up_mom: np.ndarray
    p_up_fund: np.ndarray
    disagreement: np.ndarray
    atr_state: np.ndarray

    def to_matrix(self) -> np.ndarray:
        return np.column_stack([
            self.p_down_spot,
            self.p_down_mom,
            self.p_down_fund,
            self.p_up_spot,
            self.p_up_mom,
            self.p_up_fund,
            self.disagreement,
            self.atr_state,
        ])


class ControleStackingMeta(CandidateModel):
    name = "controle_stacking_meta"
    feature_group = "meta"

    def __init__(
        self,
        *,
        base_spot: CandidateModel,
        base_mom: CandidateModel,
        base_fund: CandidateModel,
        meta_family: str = "logistic",
        meta_hp: dict[str, Any] | None = None,
        threshold_monitor: float = 0.55,
        threshold_disagreement: float = 0.30,
        n_splits_oof: int = 5,
        random_state: int = 42,
        cv_splitter=None,  # if provided, used instead of TimeSeriesSplit (e.g. PurgedKFold)
    ) -> None:
        super().__init__(random_state=random_state)
        self._base_spot = base_spot
        self._base_mom = base_mom
        self._base_fund = base_fund
        self._meta_family = meta_family
        self._meta_hp: dict[str, Any] = dict(meta_hp or {})
        self.threshold_monitor: float = float(threshold_monitor)
        self.threshold_disagreement: float = float(threshold_disagreement)
        self.n_splits_oof: int = int(n_splits_oof)
        self._meta = make_estimator(meta_family, random_state, hp=self._meta_hp)
        self._meta_classes_: np.ndarray | None = None
        self._atr_med: float = 0.0
        self._atr_std: float = 1.0
        self._cv_splitter = cv_splitter

    def _atr_state(self, df: pd.DataFrame) -> np.ndarray:
        if "atr_14d" not in df.columns:
            return np.zeros(len(df), dtype=float)
        atr = df["atr_14d"].astype(float).to_numpy()
        return (atr - self._atr_med) / max(self._atr_std, 1e-9)

    def _fit_base_oof(
        self,
        base: CandidateModel,
        df_train: pd.DataFrame,
        y_train: pd.Series,
    ) -> np.ndarray:
        """Return OOF predict_proba covering the full training window.

        If ``self._cv_splitter`` is provided (e.g. PurgedKFold), uses it; else
        defaults to ``TimeSeriesSplit(n_splits=self.n_splits_oof)``.
        """
        oof = np.zeros((len(df_train), 3), dtype=float)
        splitter = self._cv_splitter if self._cv_splitter is not None else TimeSeriesSplit(n_splits=self.n_splits_oof)
        # TimeSeriesSplit does NOT cover the very first chunk before the first fold's val.
        # We fill it with the first fold's train-only model's prediction.
        first_val_start = None
        for fold_idx, (tr_idx, va_idx) in enumerate(splitter.split(df_train)):
            if first_val_start is None:
                first_val_start = int(va_idx[0])
            fold_cand = base.__class__(
                **{k: getattr(base, k) for k in ()},
            ) if False else None  # placeholder; we use a deep-copy proxy below
            # We'll build a fresh estimator via a factory closure (callers control this).
            # Practical compromise: re-call the base.fit on its inner DataFrame slice.
            base_copy = _shallow_clone(base)
            base_copy.fit(df_train.iloc[tr_idx], y_train.iloc[tr_idx])
            oof[va_idx, :] = base_copy.predict_proba(df_train.iloc[va_idx])
        # Backfill the pre-first-val region with the first fold's model fit on its tr_idx.
        if first_val_start is not None and first_val_start > 0:
            warm_splitter = self._cv_splitter if self._cv_splitter is not None else TimeSeriesSplit(n_splits=self.n_splits_oof)
            tr_idx_first, va_idx_first = next(warm_splitter.split(df_train))
            warm = _shallow_clone(base)
            warm.fit(df_train.iloc[tr_idx_first], y_train.iloc[tr_idx_first])
            oof[:first_val_start, :] = warm.predict_proba(df_train.iloc[:first_val_start])
        return oof

    def _disagreement(self, p_spot: np.ndarray, p_mom: np.ndarray) -> np.ndarray:
        return np.abs(p_spot[:, CLASS_INDEX["DOWN"]] - p_mom[:, CLASS_INDEX["DOWN"]])

    def _meta_inputs(
        self,
        p_spot: np.ndarray,
        p_mom: np.ndarray,
        p_fund: np.ndarray,
        df: pd.DataFrame,
    ) -> MetaInputs:
        return MetaInputs(
            p_down_spot=p_spot[:, CLASS_INDEX["DOWN"]],
            p_down_mom=p_mom[:, CLASS_INDEX["DOWN"]],
            p_down_fund=p_fund[:, CLASS_INDEX["DOWN"]],
            p_up_spot=p_spot[:, CLASS_INDEX["UP"]],
            p_up_mom=p_mom[:, CLASS_INDEX["UP"]],
            p_up_fund=p_fund[:, CLASS_INDEX["UP"]],
            disagreement=self._disagreement(p_spot, p_mom),
            atr_state=self._atr_state(df),
        )

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        *,
        sample_weight: np.ndarray | None = None,
    ) -> "ControleStackingMeta":
        # ATR normalization fit on TRAIN window only (no global leakage)
        if "atr_14d" in X_train.columns:
            self._atr_med = float(np.nanmedian(X_train["atr_14d"]))
            self._atr_std = float(np.nanstd(X_train["atr_14d"]))
        # OOF probas for each base — note OOF folds don't propagate sample_weight cleanly,
        # so we rely on the final-fit weights below to bias the inference model.
        oof_spot = self._fit_base_oof(self._base_spot, X_train, y_train)
        oof_mom = self._fit_base_oof(self._base_mom, X_train, y_train)
        oof_fund = self._fit_base_oof(self._base_fund, X_train, y_train)

        # Final base models trained on FULL train window WITH sample_weight if provided.
        if sample_weight is not None:
            self._base_spot.fit(X_train, y_train, sample_weight=sample_weight)
            self._base_mom.fit(X_train, y_train, sample_weight=sample_weight)
            self._base_fund.fit(X_train, y_train, sample_weight=sample_weight)
        else:
            self._base_spot.fit(X_train, y_train)
            self._base_mom.fit(X_train, y_train)
            self._base_fund.fit(X_train, y_train)

        # Meta on OOF features (sample_weight also routed to meta if provided)
        meta_X = self._meta_inputs(oof_spot, oof_mom, oof_fund, X_train).to_matrix()
        meta_X = np.nan_to_num(meta_X, nan=0.0, posinf=0.0, neginf=0.0)
        meta_fit_kwargs: dict[str, np.ndarray] = {}
        if sample_weight is not None:
            sw = np.asarray(sample_weight, dtype=float)
            if hasattr(self._meta, "named_steps"):
                meta_fit_kwargs["clf__sample_weight"] = sw
            else:
                meta_fit_kwargs["sample_weight"] = sw
        try:
            self._meta.fit(meta_X, np.asarray(y_train), **meta_fit_kwargs)
        except (TypeError, ValueError) as exc:
            if sample_weight is not None and "sample_weight" in str(exc):
                self._meta.fit(meta_X, np.asarray(y_train))
            else:
                raise
        clf = self._meta
        if hasattr(clf, "named_steps"):
            clf = clf.named_steps["clf"]
        self._meta_classes_ = np.array(clf.classes_)
        self._is_fit = True
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not self._is_fit:
            raise RuntimeError("meta not fit")
        p_spot = self._base_spot.predict_proba(X)
        p_mom = self._base_mom.predict_proba(X)
        p_fund = self._base_fund.predict_proba(X)
        meta_X = self._meta_inputs(p_spot, p_mom, p_fund, X).to_matrix()
        meta_X = np.nan_to_num(meta_X, nan=0.0, posinf=0.0, neginf=0.0)
        raw = self._meta.predict_proba(meta_X)
        out = np.zeros((len(raw), 3), dtype=float)
        if self._meta_classes_ is None:
            raise RuntimeError("meta_classes_ unset")
        for j, cls in enumerate(self._meta_classes_):
            if cls in CLASS_INDEX:
                out[:, CLASS_INDEX[cls]] = raw[:, j]
        row_sums = out.sum(axis=1, keepdims=True)
        row_sums[row_sums == 0.0] = 1.0
        return out / row_sums

    def predict_label(
        self,
        X: pd.DataFrame,
        *,
        threshold_monitor: float | None = None,
    ) -> np.ndarray:
        """Override base predict_label to use the dual (confidence + disagreement) MONITOR rule."""
        tau_conf = (
            float(threshold_monitor) if threshold_monitor is not None else self.threshold_monitor
        )
        probs = self.predict_proba(X)
        p_spot = self._base_spot.predict_proba(X)
        p_mom = self._base_mom.predict_proba(X)
        disagreement = self._disagreement(p_spot, p_mom)
        out = np.empty(len(probs), dtype=object)
        max_p = probs.max(axis=1)
        argmax = probs.argmax(axis=1)
        for i in range(len(probs)):
            if max_p[i] < tau_conf:
                out[i] = "MONITOR"
            elif disagreement[i] > self.threshold_disagreement:
                out[i] = "MONITOR"
            else:
                out[i] = target_to_decision(CLASS_ORDER[argmax[i]])
        return out

    @property
    def hyperparameters(self) -> dict:
        return {
            "name": self.name,
            "meta_family": self._meta_family,
            "threshold_monitor": self.threshold_monitor,
            "threshold_disagreement": self.threshold_disagreement,
            "n_splits_oof": self.n_splits_oof,
            "random_state": self.random_state,
            "meta_hp": self._meta_hp,
        }


def _shallow_clone(cand: CandidateModel) -> CandidateModel:
    """Make a fresh, unfit copy of a candidate by re-invoking its class with hyperparameters."""
    import copy

    new = copy.copy(cand)
    new._is_fit = False
    # For SklearnCandidate, rebuild the estimator to clear any fit state
    if hasattr(new, "_estimator") and hasattr(new, "_family") and hasattr(new, "_hp"):
        new._estimator = make_estimator(new._family, new.random_state, hp=new._hp)
        new._kept_cols = None
        new._impute_values = {}
        new._classes_ = None
    return new

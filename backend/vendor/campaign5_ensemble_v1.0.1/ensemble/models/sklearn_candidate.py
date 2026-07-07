"""Generic sklearn / LightGBM wrapper implementing the CandidateModel contract.

Used to construct Spot / Momentum / Fundamentals candidates with a single
underlying class — only the FeatureSpec set differs.

Determinism:
    - sklearn estimators: random_state=42 set at construction.
    - LightGBM: deterministic=True, force_row_wise=True, num_threads=1
      (CLAUDE.md non-negotiable; slower but reproducible bit-for-bit).
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ensemble.features import FeatureSpec, build_feature_matrix
from ensemble.models.base import CLASS_INDEX, CLASS_ORDER, CandidateModel

ModelFamily = Literal["logistic", "random_forest", "lightgbm"]


def _lightgbm_classifier(**kwargs: Any):
    import lightgbm as lgb

    base = dict(
        deterministic=True,
        force_row_wise=True,
        num_threads=1,
        verbose=-1,
        objective="multiclass",
        num_class=3,
    )
    base.update(kwargs)
    return lgb.LGBMClassifier(**base)


def make_estimator(
    family: ModelFamily,
    random_state: int = 42,
    *,
    hp: dict[str, Any] | None = None,
):
    """Construct an sklearn-API estimator for the requested family.

    For logistic/RF, wraps in a Pipeline with StandardScaler (logistic) or raw (RF/LGBM).
    """
    hp = hp or {}
    if family == "logistic":
        clf = LogisticRegression(
            C=float(hp.get("C", 1.0)),
            penalty=hp.get("penalty", "l2"),
            solver=hp.get("solver", "lbfgs"),
            max_iter=int(hp.get("max_iter", 1000)),
            multi_class="auto",
            random_state=random_state,
            n_jobs=1,
        )
        return Pipeline([("scaler", StandardScaler(with_mean=True, with_std=True)), ("clf", clf)])
    if family == "random_forest":
        return RandomForestClassifier(
            n_estimators=int(hp.get("n_estimators", 200)),
            max_depth=hp.get("max_depth", 5),
            min_samples_leaf=int(hp.get("min_samples_leaf", 5)),
            random_state=random_state,
            n_jobs=1,
        )
    if family == "lightgbm":
        return _lightgbm_classifier(
            n_estimators=int(hp.get("n_estimators", 200)),
            max_depth=int(hp.get("max_depth", 4)),
            learning_rate=float(hp.get("learning_rate", 0.05)),
            min_child_samples=int(hp.get("min_samples_leaf", 20)),
            random_state=random_state,
            seed=random_state,
        )
    raise ValueError(f"Unknown family: {family!r}")


class SklearnCandidate(CandidateModel):
    """Sklearn-API-driven CandidateModel that builds its own feature matrix.

    Parameters
    ----------
    feature_specs : list[FeatureSpec]
        Feature specs to assemble from the source DataFrame.
    family : ModelFamily
        Estimator family.
    hp : dict
        Hyperparameters passed to the estimator family.
    fill_strategy : str
        How to handle NaN in features. "drop_columns_over" drops any column whose
        NaN fraction in TRAIN exceeds ``fill_max_null``. Remaining NaNs ffilled, then median-imputed.
    """

    is_calibrated = False

    def __init__(
        self,
        *,
        name: str,
        feature_specs: list[FeatureSpec] | tuple[FeatureSpec, ...],
        feature_group: Literal["spot", "momentum", "fundamental", "meta", "baseline"] = "spot",
        family: ModelFamily = "logistic",
        hp: dict[str, Any] | None = None,
        random_state: int = 42,
        fill_max_null: float = 0.80,
    ) -> None:
        super().__init__(random_state=random_state)
        self._name = name
        self._feature_specs: tuple[FeatureSpec, ...] = tuple(feature_specs)
        self._feature_group_runtime = feature_group
        self._family: ModelFamily = family
        self._hp: dict[str, Any] = dict(hp or {})
        self._fill_max_null: float = float(fill_max_null)

        self._estimator = make_estimator(family, random_state, hp=self._hp)
        self._kept_cols: list[str] | None = None
        self._impute_values: dict[str, float] = {}
        self._classes_: np.ndarray | None = None

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    @property
    def feature_group(self) -> str:  # type: ignore[override]
        return self._feature_group_runtime

    def _build(self, df: pd.DataFrame) -> pd.DataFrame:
        return build_feature_matrix(df, list(self._feature_specs))

    def _fit_imputer(self, X: pd.DataFrame) -> pd.DataFrame:
        # Drop high-null columns based on TRAIN window only.
        null_share = X.isna().mean() if len(X.columns) > 0 else pd.Series(dtype=float)
        self._kept_cols = [c for c in X.columns if null_share[c] <= self._fill_max_null]
        # Fallback: if all features were dropped, inject a constant column so sklearn
        # doesn't crash with "0 features". The model degenerates to a class-prior predictor.
        if not self._kept_cols:
            X = X.assign(__const__=0.0)
            self._kept_cols = ["__const__"]
        X = X[self._kept_cols]
        # ffill within column, then fill remaining NaN with column median.
        X = X.ffill()
        for c in self._kept_cols:
            med = float(X[c].median(skipna=True))
            if np.isnan(med):
                med = 0.0
            self._impute_values[c] = med
            X[c] = X[c].fillna(med)
        return X

    def _apply_imputer(self, X: pd.DataFrame) -> pd.DataFrame:
        if self._kept_cols is None:
            raise RuntimeError("SklearnCandidate not fit; call .fit(...) first.")
        # Ensure the constant fallback exists if it was used at fit time.
        if "__const__" in self._kept_cols and "__const__" not in X.columns:
            X = X.assign(__const__=0.0)
        X = X.reindex(columns=self._kept_cols)
        X = X.ffill()
        for c in self._kept_cols:
            X[c] = X[c].fillna(self._impute_values.get(c, 0.0))
        return X

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        *,
        sample_weight: np.ndarray | None = None,
    ) -> "SklearnCandidate":
        """Fit on raw source DataFrame X_train (NOT a pre-built feature matrix).

        We rebuild features internally so the column-drop policy is FOLD-LOCAL
        (no global leakage). y_train must be aligned to X_train index.

        ``sample_weight``: optional per-row weight (shape ``(len(X_train),)``).
        Routed to the underlying estimator's ``fit`` via sklearn's
        ``Pipeline.fit(..., clf__sample_weight=...)`` convention when wrapped, or
        directly when the estimator is bare.
        """
        X = self._build(X_train)
        X = self._fit_imputer(X)
        y = np.asarray(y_train)
        # Order classes by CLASS_ORDER so predict_proba columns are stable.
        # sklearn sorts classes alphabetically when string — verify and reorder if needed.
        fit_kwargs: dict[str, np.ndarray] = {}
        if sample_weight is not None:
            sw = np.asarray(sample_weight, dtype=float)
            if len(sw) != len(X):
                raise ValueError(f"sample_weight length {len(sw)} != X length {len(X)}")
            if hasattr(self._estimator, "named_steps"):
                fit_kwargs["clf__sample_weight"] = sw
            else:
                fit_kwargs["sample_weight"] = sw
        try:
            self._estimator.fit(X.to_numpy(), y, **fit_kwargs)
        except (TypeError, ValueError) as exc:
            # Some estimators may not accept sample_weight on certain solvers; fall back silently.
            if sample_weight is not None and "sample_weight" in str(exc):
                self._estimator.fit(X.to_numpy(), y)
            else:
                raise
        clf = self._estimator
        if hasattr(clf, "named_steps"):
            clf = clf.named_steps["clf"]
        self._classes_ = np.array(clf.classes_)
        self._is_fit = True
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not self._is_fit:
            raise RuntimeError(f"{self.name}: predict_proba called before fit")
        Xb = self._build(X)
        Xb = self._apply_imputer(Xb)
        raw = self._estimator.predict_proba(Xb.to_numpy())
        # Reorder columns to CLASS_ORDER (DOWN, FLAT, UP).
        if self._classes_ is None:
            raise RuntimeError("classes_ not populated after fit")
        out = np.zeros((len(raw), 3), dtype=float)
        for j, cls in enumerate(self._classes_):
            if cls in CLASS_INDEX:
                out[:, CLASS_INDEX[cls]] = raw[:, j]
        # If model never saw FLAT/UP/DOWN, the missing column is zero; renormalize.
        row_sums = out.sum(axis=1, keepdims=True)
        row_sums[row_sums == 0.0] = 1.0
        return out / row_sums

    @property
    def hyperparameters(self) -> dict:
        return {
            "name": self._name,
            "family": self._family,
            "feature_group": self._feature_group_runtime,
            "random_state": self.random_state,
            "fill_max_null": self._fill_max_null,
            "n_features": len(self._feature_specs),
            **self._hp,
        }

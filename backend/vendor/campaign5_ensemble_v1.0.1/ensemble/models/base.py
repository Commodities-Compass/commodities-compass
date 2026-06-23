"""CandidateModel ABC: contract every algorithm in the framework must satisfy.

Spec: methodology/framework-spec.md §4.4.

Probability ordering convention (DIFFERS slightly from spec example):
    predict_proba returns shape (n, 3) where the 3 columns are in the order
    CLASS_ORDER = [DOWN, FLAT, UP].

The spec's example used [UP, FLAT, DOWN]; we use [DOWN, FLAT, UP] which matches
pandas' Categorical sort order for the labels in targets.py. This is the SINGLE
source of truth — every base model, every meta, every metric uses this order.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import ClassVar, Literal

import numpy as np
import pandas as pd

Decision = Literal["OPEN", "HEDGE", "MONITOR"]
TargetClass = Literal["DOWN", "FLAT", "UP"]

CLASS_ORDER: tuple[TargetClass, ...] = ("DOWN", "FLAT", "UP")
DECISION_ORDER: tuple[Decision, ...] = ("HEDGE", "MONITOR", "OPEN")

CLASS_INDEX: dict[str, int] = {cls: i for i, cls in enumerate(CLASS_ORDER)}


def target_to_decision(target: str) -> Decision:
    """Map a 3-class label to the corresponding committed decision (no MONITOR)."""
    if target == "DOWN":
        return "HEDGE"
    if target == "UP":
        return "OPEN"
    if target == "FLAT":
        return "MONITOR"
    raise ValueError(f"Unknown target class: {target!r}")


def set_global_seed(seed: int) -> None:
    """Pin Python random, NumPy global RNG, and PYTHONHASHSEED-style state.

    Per CLAUDE.md, library code should still avoid global state — but some sklearn
    estimators (and LightGBM in some paths) reach for globals. Belt-and-braces.
    """
    random.seed(seed)
    np.random.seed(seed)


class CandidateModel(ABC):
    """Abstract contract for any decision algorithm.

    Concrete subclasses MUST:
      - set ``random_state`` at construction (CLAUDE.md non-negotiable)
      - implement ``fit``, ``predict_proba``, ``confidence``, ``hyperparameters``
      - ``predict_proba`` must be deterministic at inference time
    """

    name: ClassVar[str] = "candidate"
    feature_group: ClassVar[Literal["spot", "momentum", "fundamental", "meta", "baseline"]] = "baseline"
    is_calibrated: ClassVar[bool] = False
    requires_training: ClassVar[bool] = True

    def __init__(self, *, random_state: int = 42) -> None:
        self.random_state: int = int(random_state)
        self._is_fit: bool = False

    @abstractmethod
    def fit(self, X_train: pd.DataFrame, y_train: pd.Series) -> "CandidateModel":  # noqa: D401
        """Fit on X_train + y_train and return self."""

    @abstractmethod
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return shape (n, 3) with columns in CLASS_ORDER = (DOWN, FLAT, UP)."""

    def confidence(self, X: pd.DataFrame) -> np.ndarray:
        """Default: max class probability. Subclasses may override (e.g. calibration)."""
        return self.predict_proba(X).max(axis=1)

    def predict_label(
        self,
        X: pd.DataFrame,
        *,
        threshold_monitor: float = 0.0,
    ) -> np.ndarray:
        """Map class probabilities to a Decision.

        If max(P) < threshold_monitor -> MONITOR.
        Else argmax over (DOWN, FLAT, UP) -> (HEDGE, MONITOR, OPEN).
        """
        probs = self.predict_proba(X)
        argmax = probs.argmax(axis=1)
        max_p = probs.max(axis=1)
        out = np.empty(len(probs), dtype=object)
        for i, (idx, mp) in enumerate(zip(argmax, max_p, strict=True)):
            if mp < threshold_monitor:
                out[i] = "MONITOR"
            else:
                out[i] = target_to_decision(CLASS_ORDER[idx])
        return out

    @property
    @abstractmethod
    def hyperparameters(self) -> dict:
        """Used in experiment metadata."""

    def get_random_state(self) -> int:
        return self.random_state

    @property
    def is_fit(self) -> bool:
        return self._is_fit

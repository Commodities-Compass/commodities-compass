"""MonthlyRetrainer — Campaign 4 Phase 1.

For each (specialist, prediction_month, window_length) triple:
    1. Slice the canonical dataset to the training window [M-N months, M).
    2. Apply the specialist's target_fn + feature_specs_override + sample_weight_fn.
       NOTE: for window_months >= 6, anti-bias is FORCED ON (user mandate 2026-05-17).
    3. Build the candidate from the Phase 0c/d top-1 HPs.
    4. Fit on the training slice.
    5. Predict on all trading days in the prediction month.
    6. Return per-row predictions + diagnostic dict (incl realised class balance).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json

import numpy as np
import pandas as pd

from ensemble.models.meta import ControleStackingMeta
from ensemble.optimizer.objective import (
    FUND_FACTORIES,
    MOM_FACTORIES,
    SPOT_FACTORIES,
    _build_candidate,
)
from ensemble.optimizer.specialists import (
    SpecialistArchitecture,
    make_antibias_sw_fn,
)
from ensemble.targets import compute_3class_target


@dataclass(frozen=True)
class SpecialistWindowConfig:
    """Per-specialist allowed window lengths.

    Default: [3, 6]. GARCH-using specialists need >=500 training rows, so only N=24
    is meaningful for them; the runner skips N=3 and N=6 for those.
    """
    name: str
    window_months_list: tuple[int, ...]


@dataclass(frozen=True)
class MonthlyRetrainResult:
    specialist_name: str
    window_months: int
    year: int
    month: int
    n_train: int
    n_test: int
    n_committed: int
    n_correct: int
    accuracy: float
    coverage: float
    class_balance_train: dict[str, float]   # UP/FLAT/DOWN share in training labels
    class_balance_imbalanced: bool          # True if any class share > 0.70
    antibias_forced: bool                   # True if anti-bias was forced on due to window>=6
    per_row: pd.DataFrame = field(default_factory=pd.DataFrame)


class MonthlyRetrainer:
    """Rolling-window monthly retrain for a single specialist architecture.

    The training window has length ``window_months`` and ends on the first day of
    the prediction month (exclusive). The candidate is built from the Phase 0c/d
    top-1 HPs persisted at ``output/exp_optim_018c__<name>/top1_config.json``.
    """

    def __init__(
        self,
        specialist: SpecialistArchitecture,
        top1_config_summary: dict[str, Any],
        *,
        seed: int = 42,
    ) -> None:
        self.specialist = specialist
        self.cfg = top1_config_summary
        self.seed = int(top1_config_summary.get("seed", seed))

    @classmethod
    def from_top1_path(
        cls,
        specialist: SpecialistArchitecture,
        top1_path: Path,
    ) -> "MonthlyRetrainer":
        d = json.loads(top1_path.read_text())
        cs = d.get("config_summary") or d.get("user_attrs", {}).get("config_summary")
        if not cs:
            raise ValueError(f"top1 file missing config_summary: {top1_path}")
        return cls(specialist, cs)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _make_candidate(self) -> ControleStackingMeta:
        """Build a fresh, unfit candidate from the top-1 config."""
        cs = self.cfg
        spot_specs, mom_specs, fund_specs = self.specialist.build_feature_specs()
        spot = _build_candidate(
            SPOT_FACTORIES, cs["base_family_spot"], spot_specs,
            dict(cs["base_hp_spot"]), self.seed,
        )
        mom = _build_candidate(
            MOM_FACTORIES, cs["base_family_mom"], mom_specs,
            dict(cs["base_hp_mom"]), self.seed,
        )
        fund = _build_candidate(
            FUND_FACTORIES, cs["base_family_fund"], fund_specs,
            dict(cs["base_hp_fund"]), self.seed,
        )
        return ControleStackingMeta(
            base_spot=spot,
            base_mom=mom,
            base_fund=fund,
            meta_family=cs["meta_family"],
            meta_hp=dict(cs["meta_hp"]),
            threshold_monitor=float(cs["tau_conf"]),
            threshold_disagreement=float(cs["tau_diss"]),
            random_state=self.seed,
        )

    def _resolve_target(self, train: pd.DataFrame) -> pd.Series:
        """Compute target labels for the training slice (target_fn-aware)."""
        spec = self.specialist
        if spec.target_fn is None:
            atr_m = float(self.cfg.get("target_atr_multiple", 0.5))
            return compute_3class_target(train, horizon=spec.horizon, atr_multiple=atr_m)
        try:
            return spec.target_fn(train, horizon=spec.horizon, **spec.target_kwargs)
        except TypeError:
            return spec.target_fn(train, **spec.target_kwargs)

    def _resolve_sample_weight_fn(self, *, window_months: int):
        """Anti-bias policy:
            window_months >= 6 -> FORCE anti-bias on (user mandate 2026-05-17,
            protects against UP/DOWN imbalance leaking back into training).
            window_months < 6  -> respect specialist's own use_antibias flag.
        """
        spec = self.specialist
        if window_months >= 6:
            return make_antibias_sw_fn(
                halflife_days=spec.halflife_days,
                extra_class_weight=spec.extra_class_weight,
            ), True
        return spec.build_sample_weight_fn(), False

    @staticmethod
    def _class_balance(y: pd.Series) -> dict[str, float]:
        s = pd.Series(y).value_counts(normalize=True)
        return {c: float(s.get(c, 0.0)) for c in ("DOWN", "FLAT", "UP")}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def predict_month(
        self,
        df: pd.DataFrame,
        *,
        year: int,
        month: int,
        window_months: int,
    ) -> MonthlyRetrainResult:
        """Train on [month-N, month), predict on `month`, return diagnostics + per-row."""
        if window_months <= 0:
            raise ValueError(f"window_months must be > 0, got {window_months}")

        train_end = pd.Timestamp(year, month, 1)
        train_start = train_end - pd.DateOffset(months=window_months)
        next_month_start = train_end + pd.DateOffset(months=1)

        train = df[(df["date"] >= train_start) & (df["date"] < train_end)].reset_index(drop=True)
        test = df[(df["date"] >= train_end) & (df["date"] < next_month_start)].reset_index(drop=True)

        if len(train) < 10 or len(test) == 0:
            return MonthlyRetrainResult(
                specialist_name=self.specialist.name,
                window_months=window_months,
                year=year, month=month,
                n_train=len(train), n_test=len(test),
                n_committed=0, n_correct=0,
                accuracy=float("nan"), coverage=0.0,
                class_balance_train={"DOWN": 0.0, "FLAT": 0.0, "UP": 0.0},
                class_balance_imbalanced=False,
                antibias_forced=False,
                per_row=pd.DataFrame(),
            )

        # Targets + class balance audit
        y_train = self._resolve_target(train)
        balance = self._class_balance(y_train)
        imbalanced = bool(max(balance.values()) > 0.70)

        # Hard validation: even after the per-architecture min_window_months filter,
        # certain slices may still produce single-class labels (e.g., low-volatility
        # months with TB labels). Raise rather than silently fit on degenerate data
        # — the caller is expected to be running on a window the architecture
        # supports. A degenerate slice here means the architectural minimum is
        # wrong and needs to be raised (NOT that we should hide the failure).
        n_classes = int(pd.Series(y_train).nunique())
        if n_classes < 2:
            present = sorted(pd.Series(y_train).unique().tolist())
            raise ValueError(
                f"Degenerate training labels for {self.specialist.name!r} "
                f"on window={window_months}mo, predict={year}-{month:02d}: "
                f"only class {present!r} present out of expected 3. "
                f"n_train={len(train)}, target_fn="
                f"{getattr(self.specialist.target_fn, '__name__', 'baseline')}, "
                f"max_horizon={self.specialist.target_kwargs.get('max_horizon', '?')}. "
                f"Raise specialist.min_window_months to a value that yields "
                f"multi-class labels on this market regime."
            )

        # Sample weights (anti-bias policy)
        sw_fn, antibias_forced = self._resolve_sample_weight_fn(window_months=window_months)
        sw = sw_fn(train, y_train) if sw_fn is not None else None

        # Fit candidate
        cand = self._make_candidate()
        try:
            if sw is not None:
                cand.fit(train, y_train, sample_weight=sw)
            else:
                cand.fit(train, y_train)
        except (TypeError, ValueError) as exc:
            if sw is not None and "sample_weight" in str(exc):
                cand.fit(train, y_train)
            else:
                raise

        # Predict
        pred = cand.predict_label(test)

        # Score against forward return (sign-based correctness, same scheme as v1)
        horizon = int(self.specialist.horizon)
        fwd_col = f"forward_return_{horizon}d"
        if fwd_col not in test.columns:
            raise ValueError(f"test slice missing {fwd_col!r}")
        fwd = test[fwd_col].to_numpy()

        # Correctness: HEDGE+down=correct, OPEN+up=correct, MONITOR=abstain
        is_committed = pred != "MONITOR"
        committed_correct = (
            ((pred == "HEDGE") & (fwd < 0))
            | ((pred == "OPEN") & (fwd > 0))
        )
        n_committed = int(is_committed.sum())
        n_correct = int(committed_correct.sum())
        coverage = float(n_committed / len(test)) if len(test) > 0 else 0.0
        accuracy = float(n_correct / n_committed) if n_committed > 0 else float("nan")

        per_row = pd.DataFrame({
            "date": test["date"].values,
            "pred": pred,
            "forward_return": fwd,
            "year": pd.to_datetime(test["date"]).dt.year.values,
            "month": pd.to_datetime(test["date"]).dt.month.values,
            "committed": is_committed,
            "correct": committed_correct,
        })

        return MonthlyRetrainResult(
            specialist_name=self.specialist.name,
            window_months=window_months,
            year=year, month=month,
            n_train=len(train), n_test=len(test),
            n_committed=n_committed, n_correct=n_correct,
            accuracy=accuracy, coverage=coverage,
            class_balance_train=balance,
            class_balance_imbalanced=imbalanced,
            antibias_forced=antibias_forced,
            per_row=per_row,
        )

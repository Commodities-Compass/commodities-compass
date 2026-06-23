"""StructuralPriors — long-horizon empirical Bayesian prior holder.

Persists the [ABSOLUTE] established facts (RD-002 4 HMM regimes; LT-001
12mo-volume ↔ 12mo-return ρ=0.42; DP-005 volatility-driven regime structure)
as a conditional distribution that the Phase 4-5 orchestrator can use to
Bayesian-update short-run specialist outputs.

Implementation: bin the historical 10y window by (regime × 12mo_volume_tercile
× 12mo_return_tercile) and compute P(forward_return_h_sign | bin). At
inference, look up today's bin and return prior over {OPEN, HEDGE, MONITOR}.

We DO NOT smooth the bins because:
    1. Sparse bins are themselves information (rare regime states are flagged
       to the orchestrator via low n_train, which the orchestrator can use
       to dial back the prior weight).
    2. Bayesian smoothing introduces an arbitrary prior-of-priors which
       conflicts with the [METHOD-TIED] tag we want to keep on these priors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
import json

import numpy as np
import pandas as pd


Decision = Literal["OPEN", "HEDGE", "MONITOR"]
DECISIONS: tuple[Decision, ...] = ("OPEN", "HEDGE", "MONITOR")


@dataclass(frozen=True)
class PriorContext:
    """Slot for the orchestrator: today's context bucket."""
    regime_id: int             # 0..3 (Crash, Normal, Elevated, Bull)
    vol_12m_tercile: int       # 0 (low), 1 (mid), 2 (high)
    return_12m_tercile: int    # 0 (low), 1 (mid), 2 (high)


@dataclass(frozen=True)
class PriorBucket:
    """One bin in the prior table: context + observed distribution."""
    context: PriorContext
    n_train: int
    p_open: float
    p_hedge: float
    p_monitor: float


class StructuralPriors:
    """Empirical-Bayes prior holder over (regime, 12m_vol, 12m_ret) bins.

    Public API for the orchestrator:
        priors.fit(df_10y, regime_tags) -> self
        priors.prior_distribution(context: PriorContext) -> dict[Decision, float]
        priors.prior_for_row(row) -> dict[Decision, float]    # context derived from row
        priors.save(path) / load(path)
    """

    def __init__(self, *, horizon: int = 6, min_n_per_bucket: int = 30) -> None:
        self.horizon: int = int(horizon)
        self.min_n_per_bucket: int = int(min_n_per_bucket)
        self._table: dict[tuple[int, int, int], PriorBucket] = {}
        self._global_prior: dict[Decision, float] = {"OPEN": 1 / 3, "HEDGE": 1 / 3, "MONITOR": 1 / 3}
        self._vol_breaks: tuple[float, float] = (0.0, 0.0)   # (33rd, 67th percentile)
        self._ret_breaks: tuple[float, float] = (0.0, 0.0)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _attach_context(
        self,
        df: pd.DataFrame,
        regime_tags: pd.DataFrame,
    ) -> pd.DataFrame:
        """Compute the 3 context dimensions per row (date, regime, vol_tercile, ret_tercile)."""
        out = df.copy()
        out["date"] = pd.to_datetime(out["date"])
        regime = regime_tags.copy()
        regime["date"] = pd.to_datetime(regime["date"])
        out = out.merge(regime[["date", "regime_id"]], on="date", how="left")

        if "daily_return" not in out.columns:
            raise ValueError("StructuralPriors: dataset missing 'daily_return' column")
        if "volume" not in out.columns:
            raise ValueError("StructuralPriors: dataset missing 'volume' column")

        out = out.sort_values("date").reset_index(drop=True)
        # Rolling 12-month (≈252 trading days) windows
        out["vol_12m"] = out["daily_return"].rolling(window=252, min_periods=120).std()
        out["ret_12m"] = (1.0 + out["daily_return"]).rolling(window=252, min_periods=120).apply(
            lambda v: float(np.prod(v) - 1.0), raw=True
        )
        return out

    def _discretize(
        self,
        out: pd.DataFrame,
        *,
        fit_breaks: bool,
    ) -> pd.DataFrame:
        if fit_breaks:
            self._vol_breaks = (
                float(out["vol_12m"].quantile(1 / 3)),
                float(out["vol_12m"].quantile(2 / 3)),
            )
            self._ret_breaks = (
                float(out["ret_12m"].quantile(1 / 3)),
                float(out["ret_12m"].quantile(2 / 3)),
            )
        v1, v2 = self._vol_breaks
        r1, r2 = self._ret_breaks
        out["vol_tercile"] = pd.cut(
            out["vol_12m"], bins=[-np.inf, v1, v2, np.inf], labels=[0, 1, 2]
        ).astype("Int64")
        out["ret_tercile"] = pd.cut(
            out["ret_12m"], bins=[-np.inf, r1, r2, np.inf], labels=[0, 1, 2]
        ).astype("Int64")
        return out

    @staticmethod
    def _decision_from_forward_return(fwd: float) -> Decision:
        """Map a forward return to its 'oracle' decision: OPEN if up, HEDGE if down, MONITOR on (near-)zero."""
        # We use a tight zero band (±5e-4) so MONITOR is reserved for truly
        # near-zero days. The prior table will then mostly carry OPEN/HEDGE.
        if not np.isfinite(fwd):
            return "MONITOR"
        if fwd > 5e-4:
            return "OPEN"
        if fwd < -5e-4:
            return "HEDGE"
        return "MONITOR"

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def fit(self, df: pd.DataFrame, regime_tags: pd.DataFrame) -> "StructuralPriors":
        out = self._attach_context(df, regime_tags)
        out = self._discretize(out, fit_breaks=True)
        fwd_col = f"forward_return_{self.horizon}d"
        if fwd_col not in out.columns:
            raise ValueError(f"StructuralPriors: dataset missing {fwd_col!r}")
        out["oracle_decision"] = out[fwd_col].apply(self._decision_from_forward_return)

        # Global prior (used as fallback when a bin is sparse).
        n_total = int(out["oracle_decision"].notna().sum())
        if n_total > 0:
            for d in DECISIONS:
                self._global_prior[d] = float((out["oracle_decision"] == d).sum() / n_total)

        # Per-bucket conditional distribution.
        valid = out.dropna(subset=["regime_id", "vol_tercile", "ret_tercile"])
        for (reg, v, r), grp in valid.groupby(["regime_id", "vol_tercile", "ret_tercile"]):
            n = len(grp)
            if n < self.min_n_per_bucket:
                continue
            p = {d: float((grp["oracle_decision"] == d).mean()) for d in DECISIONS}
            self._table[(int(reg), int(v), int(r))] = PriorBucket(
                context=PriorContext(regime_id=int(reg), vol_12m_tercile=int(v), return_12m_tercile=int(r)),
                n_train=int(n),
                p_open=p["OPEN"], p_hedge=p["HEDGE"], p_monitor=p["MONITOR"],
            )
        return self

    def prior_distribution(self, context: PriorContext) -> dict[Decision, float]:
        key = (context.regime_id, context.vol_12m_tercile, context.return_12m_tercile)
        b = self._table.get(key)
        if b is None:
            return dict(self._global_prior)
        return {"OPEN": b.p_open, "HEDGE": b.p_hedge, "MONITOR": b.p_monitor}

    def attach_priors(
        self,
        df_predict: pd.DataFrame,
        regime_tags: pd.DataFrame,
    ) -> pd.DataFrame:
        """Add `prior_open`, `prior_hedge`, `prior_monitor` columns to ``df_predict``.

        Useful for backfill: take a 2026 prediction-month dataframe and attach the
        structural prior corresponding to each day's context bucket.
        """
        out = self._attach_context(df_predict, regime_tags)
        out = self._discretize(out, fit_breaks=False)
        priors_open: list[float] = []
        priors_hedge: list[float] = []
        priors_monitor: list[float] = []
        for _, row in out.iterrows():
            if pd.isna(row.get("regime_id")) or pd.isna(row.get("vol_tercile")) or pd.isna(row.get("ret_tercile")):
                p = self._global_prior
            else:
                p = self.prior_distribution(
                    PriorContext(
                        regime_id=int(row["regime_id"]),
                        vol_12m_tercile=int(row["vol_tercile"]),
                        return_12m_tercile=int(row["ret_tercile"]),
                    )
                )
            priors_open.append(p["OPEN"])
            priors_hedge.append(p["HEDGE"])
            priors_monitor.append(p["MONITOR"])
        out["prior_open"] = priors_open
        out["prior_hedge"] = priors_hedge
        out["prior_monitor"] = priors_monitor
        return out

    # ------------------------------------------------------------------
    # Persistence (JSON, human-auditable per CLAUDE.md immutability rule)
    # ------------------------------------------------------------------
    def save(self, path: Path) -> None:
        payload = {
            "horizon": self.horizon,
            "min_n_per_bucket": self.min_n_per_bucket,
            "vol_breaks": list(self._vol_breaks),
            "ret_breaks": list(self._ret_breaks),
            "global_prior": dict(self._global_prior),
            "buckets": [
                {
                    "regime_id": b.context.regime_id,
                    "vol_tercile": b.context.vol_12m_tercile,
                    "return_tercile": b.context.return_12m_tercile,
                    "n_train": b.n_train,
                    "p_open": b.p_open,
                    "p_hedge": b.p_hedge,
                    "p_monitor": b.p_monitor,
                }
                for b in self._table.values()
            ],
        }
        path.write_text(json.dumps(payload, indent=2))

    @classmethod
    def from_payload(cls, p: dict) -> "StructuralPriors":
        """Rebuild from the JSON payload dict (production path)."""
        sp = cls(horizon=int(p["horizon"]), min_n_per_bucket=int(p["min_n_per_bucket"]))
        sp._vol_breaks = tuple(p["vol_breaks"])  # type: ignore[assignment]
        sp._ret_breaks = tuple(p["ret_breaks"])  # type: ignore[assignment]
        sp._global_prior = dict(p["global_prior"])
        for b in p["buckets"]:
            ctx = PriorContext(
                regime_id=int(b["regime_id"]),
                vol_12m_tercile=int(b["vol_tercile"]),
                return_12m_tercile=int(b["return_tercile"]),
            )
            sp._table[(ctx.regime_id, ctx.vol_12m_tercile, ctx.return_12m_tercile)] = PriorBucket(
                context=ctx,
                n_train=int(b["n_train"]),
                p_open=float(b["p_open"]),
                p_hedge=float(b["p_hedge"]),
                p_monitor=float(b["p_monitor"]),
            )
        return sp

    @classmethod
    def load(cls, path: Path) -> "StructuralPriors":
        return cls.from_payload(json.loads(path.read_text()))

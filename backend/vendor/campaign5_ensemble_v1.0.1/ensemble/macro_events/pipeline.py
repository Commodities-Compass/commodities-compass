"""MacroEventLayer — Campaign 4 Phase 3 production build.

Per CAMPAIGN_4 §4.4, scope locked at Phase 0 question 1:
    Output schema: {direction ∈ {-1, 0, +1}, surprise ∈ [0, 1], half_life_days ∈ {1, 3, 7}}
    Used by the Phase 4-5 orchestrator for amplify-on-aligned-event / shield-on-uncertain.

Production data flow (NO live LLM calls in this session — the sentiment
extraction already happened upstream; we only AGGREGATE):

    pl_article_segment (LLM-extracted per zone × theme × day)
            │   confidence ≥ 0.70
            ▼
    daily confidence-weighted mean sentiment_score
            │
            ▼
    direction = sign(s) if |s| > τ_dir  else 0
    surprise  = z-score of article count vs rolling 30d baseline  →  [0, 1]
    half_life_days = piecewise per |surprise|:  <0.30 → 1d, 0.30-0.60 → 3d, >0.60 → 7d

Phase 0a (`MAC-001`) validated that bear-direction events at h=3d / h=22d carry
real conditional predictive value on the 2025-04-30 → 2026-05-12 window.
Phase 3 here turns that validated signal into a per-day score the orchestrator
can consume.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json

import numpy as np
import pandas as pd


CONF_THRESHOLD: float = 0.70
DIRECTION_THRESHOLD: float = 0.30  # |daily sentiment_score| above this -> direction != 0
SURPRISE_BASELINE_DAYS: int = 30
HALF_LIFE_BREAKS: tuple[float, float] = (0.30, 0.60)


@dataclass(frozen=True)
class MacroEventScore:
    date: pd.Timestamp
    direction: int          # -1, 0, +1
    surprise: float         # [0, 1]
    half_life_days: int     # 1, 3, 7
    n_segments: int         # number of high-confidence segments aggregated
    sentiment_wmean: float  # raw confidence-weighted mean sentiment_score
    confidence: float       # mean confidence across aggregated segments

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": pd.Timestamp(self.date),
            "direction": int(self.direction),
            "surprise": float(self.surprise),
            "half_life_days": int(self.half_life_days),
            "n_segments": int(self.n_segments),
            "sentiment_wmean": float(self.sentiment_wmean),
            "confidence": float(self.confidence),
        }


class MacroEventLayer:
    """Daily macro event scorer built from `pl_article_segment`.

    Public API:
        layer.fit(df_segments_history)        # establishes the 30d-baseline volume distribution
        layer.score_for_date(date)             # MacroEventScore for a single date
        layer.backfill(date_index)             # DataFrame of scores for a date range
    """

    def __init__(
        self,
        *,
        conf_threshold: float = CONF_THRESHOLD,
        direction_threshold: float = DIRECTION_THRESHOLD,
        baseline_days: int = SURPRISE_BASELINE_DAYS,
    ) -> None:
        self.conf_threshold = float(conf_threshold)
        self.direction_threshold = float(direction_threshold)
        self.baseline_days = int(baseline_days)
        self._daily: pd.DataFrame | None = None   # date-indexed aggregated table

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _aggregate_daily(self, df_segments: pd.DataFrame) -> pd.DataFrame:
        """Confidence-weighted daily aggregation of pl_article_segment rows.

        One row per `article_date` with:
            sentiment_wmean = Σ (conf_i × score_i) / Σ conf_i
            n_segments      = count of segments
            mean_confidence = Σ conf_i / n_segments
        """
        df = df_segments.copy()
        # Filter to high-confidence segments
        df = df[df["confidence"] >= self.conf_threshold]
        if df.empty:
            return pd.DataFrame(columns=["date", "sentiment_wmean", "n_segments", "mean_confidence"])
        df["article_date"] = pd.to_datetime(df["article_date"])
        df["w"] = df["confidence"].astype(float)
        df["ws"] = df["w"] * df["sentiment_score"].astype(float)

        grp = df.groupby("article_date", as_index=False).agg(
            sum_ws=("ws", "sum"),
            sum_w=("w", "sum"),
            n_segments=("sentiment_score", "size"),
        )
        grp["sentiment_wmean"] = grp["sum_ws"] / grp["sum_w"]
        grp["mean_confidence"] = grp["sum_w"] / grp["n_segments"]
        grp = grp.rename(columns={"article_date": "date"})
        return grp[["date", "sentiment_wmean", "n_segments", "mean_confidence"]].sort_values("date").reset_index(drop=True)

    def _half_life_for(self, surprise: float) -> int:
        """Piecewise half-life from |surprise| per the locked CAMPAIGN_4 §4.4.a output spec."""
        s = float(abs(surprise))
        if s < HALF_LIFE_BREAKS[0]:
            return 1
        if s < HALF_LIFE_BREAKS[1]:
            return 3
        return 7

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def fit(self, df_segments_history: pd.DataFrame) -> "MacroEventLayer":
        """Aggregate the history; cache the daily table for later scoring."""
        self._daily = self._aggregate_daily(df_segments_history)
        # Rolling baseline volume (article count) for surprise calculation
        if not self._daily.empty:
            self._daily["rolling_n_mean"] = (
                self._daily["n_segments"]
                .rolling(window=self.baseline_days, min_periods=5)
                .mean()
            )
            self._daily["rolling_n_std"] = (
                self._daily["n_segments"]
                .rolling(window=self.baseline_days, min_periods=5)
                .std()
                .fillna(1.0)
            )
            # surprise = sigmoid-ish mapping of z-score of article count into [0, 1]
            z = (
                (self._daily["n_segments"] - self._daily["rolling_n_mean"])
                / self._daily["rolling_n_std"].replace(0.0, 1.0)
            ).fillna(0.0)
            self._daily["surprise_raw_z"] = z
            self._daily["surprise"] = (1.0 / (1.0 + np.exp(-z))).astype(float)  # logistic z → [0,1]
        return self

    def score_for_date(self, date: pd.Timestamp) -> MacroEventScore:
        if self._daily is None or self._daily.empty:
            return MacroEventScore(
                date=pd.Timestamp(date),
                direction=0, surprise=0.0, half_life_days=1,
                n_segments=0, sentiment_wmean=0.0, confidence=0.0,
            )
        d = pd.Timestamp(date)
        row = self._daily[self._daily["date"] == d]
        if row.empty:
            return MacroEventScore(
                date=d, direction=0, surprise=0.0, half_life_days=1,
                n_segments=0, sentiment_wmean=0.0, confidence=0.0,
            )
        r = row.iloc[0]
        s = float(r["sentiment_wmean"])
        direction = 0
        if s >= self.direction_threshold:
            direction = +1
        elif s <= -self.direction_threshold:
            direction = -1
        surprise = float(r["surprise"]) if pd.notna(r["surprise"]) else 0.0
        return MacroEventScore(
            date=d,
            direction=int(direction),
            surprise=surprise,
            half_life_days=self._half_life_for(surprise),
            n_segments=int(r["n_segments"]),
            sentiment_wmean=s,
            confidence=float(r["mean_confidence"]),
        )

    def backfill(self, dates: pd.Series | list[pd.Timestamp]) -> pd.DataFrame:
        """Backfill scores for an iterable of dates. Dates with no segments → direction=0."""
        rows = [self.score_for_date(d).to_dict() for d in pd.to_datetime(pd.Series(list(dates)))]
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Persistence — JSON snapshot of the daily aggregated table.
    # ------------------------------------------------------------------
    def save_csv(self, path: Path) -> None:
        if self._daily is None:
            raise RuntimeError("nothing to save: MacroEventLayer not fit")
        self._daily.to_csv(path, index=False)

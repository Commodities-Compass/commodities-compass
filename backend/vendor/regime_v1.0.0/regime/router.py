"""Layer 1 — the causal regime router.

Classifies today's market state from trailing features only (no look-ahead) and
resolves it to exactly one specialist via a fixed priority (most-specific first).
Every trading day maps to one and only one specialist.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Routing:
    regime: str                 # bull | bear | transition
    specialist: str             # the specialist to use today
    states: dict[str, Any]


class RegimeRouter:
    """Rule-based, fully causal. Config is loaded from the frozen router artifact."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.k = float(cfg["trend_band_k"])
        self.tw = int(cfg["trend_window"])
        self.rsi_os = float(cfg["rsi_oversold"])
        self.rsi_ob = float(cfg["rsi_overbought"])
        self.atr_high = float(cfg["atr_high_value"])
        self.priority: list[str] = list(cfg["priority"])

    def _regime(self, trend20: float, trend60: float, vol20: float) -> str:
        band = self.k * vol20 * np.sqrt(self.tw / 252.0)
        if trend20 < -band:
            return "bear"
        if trend20 > band and trend60 > 0:
            return "bull"
        return "transition"

    def route(self, feat: pd.Series, available: set[str]) -> Routing:
        """feat: the 12-feature Series. `available` = specialist names present in the pack."""
        regime = self._regime(float(feat["trend20"]), float(feat["trend60"]), float(feat["vol20"]))
        rsi, atr = float(feat["rsi_14d"]), float(feat["atr_14d"])
        candidates = {
            "oversold": rsi < self.rsi_os,
            "overbought": rsi > self.rsi_ob,
            "highvol": atr > self.atr_high,
            "bull": regime == "bull",
            "bear": regime == "bear",
            "transition": regime == "transition",
        }
        specialist = "transition"
        for name in self.priority:
            if candidates.get(name) and name in available:
                specialist = name
                break
        states = {"regime": regime, "rsi_14d": round(rsi, 2), "atr_14d": round(atr, 2),
                  "trend20": round(float(feat["trend20"]), 4)}
        return Routing(regime=regime, specialist=specialist, states=states)

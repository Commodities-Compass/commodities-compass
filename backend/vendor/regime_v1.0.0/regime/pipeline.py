"""Top-level entry point: RegimePipeline.decide(request) -> RegimeDecision.

Two layers:
  1. RegimeRouter classifies today's regime from trailing features and picks a specialist.
  2. That specialist predicts P(next day up); >= 0.5 -> OPEN, else HEDGE.

v1.0.0 is binary (no MONITOR) except as a fail-safe when the routed specialist is
absent from the pack. The prod risk/abstention brake, if any, lives downstream and
is NOT baked into this pack.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd

from regime.artifact_io import FrozenDirLoader
from regime.config import OPEN, HEDGE, MONITOR
from regime.data_loader_protocol import DecideRequest, RegimeDecision
from regime.features import compute_feature_row
from regime.router import RegimeRouter


class RegimePipeline:
    def __init__(self, specialists: dict, router: RegimeRouter, feature_order: list[str]) -> None:
        self.specialists = specialists
        self.router = router
        self.feature_order = feature_order
        self._trend_w = int(router.cfg["trend_window"])
        self._confirm_w = int(router.cfg["trend_confirm_window"])
        self._vol_w = int(router.cfg["vol_window"])

    @classmethod
    def from_frozen(cls, frozen_dir: str | Path) -> "RegimePipeline":
        loader = FrozenDirLoader(frozen_dir)
        specialists = loader.load_specialists()
        router_cfg = loader.load_router()
        feature_order = list(loader.manifest["router_features"])
        return cls(specialists, RegimeRouter(router_cfg), feature_order)

    def decide(self, request: DecideRequest) -> RegimeDecision:
        feat = compute_feature_row(
            request.market_history, request.today,
            trend_window=self._trend_w, confirm_window=self._confirm_w, vol_window=self._vol_w,
        )
        routing = self.router.route(feat, available=set(self.specialists))
        model = self.specialists.get(routing.specialist)
        if model is None:  # fail-safe — never commit blind
            return RegimeDecision(request.today, MONITOR, routing.regime,
                                  routing.specialist, 0.5, routing.states)
        X = feat[self.feature_order].to_frame().T
        prob_up = float(model.predict_proba(X)[0, 1])
        decision = OPEN if prob_up >= 0.5 else HEDGE
        return RegimeDecision(request.today, decision, routing.regime,
                              routing.specialist, prob_up, routing.states)

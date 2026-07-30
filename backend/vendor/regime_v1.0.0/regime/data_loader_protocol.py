"""Request/response contracts prod implements to drive the regime pipeline.

Mirrors the ensemble deliverable's seam so Compass integrates it the same way:
prod assembles a ``DecideRequest`` from its own DB loaders and receives a
``RegimeDecision``. The regime algo needs only market history — no macro layer,
no prior decisions/votes (the router + specialists are memoryless per day).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import pandas as pd


@dataclass(frozen=True)
class DecideRequest:
    today: pd.Timestamp
    contract_id: str
    # Canonical market panel for `contract_id`, rows sorted by date, INCLUDING `today`.
    # Must carry `date`, `daily_return`, and the nine passthrough derived-indicator
    # columns (see config.DERIVED_PASSTHROUGH). Needs >= 60 trailing rows so the
    # router's trend/vol windows are well-defined.
    market_history: pd.DataFrame


@dataclass(frozen=True)
class RegimeDecision:
    date: pd.Timestamp
    decision: str            # OPEN | HEDGE | MONITOR
    regime: str              # bull | bear | transition
    specialist: str          # which specialist was routed to
    prob_up: float           # specialist P(next day up)
    states: dict[str, Any] = field(default_factory=dict)  # rsi/atr/trend diagnostics

    def to_dict(self) -> dict:
        return {
            "date": pd.Timestamp(self.date),
            "decision": str(self.decision),
            "regime": str(self.regime),
            "specialist": str(self.specialist),
            "prob_up": float(self.prob_up),
            **{f"state_{k}": v for k, v in self.states.items()},
        }

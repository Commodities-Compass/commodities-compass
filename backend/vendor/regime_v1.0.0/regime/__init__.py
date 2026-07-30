"""regime — two-layer regime-router + condition-specialist algorithm (v1.0.0).

Public API:
    from regime.pipeline import RegimePipeline
    from regime.data_loader_protocol import DecideRequest
    pipe = RegimePipeline.from_frozen("frozen")
    decision = pipe.decide(DecideRequest(today, contract_id, market_history))
"""
from __future__ import annotations

from regime.config import ALGORITHM_NAME, ALGORITHM_VERSION, HORIZON

__all__ = ["ALGORITHM_NAME", "ALGORITHM_VERSION", "HORIZON"]

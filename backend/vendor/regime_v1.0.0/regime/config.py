"""Static config for the `regime` algorithm v1.0.0."""
from __future__ import annotations

SEED: int = 42
ALGORITHM_NAME: str = "regime"
ALGORITHM_VERSION: str = "1.0.0"
HORIZON: str = "J+1"  # binary next-trading-day direction

# The 12 features every specialist consumes. The first nine are passthrough columns
# from `pl_derived_indicators` (roll-neutralized). The last three are computed from
# the daily-return series by the router (trailing trend + realized vol).
DERIVED_PASSTHROUGH: tuple[str, ...] = (
    "macd", "macd_signal", "rsi_14d", "atr_14d", "stochastic_d_14",
    "close_pivot_ratio", "volume_oi_ratio", "daily_return", "bollinger_width",
)
ROUTER_DERIVED: tuple[str, ...] = ("trend20", "trend60", "vol20")
FEATURES: tuple[str, ...] = DERIVED_PASSTHROUGH + ROUTER_DERIVED

# Decision vocabulary (matches the prod ensemble contract).
OPEN, HEDGE, MONITOR = "OPEN", "HEDGE", "MONITOR"

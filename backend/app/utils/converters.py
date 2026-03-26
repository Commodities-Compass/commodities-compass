"""Shared type conversion utilities for DB read/write paths.

All converters handle None and NaN gracefully — no caller should need
to pre-check. These are the single source of truth; do not define
local _to_* helpers in individual modules.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any


def to_decimal(value: Any, precision: int = 6) -> Decimal | None:
    """Convert to Decimal, returning None for None/NaN/unconvertible."""
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        return Decimal(str(round(float(value), precision)))
    except (ValueError, TypeError, OverflowError):
        return None


def to_float(value: Any, default: float = 0.0) -> float:
    """Convert to float, returning default for None/NaN/unconvertible."""
    if value is None:
        return default
    try:
        result = float(value)
        return default if math.isnan(result) or math.isinf(result) else result
    except (ValueError, TypeError):
        return default


def to_int(value: Any) -> int | None:
    """Convert to int, returning None for None/unconvertible."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def to_str(value: Any) -> str | None:
    """Convert to string, returning None for None/NaN."""
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return str(value)

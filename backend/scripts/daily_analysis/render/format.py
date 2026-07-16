"""Shared number formatting for the conclusion renderers.

Matches the historical prompt formatting so rendered numbers are identical
across locales: ``:g`` (6 significant figures) for prices / indicators,
thousand-separated integers for tonnages. Grounded against real production
conclusions (e.g. rsi 60.952103 -> "60.9521", macd 113.656854 -> "113.657",
stock 212482 -> "212,482").
"""

from __future__ import annotations

from typing import Optional


def fmt(value: Optional[float]) -> str:
    """Price / indicator format (``:g``, 6 significant figures). None -> ''."""
    if value is None:
        return ""
    return f"{value:g}"


def fmt_tonnes(value: Optional[float]) -> str:
    """Tonnage with thousand separators (e.g. 212,482). None -> ''."""
    if value is None:
        return ""
    return f"{value:,.0f}"

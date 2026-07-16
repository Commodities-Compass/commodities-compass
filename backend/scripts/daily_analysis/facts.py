"""Deterministic facts for the daily narrative (US-1 facts/voice refactor).

The conclusion narrative embeds numbers (CLOSE, VOLUME, RSI, S1/R1, stocks...).
Historically the LLM re-typed those numbers into prose, which is (a) a
correctness risk — a model can drop a digit or flip a sign — and (b) a blocker
for i18n, because the French phrasing was parsed by the frontend.

This module extracts every number the narrative needs into a typed,
language-agnostic ``FactsPayload`` built straight from the DB rows. The
per-locale renderer (``render/``) turns it into prose; the LLM never re-types a
number, and the accuracy gate asserts the LLM voice never introduces a number
that isn't grounded here.

See docs/user-stories/P1-i18n-content-facts-voice-refactor.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Mapping, Optional


def _num(value: object) -> Optional[float]:
    """Coerce a DB value (Decimal/float/int/str/None) to float or None.

    None stays None — a real zero and 'not computed' must remain
    distinguishable (pipeline-continuity rule). Thousand separators in string
    inputs are tolerated.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class MetricPair:
    """A metric's today (and optional prior) value.

    Direction is *derived*, never stored as a language string — the renderer
    maps the neutral code to per-locale phrasing.
    """

    today: Optional[float]
    yesterday: Optional[float] = None

    @property
    def direction(self) -> Optional[str]:
        """'up' | 'down' | 'flat' | None (None when either side is missing)."""
        if self.today is None or self.yesterday is None:
            return None
        if self.today > self.yesterday:
            return "up"
        if self.today < self.yesterday:
            return "down"
        return "flat"


@dataclass(frozen=True)
class FactsPayload:
    """Every deterministic number the daily conclusion needs, language-agnostic.

    Built once from the DB, consumed by every locale's renderer plus the
    accuracy gate. No French, no English — only numbers and neutral codes.
    """

    session_date: date
    # 8 fact-bullet metrics
    close: MetricPair
    volume: MetricPair
    oi: MetricPair
    rsi: MetricPair
    macd: MetricPair
    iv: MetricPair
    stock_us: MetricPair
    stock_eu: MetricPair
    # à-surveiller levels (today's derived indicators)
    s1: Optional[float]
    s2: Optional[float]
    r1: Optional[float]
    r2: Optional[float]

    def all_numbers(self) -> list[float]:
        """Every number grounded in this payload.

        The accuracy gate uses this to assert the LLM voice never introduces a
        number that isn't one of these.
        """
        vals: list[float] = []
        for m in (
            self.close,
            self.volume,
            self.oi,
            self.rsi,
            self.macd,
            self.iv,
            self.stock_us,
            self.stock_eu,
        ):
            if m.today is not None:
                vals.append(m.today)
            if m.yesterday is not None:
                vals.append(m.yesterday)
        for lvl in (self.s1, self.s2, self.r1, self.r2):
            if lvl is not None:
                vals.append(lvl)
        return vals


def build_facts_payload(
    today_row: Mapping[str, object],
    yesterday_row: Mapping[str, object],
    *,
    session_date: date,
) -> FactsPayload:
    """Build a :class:`FactsPayload` from the raw today/yesterday DB rows.

    ``today_row`` / ``yesterday_row`` are the dicts produced by the technicals
    read (``pl_contract_data_daily`` JOIN ``pl_derived_indicators`` plus the
    injected weekly ``stock_us`` / ``stock_eu_tonnes`` columns). Missing values
    become ``None``.
    """

    def pair(col: str) -> MetricPair:
        return MetricPair(
            today=_num(today_row.get(col)),
            yesterday=_num(yesterday_row.get(col)),
        )

    return FactsPayload(
        session_date=session_date,
        close=pair("close"),
        volume=pair("volume"),
        oi=pair("oi"),
        rsi=pair("rsi_14d"),
        macd=pair("macd"),
        iv=pair("implied_volatility"),
        stock_us=pair("stock_us"),
        stock_eu=pair("stock_eu_tonnes"),
        s1=_num(today_row.get("s1")),
        s2=_num(today_row.get("s2")),
        r1=_num(today_row.get("r1")),
        r2=_num(today_row.get("r2")),
    )

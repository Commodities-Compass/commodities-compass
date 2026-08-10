"""Parse a Compass daily brief (.txt) into a typed :class:`Brief`.

The briefs are prose destined for a daily podcast, wrapped in box-drawing
separators that often arrive mojibake'd. The parser is therefore label-driven
and encoding-tolerant: it anchors on stable tokens ("Position", "Confidence",
"SUPPLY", "Impact:", "Session close") rather than on layout.
"""

from __future__ import annotations

import re

from .schema import Brief, Decision, PressRead, WeatherRead

_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ],
        start=1,
    )
}


def _to_iso(date_str: str) -> str:
    """'31 July 2026' -> '2026-07-31'. Returns '' if unparseable."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", date_str)
    if not m:
        return ""
    day, month_name, year = m.group(1), m.group(2).lower(), m.group(3)
    month = _MONTHS.get(month_name)
    if not month:
        return ""
    return f"{year}-{month:02d}-{int(day):02d}"


def _find(pattern: str, text: str, *, flags: int = 0) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def _num(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.replace(",", "").replace(" ", "").replace("%", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _section(text: str, start_label: str, stop_labels: tuple[str, ...]) -> str:
    """Return the body between ``start_label`` and the next stop label."""
    start = re.search(rf"{start_label}\s*:?\s*\n", text)
    if not start:
        return ""
    body = text[start.end():]
    stops = [body.find(f"\n{lbl}") for lbl in stop_labels]
    stops = [s for s in stops if s != -1]
    end = min(stops) if stops else len(body)
    return body[:end].strip()


def _parse_press(text: str) -> PressRead:
    supply = _section(text, "SUPPLY", ("FUNDAMENTALS", "MARKET", "Impact summary"))
    fundamentals = _section(text, "FUNDAMENTALS", ("MARKET", "Impact summary"))
    market = _section(text, "MARKET", ("MARKET SENTIMENT", "Impact summary"))
    sentiment = _section(text, "MARKET SENTIMENT", ("Impact summary", "IV "))
    impact = _find(r"Impact summary:\s*(.+?)(?:\n\s*\n|\nIV|\Z)", text, flags=re.S)
    return PressRead(
        supply=supply,
        fundamentals=fundamentals,
        market=market,
        sentiment=sentiment,
        impact_summary=(impact or "").strip(),
    )


def _parse_weather(text: str) -> WeatherRead:
    impact = _num(_find(r"Impact:\s*(\d+(?:\.\d+)?)\s*/\s*10", text))
    summary = _find(r"Impact:\s*(\d+/10;[^\n]*)", text) or ""
    return WeatherRead(impact_10=impact, summary=summary.strip())


_DECISION_TOKENS = {
    "OPEN": Decision.OPEN,
    "HEDGE": Decision.HEDGE,
    "MONITOR": Decision.MONITOR,
}


def parse_brief(text: str) -> Brief:
    """Parse the full brief text into a :class:`Brief`."""
    session_date = _to_iso(_find(r"Date:\s*([^\n]+)", text) or "")

    position_raw = _find(r"Position\s*:\s*([A-Z]+)", text) or "MONITOR"
    base_decision = _DECISION_TOKENS.get(position_raw.upper(), Decision.MONITOR)

    base_conf = _num(_find(r"Confidence\s*:\s*([0-9.]+)\s*/\s*5", text)) or 0.0
    direction = _find(r"Direction\s*:\s*([A-Za-zÀ-ÿ]+)", text) or ""
    ytd = _num(_find(r"YTD performance\s*:\s*([+\-]?[0-9.]+)\s*%", text))

    last_close_date = _find(r"Session close\s*:\s*(\d{4}-\d{2}-\d{2})", text) or ""
    close = _num(_find(r"CLOSE\s*=\s*([\d,]+(?:\.\d+)?)", text))
    volume = _num(_find(r"VOLUME\s*=\s*([\d,]+)", text))
    rsi = _num(_find(r"RSI at\s*([\d.]+)", text))

    return Brief(
        session_date=session_date,
        last_close_date=last_close_date,
        base_decision=base_decision,
        base_confidence=base_conf,
        base_direction_label=direction,
        ytd=ytd,
        press=_parse_press(text),
        weather=_parse_weather(text),
        close=close,
        volume=volume,
        rsi=rsi,
        raw_text=text,
    )


def parse_brief_file(path: str) -> Brief:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return parse_brief(fh.read())

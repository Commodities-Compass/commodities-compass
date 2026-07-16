"""English renderer: FactsPayload -> deterministic conclusion body.

Mirror of ``render/fr.py`` for the Ghana / West-African trader edition (US-3).
Owns the 8 fact-bullets and the 3 "to watch" alerts; the headline is the LLM's
voice, assembled in by ``render_conclusion``. Every number is formatted here
from the payload (shared ``format`` module) and NEVER re-typed by the model, so
the figures are byte-identical to the French edition — only the prose differs.

Market / technical terms are kept verbatim (CLOSE, VOLUME, RSI, MACD, SUPPORT,
RESISTANCE, tonnes); the RSI alert threshold rule matches fr.py (round(rsi) - 3
for a >=50 reading).
"""

from __future__ import annotations

from scripts.daily_analysis.facts import FactsPayload, MetricPair
from scripts.daily_analysis.render.format import fmt, fmt_tonnes

LANG = "en"

_BULLET = "        • "  # 8 spaces + bullet + space — same indent as fr.py
_WATCH_HEADER = "> TO WATCH TODAY:"


def _trend(pair: MetricPair, up: str, down: str, flat: str) -> str:
    return {"up": up, "down": down, "flat": flat}.get(pair.direction or "", flat)


def _vs_prev(pair: MetricPair, *, tonnes: bool = False) -> str:
    if pair.yesterday is None:
        return ""
    val = fmt_tonnes(pair.yesterday) if tonnes else fmt(pair.yesterday)
    unit = " tonnes" if tonnes else ""
    return f", vs {val}{unit} the prior session"


def _rsi_zone(rsi: float) -> str:
    if rsi < 30:
        return "oversold territory"
    if rsi > 70:
        return "overbought territory"
    return "neutral zone"


def render_fact_bullets(facts: FactsPayload) -> str:
    """The 8 deterministic fact-bullets (one per available metric)."""
    lines: list[str] = []

    if facts.close.today is not None:
        t = _trend(facts.close, "bullish trend", "bearish trend", "neutral trend")
        lines.append(
            f"{_BULLET}CLOSE settles at {fmt(facts.close.today)}"
            f"{_vs_prev(facts.close)} — {t}."
        )

    if facts.volume.today is not None:
        t = _trend(
            facts.volume, "activity picking up", "activity easing", "activity steady"
        )
        lines.append(
            f"{_BULLET}VOLUME comes in at {fmt(facts.volume.today)}"
            f"{_vs_prev(facts.volume)} — {t}."
        )

    if facts.oi.today is not None:
        t = _trend(
            facts.oi, "positions building", "positions unwinding", "positions steady"
        )
        lines.append(
            f"{_BULLET}OPEN INTEREST at {fmt(facts.oi.today)}"
            f"{_vs_prev(facts.oi)} — {t}."
        )

    if facts.rsi.today is not None:
        lines.append(
            f"{_BULLET}RSI at {fmt(facts.rsi.today)} — {_rsi_zone(facts.rsi.today)}."
        )

    if facts.macd.today is not None:
        sign = "negative" if facts.macd.today < 0 else "positive"
        mom = _trend(
            facts.macd, "momentum building", "momentum fading", "momentum steady"
        )
        lines.append(f"{_BULLET}MACD at {fmt(facts.macd.today)} ({sign}) — {mom}.")

    if facts.iv.today is not None:
        t = _trend(
            facts.iv,
            "vol expectations rising",
            "vol expectations easing",
            "vol expectations steady",
        )
        lines.append(
            f"{_BULLET}Implied volatility at {fmt(facts.iv.today)}"
            f"{_vs_prev(facts.iv)} — {t}."
        )

    if facts.stock_us.today is not None:
        t = _trend(facts.stock_us, "stocks rising", "stocks falling", "stocks steady")
        lines.append(
            f"{_BULLET}US stocks at {fmt_tonnes(facts.stock_us.today)} tonnes"
            f"{_vs_prev(facts.stock_us, tonnes=True)} — {t}."
        )

    if facts.stock_eu.today is not None:
        t = _trend(facts.stock_eu, "stocks rising", "stocks falling", "stocks steady")
        lines.append(
            f"{_BULLET}EU stocks at {fmt_tonnes(facts.stock_eu.today)} tonnes"
            f"{_vs_prev(facts.stock_eu, tonnes=True)} — {t}."
        )

    return "\n".join(lines)


def render_watch_section(facts: FactsPayload) -> str:
    """The 3 pinned watch alerts: CLOSE vs S1->S2, CLOSE vs R1->R2, RSI band."""
    alerts: list[str] = []

    if facts.s1 is not None:
        obj = f" — target SUPPORT 2 at {fmt(facts.s2)}" if facts.s2 is not None else ""
        alerts.append(
            f"{_BULLET}Bearish if CLOSE breaks below SUPPORT 1 ({fmt(facts.s1)}){obj}."
        )

    if facts.r1 is not None:
        obj = (
            f" — target RESISTANCE 2 at {fmt(facts.r2)}" if facts.r2 is not None else ""
        )
        alerts.append(
            f"{_BULLET}Bullish if CLOSE clears RESISTANCE 1 ({fmt(facts.r1)}){obj}."
        )

    if facts.rsi.today is not None:
        rsi = facts.rsi.today
        if rsi >= 50:
            thr = round(rsi) - 3
            alerts.append(
                f"{_BULLET}Bearish if RSI slips below {thr} "
                f"(currently {fmt(rsi)}) — selling pressure builds."
            )
        else:
            thr = round(rsi) + 3
            alerts.append(
                f"{_BULLET}Bullish if RSI climbs above {thr} "
                f"(currently {fmt(rsi)}) — buying pressure builds."
            )

    if not alerts:
        return ""
    return "\n".join([_WATCH_HEADER, *alerts])


def render_conclusion(headline: str, facts: FactsPayload) -> str:
    """Assemble the full conclusion: LLM headline + deterministic body."""
    head = headline.strip()
    if not head.startswith(">"):
        head = f"> {head}"
    parts = [head]
    body = render_fact_bullets(facts)
    if body:
        parts.append(body)
    watch = render_watch_section(facts)
    if watch:
        parts.append(watch)
    return "\n".join(parts)

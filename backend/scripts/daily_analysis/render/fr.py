"""French renderer: FactsPayload -> deterministic conclusion body.

Owns the 8 fact-bullets and the 3 "à surveiller" alerts. The headline
(qualitative synthesis) is the LLM's voice, assembled in by ``render_conclusion``.
Every number is formatted here from the payload and NEVER re-typed by the model,
which is what makes the numbers correct-by-construction and the output i18n-safe.

Grounded against real production conclusions: the RSI alert threshold rule
(round(rsi) - 3 for a >=50 reading) reproduces the historical "sous 58"
for an RSI of 60.9521.
"""

from __future__ import annotations

from scripts.daily_analysis.facts import FactsPayload, MetricPair
from scripts.daily_analysis.render.format import fmt, fmt_tonnes

LANG = "fr"

_BULLET = "        • "  # 8 spaces + bullet + space — the historical indent
_WATCH_HEADER = "> A SURVEILLER AUJOURD'HUI:"


def _trend(pair: MetricPair, up: str, down: str, flat: str) -> str:
    return {"up": up, "down": down, "flat": flat}.get(pair.direction or "", flat)


def _vs_prev(pair: MetricPair, *, tonnes: bool = False) -> str:
    if pair.yesterday is None:
        return ""
    val = fmt_tonnes(pair.yesterday) if tonnes else fmt(pair.yesterday)
    unit = " tonnes" if tonnes else ""
    return f", contre {val}{unit} la veille"


def _rsi_zone(rsi: float) -> str:
    if rsi < 30:
        return "zone de survente"
    if rsi > 70:
        return "zone de surachat"
    return "zone neutre"


def render_fact_bullets(facts: FactsPayload) -> str:
    """The 8 deterministic fact-bullets (one per available metric)."""
    lines: list[str] = []

    if facts.close.today is not None:
        t = _trend(
            facts.close, "tendance haussière", "tendance baissière", "tendance neutre"
        )
        lines.append(
            f"{_BULLET}Le CLOSE s'établit à {fmt(facts.close.today)}"
            f"{_vs_prev(facts.close)} — {t}."
        )

    if facts.volume.today is not None:
        t = _trend(
            facts.volume, "activité en hausse", "activité en repli", "activité stable"
        )
        lines.append(
            f"{_BULLET}Le VOLUME ressort à {fmt(facts.volume.today)}"
            f"{_vs_prev(facts.volume)} — {t}."
        )

    if facts.oi.today is not None:
        t = _trend(
            facts.oi,
            "accumulation de positions",
            "réduction des positions",
            "positions stables",
        )
        lines.append(
            f"{_BULLET}L'OPEN INTEREST s'inscrit à {fmt(facts.oi.today)}"
            f"{_vs_prev(facts.oi)} — {t}."
        )

    if facts.rsi.today is not None:
        lines.append(
            f"{_BULLET}Le RSI est à {fmt(facts.rsi.today)} — {_rsi_zone(facts.rsi.today)}."
        )

    if facts.macd.today is not None:
        sign = "négatif" if facts.macd.today < 0 else "positif"
        mom = _trend(
            facts.macd, "momentum en hausse", "momentum en repli", "momentum stable"
        )
        lines.append(
            f"{_BULLET}Le MACD est à {fmt(facts.macd.today)} ({sign}) — {mom}."
        )

    if facts.iv.today is not None:
        t = _trend(
            facts.iv,
            "anticipations de volatilité en hausse",
            "anticipations de volatilité en baisse",
            "anticipations stables",
        )
        lines.append(
            f"{_BULLET}La volatilité implicite est à {fmt(facts.iv.today)}"
            f"{_vs_prev(facts.iv)} — {t}."
        )

    if facts.stock_us.today is not None:
        t = _trend(
            facts.stock_us, "stocks en hausse", "stocks en baisse", "stocks stables"
        )
        lines.append(
            f"{_BULLET}Le STOCK US est à {fmt_tonnes(facts.stock_us.today)} tonnes"
            f"{_vs_prev(facts.stock_us, tonnes=True)} — {t}."
        )

    if facts.stock_eu.today is not None:
        t = _trend(
            facts.stock_eu, "stocks en hausse", "stocks en baisse", "stocks stables"
        )
        lines.append(
            f"{_BULLET}Le STOCK EU est à {fmt_tonnes(facts.stock_eu.today)} tonnes"
            f"{_vs_prev(facts.stock_eu, tonnes=True)} — {t}."
        )

    return "\n".join(lines)


def render_watch_section(facts: FactsPayload) -> str:
    """The 3 pinned à-surveiller alerts: CLOSE vs S1->S2, CLOSE vs R1->R2, RSI band."""
    alerts: list[str] = []

    if facts.s1 is not None:
        obj = f" — objectif SUPPORT 2 à {fmt(facts.s2)}" if facts.s2 is not None else ""
        alerts.append(
            f"{_BULLET}Baissier si le CLOSE passe sous le SUPPORT 1 ({fmt(facts.s1)}){obj}."
        )

    if facts.r1 is not None:
        obj = (
            f" — objectif RESISTANCE 2 à {fmt(facts.r2)}"
            if facts.r2 is not None
            else ""
        )
        alerts.append(
            f"{_BULLET}Haussier si le CLOSE dépasse la RESISTANCE 1 ({fmt(facts.r1)}){obj}."
        )

    if facts.rsi.today is not None:
        rsi = facts.rsi.today
        if rsi >= 50:
            thr = round(rsi) - 3
            alerts.append(
                f"{_BULLET}Baissier si le RSI repasse sous {thr} "
                f"(actuellement {fmt(rsi)}) — pression vendeuse accrue."
            )
        else:
            thr = round(rsi) + 3
            alerts.append(
                f"{_BULLET}Haussier si le RSI repasse au-dessus de {thr} "
                f"(actuellement {fmt(rsi)}) — pression acheteuse accrue."
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

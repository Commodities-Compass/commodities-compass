"""Render the .txt brief — deterministic layout, LLM prose only where intended.

Split of responsibility (the facts/voice separation established by US-1):

    the narrator writes PROSE and never a figure
    this module writes FIGURES and never prose

So a number can only ever be wrong here, where it is a direct read of the DB,
and never because a model retyped it.

The output is plain text read aloud by NotebookLM, so it carries no markup and
no mention of any machinery.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from scripts.regime_brief.db_reader import BriefData
from scripts.regime_brief.narrator import Narrative

_LABELS = {
    "fr": {
        "title": "COMPASS BRIEF",
        "session": "Séance",
        "contract": "Contrat",
        "signal": "SIGNAL DU JOUR",
        "conviction": "Conviction",
        "market": "MARCHÉ",
        "close": "Clôture",
        "change": "Variation",
        "volume": "Volume",
        "oi": "Positions ouvertes",
        "rsi": "RSI 14j",
        "levels": "Niveaux à surveiller",
        "support": "support",
        "resistance": "résistance",
        "reading": "LECTURE DU JOUR",
        "macro": "CONTEXTE MACRO ET FONDAMENTAUX",
        "watch": "CE QUI POURRAIT FAIRE MENTIR CETTE LECTURE",
        "press": "REVUE DE PRESSE",
        "weather": "MÉTÉO DES ORIGINES",
        "unavailable": "non disponible",
    },
    "en": {
        "title": "COMPASS BRIEF",
        "session": "Session",
        "contract": "Contract",
        "signal": "TODAY'S SIGNAL",
        "conviction": "Conviction",
        "market": "MARKET",
        "close": "Close",
        "change": "Change",
        "volume": "Volume",
        "oi": "Open interest",
        "rsi": "RSI 14d",
        "levels": "Levels to watch",
        "support": "support",
        "resistance": "resistance",
        "reading": "TODAY'S READ",
        "macro": "MACRO AND FUNDAMENTAL BACKDROP",
        "watch": "WHAT WOULD PROVE THIS READ WRONG",
        "press": "PRESS REVIEW",
        "weather": "ORIGIN WEATHER",
        "unavailable": "unavailable",
    },
}


def _fmt_number(value: Optional[Decimal | int | float], digits: int = 0) -> str:
    if value is None:
        return "—"
    number = float(value)
    if digits == 0:
        return f"{number:,.0f}".replace(",", " ")
    return f"{number:,.{digits}f}".replace(",", " ")


def _fmt_change(close: Optional[Decimal], prev: Optional[Decimal]) -> str:
    if close is None or prev is None or float(prev) == 0:
        return "—"
    delta = float(close) - float(prev)
    pct = delta / float(prev) * 100
    return f"{delta:+,.0f} ({pct:+.2f} %)".replace(",", " ")


def _section(title: str, body: str) -> str:
    return f"{title}\n{'-' * len(title)}\n{body.strip()}\n"


def render_brief(data: BriefData, narrative: Narrative) -> str:
    """Assemble the full brief text for one language."""
    labels = _LABELS.get(data.language, _LABELS["fr"])
    tech = data.technicals

    header = (
        f"{labels['title']} — {data.session_date.isoformat()}\n"
        f"{labels['session']} : {data.session_date.isoformat()}   "
        f"{labels['contract']} : {data.contract_code}\n"
    )

    signal_body = (
        f"{data.judge.final_decision}\n"
        f"{labels['conviction']} : {data.judge.confidence}/5"
    )

    levels = []
    if tech.s1 is not None:
        levels.append(f"{labels['support']} {_fmt_number(tech.s1)}")
    if tech.r1 is not None:
        levels.append(f"{labels['resistance']} {_fmt_number(tech.r1)}")

    market_lines = [
        f"{labels['close']} : {_fmt_number(tech.close)}",
        f"{labels['change']} : {_fmt_change(tech.close, tech.close_prev)}",
        f"{labels['volume']} : {_fmt_number(tech.volume)}",
        f"{labels['oi']} : {_fmt_number(tech.oi)}",
        f"{labels['rsi']} : {_fmt_number(tech.rsi_14d, 1)}",
    ]
    if levels:
        market_lines.append(f"{labels['levels']} : {' / '.join(levels)}")

    parts = [
        header,
        _section(labels["signal"], signal_body),
        _section(labels["market"], "\n".join(market_lines)),
        _section(labels["reading"], narrative.conclusion),
        _section(labels["macro"], narrative.eco),
        _section(labels["watch"], narrative.confidence_rationale),
        _section(labels["press"], data.press_summary),
        _section(labels["weather"], data.weather_body),
    ]
    return "\n".join(parts).strip() + "\n"

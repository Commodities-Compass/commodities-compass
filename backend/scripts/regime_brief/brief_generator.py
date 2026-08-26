"""Render the full daily brief for the regime+judge track.

A FAITHFUL MIRROR of the ensemble brief: same six sections, same order, same
labels, same guards. The brief is the whole of Compass — signal, guaranteed
farmgate price, eco & press, weather, technicals, operational recommendations —
and the NotebookLM podcast prompt maps onto those sections one by one. Ship a
thinner brief and the podcast breaks: it looks for the YTD at point 2, the
confidence pillars at 3, section II at 4, the stocks at 7, the three TO WATCH
alerts at 8.

Exactly ONE section changes: **II — EDITORIAL READ**. The ensemble version
described a panel of reads converging on a verdict; the regime+judge version
describes the detected market regime, the technical stance it implies, and how
the macro specialist arbitrated it. Everything else is untouched, because
everything else describes the market rather than the algorithm.

Split of responsibility, as in the ensemble track:
    the narrator writes PROSE and never a figure
    this module writes FIGURES and never prose
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from datetime import date as date_cls

from scripts._shared.farmgate_brief import format_farmgate_lines
from scripts.regime_brief.db_reader import BriefData
from scripts.regime_brief.narrator import Narrative

SEP_THICK = "─" * 70
SEP_THIN = "─" * 70

MONTHS_FR = (
    "janvier février mars avril mai juin juillet août septembre octobre "
    "novembre décembre"
).split()
MONTHS_EN = (
    "January February March April May June July August September October "
    "November December"
).split()


@dataclass(frozen=True)
class _BriefLabels:
    months: Sequence[str]
    date_prefix: str
    horizon: str
    intro: str
    section_editorial: str
    section_eco: str
    section_technicals: str
    section_reco: str
    field_position: str
    field_confidence: str
    field_direction: str
    field_ytd: str
    regime_prefix: str
    stance_confirm: str
    stance_contradict: str
    stance_neutral: str
    press_review_prefix: str
    press_impact_prefix: str
    press_sentiment_prefix: str
    weather_impact_prefix: str
    weather_none: str
    reco_none: str


# The editorial vocabulary is deliberately business-facing. No mechanism is
# named: the podcast prompt forbids "orchestrator", "detector", "model", any
# panel size — and this text is read aloud verbatim.
_LABELS_FR = _BriefLabels(
    months=MONTHS_FR,
    date_prefix="Date :",
    horizon="Horizon de décision : prochaine séance",
    intro=(
        "La lecture Compass du jour sur le cacao Londres premier échéance, "
        "horizon prochaine séance."
    ),
    section_editorial="II — LECTURE ÉDITORIALE",
    section_eco="III — ÉCO & REVUE DE PRESSE",
    section_technicals="V — PHOTO TECHNIQUE — DERNIÈRE SÉANCE",
    section_reco="VI — RECOMMANDATIONS OPÉRATIONNELLES",
    field_position="Position",
    field_confidence="Confiance",
    field_direction="Direction",
    field_ytd="Performance YTD",
    regime_prefix="Régime de marché identifié :",
    stance_confirm=(
        "La lecture macro confirme la position technique : les deux angles "
        "pointent dans la même direction."
    ),
    stance_contradict=(
        "La lecture macro s'oppose à la position technique — l'arbitrage "
        "retient la prudence plutôt que la conviction de départ."
    ),
    stance_neutral=(
        "La lecture macro ne tranche pas : elle laisse la position technique "
        "en place sans la renforcer."
    ),
    press_review_prefix="Revue de presse :",
    press_impact_prefix="Impact synthèse :",
    press_sentiment_prefix="Sentiment dominant :",
    weather_impact_prefix="Impact :",
    weather_none="(aucune météo disponible pour la séance)",
    reco_none="(pas de conclusion narrative pour cette séance)",
)

_LABELS_EN = _BriefLabels(
    months=MONTHS_EN,
    date_prefix="Date:",
    horizon="Decision horizon: next trading session",
    intro=("Today's Compass read on London front-month cocoa, horizon next session."),
    section_editorial="II — EDITORIAL READ",
    section_eco="III — ECO & PRESS REVIEW",
    section_technicals="V — TECHNICAL SNAPSHOT — LAST SESSION",
    section_reco="VI — OPERATIONAL RECOMMENDATIONS",
    field_position="Position",
    field_confidence="Confidence",
    field_direction="Direction",
    field_ytd="YTD performance",
    regime_prefix="Market regime identified:",
    stance_confirm=(
        "The macro read confirms the technical stance: both angles point the same way."
    ),
    stance_contradict=(
        "The macro read opposes the technical stance — the arbitration favours "
        "caution over the original conviction."
    ),
    stance_neutral=(
        "The macro read does not decide: it leaves the technical stance in "
        "place without reinforcing it."
    ),
    press_review_prefix="Press review:",
    press_impact_prefix="Impact summary:",
    press_sentiment_prefix="Dominant sentiment:",
    weather_impact_prefix="Impact:",
    weather_none="(no weather available for this session)",
    reco_none="(no narrative conclusion for this session)",
)

_LABELS_BY_LANG = {"fr": _LABELS_FR, "en": _LABELS_EN}

# Business names for the internal regime tags. The raw tags (bull, highvol…)
# are engine vocabulary and must not surface in a text read aloud.
_REGIME_LABEL = {
    "fr": {
        "bull": "tendance haussière établie",
        "bear": "tendance baissière établie",
        "transition": "marché sans direction claire",
        "highvol": "volatilité élevée",
        "oversold": "zone de survente",
        "overbought": "zone de surachat",
    },
    "en": {
        "bull": "established uptrend",
        "bear": "established downtrend",
        "transition": "no clear direction",
        "highvol": "elevated volatility",
        "oversold": "oversold territory",
        "overbought": "overbought territory",
    },
}

# Substrings that would leak the machinery into a text read aloud.
#
# Two lists, because the brief renders text from two sources with two different
# threat models. Applying one list to both is what broke the 2026-08-23 run.
#
# OUR OWN PROSE — the narrator's conclusion / eco / confidence_rationale. We
# control it through the prompt, so ANY machinery vocabulary is a leak and a
# prompt regression. Broad on purpose: "modèle", "algorithme", "IA" are exactly
# the words a model reaches for when it starts describing itself.
_FORBIDDEN_OWN_PROSE = (
    "regime router",
    "routeur",
    "specialist",
    "spécialiste ml",
    "lightgbm",
    "prob_up",
    "p(up)",
    "soft-gate",
    "wrapper",
    "orchestrator",
    "machine learning",
    "llm",
    "gpt",
    "o4-mini",
    "algorithme",
    "algorithm",
    "modèle",
    "artificial intelligence",
    "intelligence artificielle",
)

# THIRD-PARTY CONTENT — the press review and the weather bulletin. Written by
# other agents summarising real articles and real measurements; they never see
# our engine, so they cannot leak it. What they DO contain is ordinary business
# French: "le modèle coopératif ivoirien", "un algorithme de tri des fèves",
# "l'intelligence artificielle dans l'agriculture". None of that is a leak.
#
# On 2026-08-23 the press summary used the word "modèle" and the brief refused to
# render — killing the job for a session whose decision was already computed. The
# guard was policing a source it was never designed for.
#
# Kept here: only tokens that could not plausibly appear in cocoa journalism and
# would therefore mean our own vocabulary escaped into another agent's output.
_FORBIDDEN_THIRD_PARTY = (
    "regime router",
    "routeur",
    "prob_up",
    "p(up)",
    "soft-gate",
    "lightgbm",
    "orchestrator",
    "o4-mini",
)


class BriefLeakError(RuntimeError):
    """A field about to be rendered names the machinery."""


def _labels_for(language: str) -> _BriefLabels:
    return _LABELS_BY_LANG.get(language, _LABELS_FR)


def _assert_safe(
    value: str | None,
    *,
    field_name: str,
    forbidden: tuple[str, ...] = _FORBIDDEN_OWN_PROSE,
) -> None:
    """Abort before rendering rather than emit a leaky brief.

    The brief is read aloud outside the company and is the most exposed channel
    for reverse-engineering the decision engine. A producer fails, it does not
    degrade.

    ``forbidden`` defaults to the strict list, so a new call site is policed
    strictly unless it opts out explicitly — the safe direction to be wrong in.
    Pass ``_FORBIDDEN_THIRD_PARTY`` for text another agent wrote from external
    sources.
    """
    if not value:
        return
    lowered = value.lower()
    hits = [token for token in forbidden if token in lowered]
    if hits:
        raise BriefLeakError(
            f"{field_name} leaks internals {hits} — refusing to render the brief"
        )


def _format_date(value: date_cls, language: str) -> str:
    labels = _labels_for(language)
    month = labels.months[value.month - 1]
    return (
        f"{value.day} {month} {value.year}"
        if language != "en"
        else f"{value.day} {month} {value.year}"
    )


def _field(label: str, value: str) -> str:
    return f"  {label:<18} : {value}"


def _fmt_signed_pct(value: float | None) -> str | None:
    return None if value is None else f"{value:+.2f}%"


def _render_editorial_section(data: BriefData, language: str) -> list[str]:
    """Section II — the ONLY part that differs from the ensemble brief.

    Three beats, no mechanism named: the regime the market is in, the technical
    stance that follows, and how the macro read arbitrated it.
    """
    labels = _labels_for(language)
    regime_names = _REGIME_LABEL.get(language, _REGIME_LABEL["fr"])
    lines: list[str] = []

    regime_label = regime_names.get(
        data.regime.regime, data.regime.regime.replace("_", " ")
    )
    lines.append(f"  {labels.regime_prefix} {regime_label}.")
    lines.append("")

    stance = data.judge.stance.upper()
    if stance == "CONFIRM":
        lines.append(f"  {labels.stance_confirm}")
    elif stance in ("CONTRADICT", "CONTRARIAN"):
        lines.append(f"  {labels.stance_contradict}")
    else:
        lines.append(f"  {labels.stance_neutral}")

    return lines


def render_brief(data: BriefData, narrative: Narrative) -> str:
    """Render the full daily brief as a single text block."""
    language = data.language
    labels = _labels_for(language)
    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────
    lines.append(SEP_THICK)
    lines.append("COMPASS DAILY BRIEF — Cocoa Outlook")
    lines.append(f"{labels.date_prefix} {_format_date(data.target_date, language)}")
    lines.append(labels.horizon)
    lines.append(SEP_THICK)
    lines.append("")
    lines.append(labels.intro)
    lines.append("")

    # ── I — Signal ────────────────────────────────────────────────────────
    lines.append("I — SIGNAL")
    lines.append(SEP_THIN)
    lines.append(_field(labels.field_position, data.judge.final_decision))
    confidence_line = f"{data.judge.confidence}/5"
    if narrative.confidence_rationale:
        confidence_line = f"{confidence_line} — {narrative.confidence_rationale}"
    lines.append(_field(labels.field_confidence, confidence_line))
    lines.append(_field(labels.field_direction, data.judge.direction))
    ytd = _fmt_signed_pct(data.ytd_score)
    if ytd is not None:
        lines.append(_field(labels.field_ytd, ytd))
    lines.append("")

    # ── Official guaranteed farmgate price (standing reference) ───────────
    farmgate_lines = format_farmgate_lines(
        data.farmgate if isinstance(data.farmgate, Mapping) else None, language
    )
    if farmgate_lines:
        lines.extend(farmgate_lines)
        lines.append("")

    # Fail-loud on every LLM-written field BEFORE rendering anything else, and
    # before any DB write (main.py persists only after render_brief returns) —
    # a refused brief must leave the previous session's narrative untouched.
    #
    # Our own prose is held to the strict list; text other agents wrote from
    # external sources is held to the narrow one. See the two tuples above.
    for field, value in (
        ("conclusion", narrative.conclusion),
        ("eco", narrative.eco),
        ("confidence_rationale", narrative.confidence_rationale),
    ):
        _assert_safe(value, field_name=field)

    for field, value in (
        ("press_summary", data.press_summary),
        ("press_impact", data.press_impact),
        ("press_sentiment", data.press_sentiment),
        ("meteo_summary", data.meteo_summary),
        ("meteo_impact", data.meteo_impact),
        ("weather_body", data.weather_body),
    ):
        _assert_safe(value, field_name=field, forbidden=_FORBIDDEN_THIRD_PARTY)

    # ── II — Editorial read (the only track-specific section) ─────────────
    lines.append(labels.section_editorial)
    lines.append(SEP_THIN)
    lines.extend(_render_editorial_section(data, language))
    lines.append("")

    # ── III — Eco & press review ──────────────────────────────────────────
    lines.append(labels.section_eco)
    lines.append(SEP_THIN)
    if narrative.eco:
        lines.append(narrative.eco)
        lines.append("")
    if data.press_summary:
        lines.append(labels.press_review_prefix)
        lines.append(data.press_summary)
        lines.append("")
    if data.press_impact:
        lines.append(f"{labels.press_impact_prefix} {data.press_impact}")
    if data.press_sentiment:
        lines.append(f"{labels.press_sentiment_prefix} {data.press_sentiment}")
    lines.append("")

    # ── IV — Weather watch ────────────────────────────────────────────────
    lines.append("IV — WEATHER WATCH")
    lines.append(SEP_THIN)
    if data.meteo_summary:
        lines.append(data.meteo_summary)
    if data.meteo_trajectory:
        lines.append(data.meteo_trajectory)
    if data.meteo_impact:
        lines.append(f"{labels.weather_impact_prefix} {data.meteo_impact}")
    if not (data.meteo_summary or data.meteo_impact):
        lines.append(labels.weather_none)
    lines.append("")

    # ── V — Technical snapshot ────────────────────────────────────────────
    lines.append(labels.section_technicals)
    lines.append(SEP_THIN)
    lines.append(data.technicals_snapshot)
    lines.append("")

    # ── VI — Operational recommendations ──────────────────────────────────
    lines.append(labels.section_reco)
    lines.append(SEP_THIN)
    lines.append(narrative.conclusion or labels.reco_none)
    if data.watch_lines:
        lines.append("")
        lines.extend(data.watch_lines)
    lines.append("")
    lines.append(SEP_THICK)

    return "\n".join(lines)

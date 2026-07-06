"""Render the Compass cocoa daily brief from an :class:`EnsembleBriefData`.

The brief is uploaded to Drive and fed verbatim into NotebookLM, which turns
it into the daily audio podcast. Everything written here ends up read aloud —
so the template is intentionally redacted of any reference to the underlying
decision engine (no panel size, no model family, no orchestrator names, no
internal gate diagnostics). Audit details still flow through the DB and
dashboard.

Structure rendered :

  Intro    — single neutral framing line
  I.       — Signal (decision + confidence + direction + YTD)
  II.      — Lecture éditoriale (headline specialist + thematic grouping)
  III.     — Éco & Press review (LLM narrative)
  IV.      — Weather watch
  V.       — Chiffres techniques de la dernière session
  VI.      — Recommandations opérationnelles
"""

from __future__ import annotations

import logging
from datetime import date as date_type, datetime
from typing import TYPE_CHECKING

from scripts.compass_brief_ensemble.specialist_catalog import (
    SPECIALIST_CATALOG,
    SpecialistProfile,
    lookup,
)

if TYPE_CHECKING:
    from scripts.compass_brief_ensemble.db_reader import (
        EnsembleBriefData,
        SpecialistVote,
    )

MOIS_FR = {
    1: "janvier",
    2: "février",
    3: "mars",
    4: "avril",
    5: "mai",
    6: "juin",
    7: "juillet",
    8: "août",
    9: "septembre",
    10: "octobre",
    11: "novembre",
    12: "décembre",
}

SEP_THICK = "═" * 70
SEP_THIN = "─" * 70

_ENGAGED_VOTES = {"OPEN", "HEDGE"}

_THEME_LABEL = {
    "technique": "une lecture technique",
    "fx": "une lecture FX",
    "macro": "une lecture macro",
    "climat": "une lecture climatique",
    "volatilité": "une lecture volatilité",
}

_DECISION_TO_BIAS = {"OPEN": "bullish", "HEDGE": "bearish"}

# Engine-revealing substrings that must NEVER reach NotebookLM, split into two
# tiers because the guard runs on fields with different provenance:
#
#   Tier 1 — _FORBIDDEN_INTERNALS: unambiguous engine/architecture tokens that
#   essentially never occur in legitimate cocoa news. Checked on EVERY guarded
#   field, INCLUDING press_summary (defense-in-depth against a press-review LLM
#   hallucinating engine framing like "the soft-gate indicates...").
#
#   Tier 2 — _FORBIDDEN_ENGINE_VOCAB: generic French financial / ML vocabulary
#   that only reveals the engine when the ENGINE itself says it. These words
#   legitimately appear in external news (e.g. "le prix garanti bord-champ
#   offre un filet de sécurité aux producteurs" — real Ghana press, 2026-07-06).
#   Checked ONLY on the fields authored by cc-ensemble-explainer (eco /
#   conclusion / confidence_rationale), NOT on press_summary — otherwise one
#   ordinary news phrase aborts the whole brief (prod incident 2026-07-06).
#
# The check is substring-only (case-insensitive, no regex) — keeps the lists
# explicit and trivially auditable. A match is fail-loud (abort), never a silent
# redaction, per .claude/rules/pipeline-error-handling.md.
_FORBIDDEN_INTERNALS: tuple[str, ...] = (
    "soft-gate",
    "softgate",
    "wrapper",
    "wrapper_fired",
    "running_acc",
    "realized_return",
    "anomaly_z",
    "anomaly_score_z",
    "dispersion fire",
    "detectors fired",
    "cluster winter",
    "cluster spring",
    "orchestrateur bayésien",
    "14 spécialistes",
    "spécialistes sur 14",
    "sur 14 confirment",
    "sur 14 votent",
    "panel de 14",
    "consensus n/14",
    "net_score",
    "net score",
    "ensemble v1",
)

# Tier 2 — generic vocab, engine-authored fields only (see note above). "des 14"
# lives here (not in Tier 1) because it fires on plain figures like "des 14 000
# tonnes"; as a panel-count leak it only matters inside explainer prose.
_FORBIDDEN_ENGINE_VOCAB: tuple[str, ...] = (
    "des 14",
    "filet de sécurité",
    "filet de securite",
    "propriétaires",
    "machine learning",
)

# Union applied to cc-ensemble-explainer fields (eco / conclusion / rationale).
_FORBIDDEN_ALL: tuple[str, ...] = _FORBIDDEN_INTERNALS + _FORBIDDEN_ENGINE_VOCAB

logger = logging.getLogger(__name__)


class UnsafeBriefContentError(RuntimeError):
    """An upstream LLM-written field still embeds engine internals.

    Raised by the brief renderer when a guarded field matches its tier of
    forbidden tokens: engine-authored fields (``eco`` / ``conclusion`` /
    ``confidence_rationale``) are checked against ``_FORBIDDEN_ALL``, while
    external ``press_summary`` is checked against ``_FORBIDDEN_INTERNALS`` only.
    Per ``.claude/rules/pipeline-error-handling.md`` the brief job must
    fail loud rather than ship a leaky `.txt` to NotebookLM — the recovery
    path is to diagnose the upstream source (``cc-ensemble-explainer`` for
    engine fields, the press-review agent for ``press_summary``), fix it,
    and manually relaunch.
    """


def _assert_safe(
    value: str | None, *, field_name: str, tokens: tuple[str, ...]
) -> None:
    """Raise ``UnsafeBriefContentError`` if ``value`` carries any forbidden
    token from ``tokens``. No-op when ``value`` is empty or safe.

    Callers pass the tier that fits the field's provenance: engine-authored
    fields (eco / conclusion / confidence_rationale) get ``_FORBIDDEN_ALL``;
    external content (press_summary) gets only ``_FORBIDDEN_INTERNALS`` so a
    legitimate news phrase does not abort the brief.
    """
    if not value:
        return
    lowered = value.lower()
    hits = [tok for tok in tokens if tok in lowered]
    if not hits:
        return
    logger.error(
        "Brief field %s contains forbidden engine tokens %s — refusing to "
        "render (fail-loud). For eco/conclusion/confidence_rationale the likely "
        "cause is cc-ensemble-explainer leaking engine internals; for "
        "press_summary an external news phrase matched a genuine internal "
        "token. Diagnose before relaxing — see runbooks/brief-dual-track.md.",
        field_name,
        hits,
    )
    raise UnsafeBriefContentError(
        f"Refused to render brief: field '{field_name}' embeds engine "
        f"internals ({hits}). Investigate upstream source, fix, and relaunch."
    )


def _format_date(value) -> str:
    if isinstance(value, date_type):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return value
    else:
        return str(value)
    return f"{dt.day} {MOIS_FR[dt.month]} {dt.year}"


def _fmt_signed_pct(value) -> str | None:
    """Format a YTD-style numeric value as a signed percentage with 2 dp."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f"{f:+.2f}%"


def render_brief(data: "EnsembleBriefData") -> str:
    """Render the full daily brief as a single text block."""
    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────
    lines.append(SEP_THICK)
    lines.append("COMPASS DAILY BRIEF — Cocoa Outlook")
    lines.append(f"Date : {_format_date(data.target_date)}")
    lines.append("Horizon décisionnel : 4 à 5 sessions boursières")
    lines.append(SEP_THICK)
    lines.append("")

    # ── Intro — neutral framing, no panel ─────────────────────────────────
    lines.append(
        "Lecture Compass du jour sur le front-month cocoa Londres, "
        "horizon 4 à 5 sessions."
    )
    lines.append("")

    # ── I — Signal ────────────────────────────────────────────────────────
    lines.append("I — SIGNAL")
    lines.append(SEP_THIN)
    lines.append(f"  Position           : {data.decision}")
    if data.confidence is not None:
        rationale = (data.confidence_rationale or "").strip()
        if rationale:
            lines.append(f"  Confiance          : {data.confidence}/5 — {rationale}")
        else:
            lines.append(f"  Confiance          : {data.confidence}/5")
    if data.direction:
        lines.append(f"  Direction          : {data.direction}")
    ytd = _fmt_signed_pct(data.ytd_score)
    if ytd is not None:
        lines.append(f"  Performance YTD    : {ytd}")
    lines.append("")

    # ── II — Lecture éditoriale ───────────────────────────────────────────
    lines.append("II — LECTURE ÉDITORIALE")
    lines.append(SEP_THIN)
    lines.extend(_render_editorial_section(data))
    lines.append("")

    # Fail-loud guard on every LLM-written field BEFORE rendering anything
    # else — better to abort early than to emit a partial leaky brief.
    _assert_safe(data.eco, field_name="eco", tokens=_FORBIDDEN_ALL)
    _assert_safe(
        data.press_summary, field_name="press_summary", tokens=_FORBIDDEN_INTERNALS
    )
    _assert_safe(data.conclusion, field_name="conclusion", tokens=_FORBIDDEN_ALL)
    _assert_safe(
        data.confidence_rationale,
        field_name="confidence_rationale",
        tokens=_FORBIDDEN_ALL,
    )

    # ── III — Éco & press review ──────────────────────────────────────────
    lines.append("III — ÉCO & PRESS REVIEW")
    lines.append(SEP_THIN)
    if data.eco:
        lines.append(data.eco)
        lines.append("")
    if data.press_summary:
        lines.append("Press review :")
        lines.append(data.press_summary)
        lines.append("")
    if data.press_impact:
        lines.append(f"Impact synthèse : {data.press_impact}")
    if data.press_sentiment:
        lines.append(f"Sentiment dominant : {data.press_sentiment}")
    lines.append("")

    # ── IV — Weather watch ────────────────────────────────────────────────
    lines.append("IV — WEATHER WATCH")
    lines.append(SEP_THIN)
    if data.meteo_summary:
        lines.append(data.meteo_summary)
    if data.meteo_trajectory:
        lines.append(data.meteo_trajectory)
    if data.meteo_impact:
        lines.append(f"Impact : {data.meteo_impact}")
    if not (data.meteo_summary or data.meteo_impact):
        lines.append("(aucune météo disponible pour la session)")
    lines.append("")

    # ── V — Chiffres techniques ───────────────────────────────────────────
    lines.append("V — CHIFFRES TECHNIQUES DERNIÈRE SESSION")
    lines.append(SEP_THIN)
    lines.append(data.technicals_snapshot)
    lines.append("")

    # ── VI — Recommandations ──────────────────────────────────────────────
    lines.append("VI — RECOMMANDATIONS OPÉRATIONNELLES")
    lines.append(SEP_THIN)
    if data.conclusion:
        lines.append(data.conclusion)
    else:
        lines.append(
            "(pas de conclusion narrative — la lecture humaine n'a pas "
            "encore été enrichie pour cette session)"
        )
    lines.append("")
    lines.append(SEP_THICK)

    return "\n".join(lines)


def _render_editorial_section(data: "EnsembleBriefData") -> list[str]:
    """Section II — headline lecture + thematic convergence.

    Picks one specialist as the editorial headline (priority: vote aligned
    with the daily decision AND bias matching the decision direction), then
    groups the remaining engaged specialists by business theme. No counts,
    no codes, no clusters, no horizons — pure editorial framing.
    """
    engaged: list[SpecialistVote] = [
        s for s in data.specialists if s.pred in _ENGAGED_VOTES
    ]
    if not engaged:
        return [
            "  Pas de lecture marquée engagée sur cette session — "
            "le marché est observé sans prise de position."
        ]

    headline = _pick_headline(engaged, data.decision)
    lines: list[str] = []

    if headline is not None:
        headline_profile = lookup(headline.name)
        if headline_profile is not None:
            lines.append(f"  Lecture phare du jour : {headline_profile.label}.")
            for chunk in _wrap_indented(
                headline_profile.description, indent="  ", width=80
            ):
                lines.append(chunk)
            lines.append("")

    others = [s for s in engaged if s is not headline]
    theme_sentence = _render_theme_convergence(others)
    if theme_sentence:
        lines.append(f"  {theme_sentence}")

    return lines


def _pick_headline(
    engaged: list["SpecialistVote"], decision: str
) -> "SpecialistVote | None":
    """Pick the most editorial-meaningful specialist for the day.

    Priority tiers, in order :
      1. vote == decision AND architectural bias matches the decision
         direction (e.g. HEDGE decision + bearish specialist).
      2. vote == decision, any bias.
      3. fallback: first engaged specialist.
    """
    if not engaged:
        return None

    target_bias = _DECISION_TO_BIAS.get(decision)
    if target_bias is not None:
        for vote in engaged:
            profile = lookup(vote.name)
            if (
                profile is not None
                and vote.pred == decision
                and profile.bias == target_bias
            ):
                return vote

    for vote in engaged:
        if vote.pred == decision:
            return vote

    return engaged[0]


def _render_theme_convergence(others: list["SpecialistVote"]) -> str:
    """Build a single editorial sentence describing what else is converging.

    Returns an empty string when no other engaged specialists exist or
    when none of them map to a known theme.
    """
    themes_seen: list[str] = []
    for vote in others:
        profile = lookup(vote.name)
        if profile is None:
            continue
        label = _THEME_LABEL.get(profile.theme)
        if label is None:
            continue
        if label not in themes_seen:
            themes_seen.append(label)

    if not themes_seen:
        return ""
    if len(themes_seen) == 1:
        return f"D'autres lectures convergent sur ce verdict, dont {themes_seen[0]}."
    if len(themes_seen) == 2:
        return (
            f"D'autres lectures convergent sur ce verdict — {themes_seen[0]} "
            f"et {themes_seen[1]}."
        )
    head = ", ".join(themes_seen[:-1])
    return f"D'autres lectures convergent sur ce verdict — {head} et {themes_seen[-1]}."


def _wrap_indented(text: str, indent: str, width: int = 80) -> list[str]:
    """Soft-wrap ``text`` to lines of at most ``width`` chars, prefixed by indent.

    Word-aware, no hyphenation, preserves the original phrasing. Every wrapped
    line keeps the ``indent`` prefix so the brief stays visually aligned.
    """
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    current = indent
    for word in words:
        if current == indent:
            candidate = indent + word
        else:
            candidate = current + " " + word
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            current = indent + word
    if current != indent:
        lines.append(current)
    return lines


# Exposed for compatibility with downstream callers that import the catalog
# symbol from here. Re-exporting keeps the import path stable.
__all__ = [
    "render_brief",
    "SPECIALIST_CATALOG",
    "SpecialistProfile",
]

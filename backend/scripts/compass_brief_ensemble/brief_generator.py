"""Render the ensemble brief from an :class:`EnsembleBriefData` instance.

7-section template + a contextual intro to the panel of specialists :

  Intro — Qui parle aujourd'hui (le panel + qui s'engage)
  I.    Signal ensemble + persistence + triggers réévaluation
  II.   Les spécialistes qui se sont exprimés aujourd'hui (committed only)
        — listed by business profile (cf. specialist_catalog.SPECIALIST_CATALOG)
  III.  Macro radar ensemble (sentiment + anomaly + priors)
  IV.   Éco & press review (LLM narrative)
  V.    Weather watch
  VI.   Chiffres techniques
  VII.  Recommandations opérationnelles

Pure formatter — no DB, no LLM. Takes the assembled data and returns a string.
The committed/abstained vocabulary follows the soft-gate's semantic : a
specialist whose pred is OPEN or HEDGE is *engaged*, one whose pred is MONITOR
is *abstaining* (it contributes 0 to the gate's net_score). This is why the
brief focuses on the engaged voices — they are the ones the gate listened to.
"""

from __future__ import annotations

from datetime import date as date_type, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from scripts.compass_brief_ensemble.specialist_catalog import (
    SPECIALIST_CATALOG,
    cluster_of,
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

# A specialist whose vote is one of these is considered *committed* by the
# soft-gate (it contributes to the weighted net_score). MONITOR-level votes
# at the specialist level are abstentions, not "MONITOR votes" in the usual
# sense — they sit out, neither pushing the gate up nor down.
_ENGAGED_VOTES = {"OPEN", "HEDGE"}


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


def _fmt(value, precision: int = 3, suffix: str = "") -> str:
    """Format a numeric/Decimal/None value compactly."""
    if value is None:
        return "n/a"
    if isinstance(value, Decimal):
        try:
            return f"{float(value):.{precision}f}{suffix}"
        except (ValueError, OverflowError):
            return str(value)
    if isinstance(value, float):
        return f"{value:.{precision}f}{suffix}"
    return f"{value}{suffix}"


def _direction_glyph(signed_vote: int | None) -> str:
    if signed_vote is None:
        return "→"
    if signed_vote > 1:
        return "↗"
    if signed_vote < -1:
        return "↘"
    return "→"


def _cluster_tag(signed_vote: int | None) -> str:
    if signed_vote is None:
        return ""
    if signed_vote > 1:
        return "bullish"
    if signed_vote < -1:
        return "bearish"
    return "neutre"


def _anomaly_label(z) -> str:
    if z is None:
        return "n/a"
    try:
        zf = float(z)
    except (TypeError, ValueError):
        return "n/a"
    if zf >= 2.5:
        return "CRITIQUE"
    if zf >= 1.5:
        return "élevé"
    return "normal"


def _bool_str(value: bool) -> str:
    return "oui" if value else "non"


def _vote_phrase(pred: str) -> str:
    """Human-friendly verb for a vote at the specialist level."""
    if pred == "OPEN":
        return "ouvre la position"
    if pred == "HEDGE":
        return "appelle à couvrir"
    return "préfère ne pas s'exprimer"


def render_brief(data: "EnsembleBriefData") -> str:
    """Render the full ensemble brief as a single text block."""
    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────
    lines.append(SEP_THICK)
    lines.append("COMPASS DAILY BRIEF — Cocoa Outlook (Ensemble v1.0.0)")
    lines.append(f"Date : {_format_date(data.target_date)}")
    lines.append("Horizon décisionnel : 4-5 trading days (J+4-J+5)")
    lines.append(SEP_THICK)
    lines.append("")

    # ── Intro — Qui parle aujourd'hui ─────────────────────────────────────
    lines.append("À PROPOS DU PANEL COMPASS")
    lines.append(SEP_THIN)
    lines.extend(_render_panel_intro(data))
    lines.append("")

    # ── I — Signal ensemble ───────────────────────────────────────────────
    lines.append("I — SIGNAL ENSEMBLE")
    lines.append(SEP_THIN)
    lines.append(f"  Position           : {data.decision}")
    if data.confidence is not None:
        lines.append(
            f"  Confiance          : {data.confidence}/5 (jugée par notre relecteur LLM)"
        )
    if data.direction:
        lines.append(f"  Direction          : {data.direction}")
    lines.append(
        f"  Persistence        : biais maintenu depuis {data.persistence_days} jour(s)"
    )
    triggers = _build_triggers(data)
    if triggers:
        lines.append("  Triggers de réévaluation :")
        for t in triggers:
            lines.append(f"    • {t}")
    lines.append("")

    # ── II — Les spécialistes qui se sont exprimés ────────────────────────
    lines.append("II — LES SPÉCIALISTES QUI SE SONT EXPRIMÉS AUJOURD'HUI")
    lines.append(SEP_THIN)
    lines.extend(_render_specialists_section(data))
    lines.append("")

    # ── III — Macro radar ──────────────────────────────────────────────────
    lines.append("III — MACRO RADAR ENSEMBLE")
    lines.append(SEP_THIN)
    lines.append(
        f"  Macro direction               : {_fmt(data.macro_direction, 0)} "
        f"(depuis sentiment features)"
    )
    lines.append(
        f"  Surprise macro                : {_fmt(data.macro_surprise, 3, 'σ')} "
        f"(half_life {_fmt(data.macro_half_life_days, 0, ' jours')})"
    )
    lines.append(
        f"  Anomaly score                 : {_fmt(data.anomaly_score_z, 2)} "
        f"({_anomaly_label(data.anomaly_score_z)})"
    )
    lines.append(
        f"  Prior structurel              : P(OPEN)={_fmt(data.prior_open, 3)} "
        f"P(HEDGE)={_fmt(data.prior_hedge, 3)} P(MONITOR)={_fmt(data.prior_monitor, 3)}"
    )
    lines.append(
        f"  Wrapper actif                 : {_bool_str(data.wrapper_active)}  "
        f"(soft-gate disait {data.soft_gate_decision})"
    )
    lines.append(
        f"  Detectors fired               : run_acc={_bool_str(data.fired_running_acc)} "
        f"dispersion={_bool_str(data.fired_dispersion)} "
        f"trend={_bool_str(data.fired_trend)} 3way={_bool_str(data.fired_three_way)}"
    )
    lines.append(
        f"  Running acc 5d (Compass)      : {_fmt(data.running_acc_5d, 4)}  "
        f"| Realized return 5d : {_fmt(data.realized_return_5d, 4)}"
    )
    lines.append("")

    # ── IV — Éco & press review ──────────────────────────────────────────
    lines.append("IV — ÉCO & PRESS REVIEW (LECTURE HUMAINE)")
    lines.append(SEP_THIN)
    if data.eco:
        lines.append(data.eco)
        lines.append("")
    if data.press_summary:
        lines.append("Press review (cc-press-review-agent) :")
        lines.append(data.press_summary)
        lines.append("")
    if data.press_impact:
        lines.append(f"Impact synthèse : {data.press_impact}")
    if data.press_sentiment:
        lines.append(f"Sentiment dominant : {data.press_sentiment}")
    lines.append("")

    # ── V — Weather watch ────────────────────────────────────────────────
    lines.append("V — WEATHER WATCH")
    lines.append(SEP_THIN)
    if data.meteo_summary:
        lines.append(data.meteo_summary)
    if data.meteo_impact:
        lines.append(f"Impact : {data.meteo_impact}")
    if not (data.meteo_summary or data.meteo_impact):
        lines.append("(aucune météo disponible pour la session)")
    lines.append("")

    # ── VI — Chiffres techniques ─────────────────────────────────────────
    lines.append("VI — CHIFFRES TECHNIQUES DERNIÈRE SESSION")
    lines.append(SEP_THIN)
    lines.append(data.technicals_snapshot)
    lines.append("")

    # ── VII — Recommandations ───────────────────────────────────────────
    lines.append("VII — RECOMMANDATIONS OPÉRATIONNELLES")
    lines.append(SEP_THIN)
    if data.conclusion:
        lines.append(data.conclusion)
    else:
        lines.append(
            "(pas de conclusion narrative — cc-ensemble-explainer n'a pas encore tourné)"
        )
    lines.append("")
    lines.append(SEP_THICK)

    return "\n".join(lines)


def _render_panel_intro(data: "EnsembleBriefData") -> list[str]:
    """Magazine-style intro that explains *what* the panel is.

    Read aloud first thing in the podcast so the auditeur understands the
    speakers behind the upcoming decision. Deliberately repeated each day —
    the auditeur may be discovering the system on this brief.
    """
    n_committed = data.n_committed_specialists or 0
    n_abstained = 14 - n_committed
    return [
        "  Le signal du jour provient de l'ensemble Compass v1.0.0 — un panel de",
        "  14 spécialistes propriétaires entraînés en machine learning sur dix ans",
        "  de données cocoa Londres. Chacun a sa propre méthode : structure",
        "  de prix, lecture FX, conditions climatiques ENSO, dynamique de",
        "  volatilité. Six d'entre eux composent le cluster Winter (tendance",
        "  technique + FX), huit autres le cluster Spring (macro et climat).",
        "",
        "  Chaque jour, ces spécialistes ont le choix entre trois positions :",
        "  s'engager à l'achat (OPEN), appeler à la couverture (HEDGE), ou",
        "  s'abstenir (MONITOR) quand leur signal est trop faible. L'orchestrateur",
        "  bayésien Compass agrège uniquement les voix engagées et tranche.",
        "",
        f"  Aujourd'hui {n_committed} spécialiste(s) sur 14 se sont engagés ; "
        f"{n_abstained} ont préféré s'abstenir.",
    ]


def _render_specialists_section(data: "EnsembleBriefData") -> list[str]:
    """Section II — focused on engaged specialists, with their profiles.

    The committed/abstained partition follows the soft-gate semantic. We
    expose every engaged specialist with its business profile (label +
    description from SPECIALIST_CATALOG) so the auditeur understands *who*
    is speaking, not just an aggregate count. Abstainers are summarised.
    """
    lines: list[str] = []

    winter_glyph = _direction_glyph(data.winter_vote_signed)
    winter_tag = _cluster_tag(data.winter_vote_signed)
    spring_glyph = _direction_glyph(data.spring_vote_signed)
    spring_tag = _cluster_tag(data.spring_vote_signed)

    lines.append(
        f"  Score cumulé Winter (TB/FX)        : {_fmt(data.winter_vote_signed, 0)}  "
        f"{winter_glyph} {winter_tag}"
    )
    lines.append(
        f"  Score cumulé Spring (macro/ENSO)   : {_fmt(data.spring_vote_signed, 0)}  "
        f"{spring_glyph} {spring_tag}"
    )
    lines.append(
        f"  Spécialistes engagés               : "
        f"{_fmt(data.n_committed_specialists, 0)}/14"
    )
    lines.append("")

    # Partition specialists: engaged (OPEN or HEDGE) vs abstained (MONITOR)
    engaged: list[SpecialistVote] = [
        s for s in data.specialists if s.pred in _ENGAGED_VOTES
    ]
    abstained: list[SpecialistVote] = [
        s for s in data.specialists if s.pred not in _ENGAGED_VOTES
    ]

    if not engaged:
        lines.append(
            "  Aucun spécialiste ne s'est engagé aujourd'hui — le panel reste "
            "spectateur, la décision finale revient au prior structurel."
        )
        lines.append("")
        return lines

    lines.append(f"  ★ Voix engagées ({len(engaged)})")
    lines.append("")

    for vote in engaged:
        profile = lookup(vote.name)
        if profile is None:
            # Unknown specialist — should never happen in steady state. Be
            # defensive : show the raw name so the brief still renders.
            lines.append(
                f"    [{vote.pred}] {vote.name} — profil non répertorié "
                f"(window={vote.window_months}m)"
            )
            continue
        # Header line — vote + business label + cluster code
        lines.append(
            f"    [{vote.pred:5s}] {profile.label}  · cluster {profile.cluster.capitalize()} "
            f"({profile.code}, horizon {profile.horizon_days}j)"
        )
        # Description wrapped onto two indented lines for readability
        for chunk in _wrap_indented(profile.description, indent="      ", width=80):
            lines.append(chunk)
        lines.append(
            f"      → {profile.label.split(' — ')[0]} {_vote_phrase(vote.pred)} ce jour."
        )
        lines.append("")

    if abstained:
        lines.append(f"  ☐ Voix silencieuses ({len(abstained)})")
        lines.append(
            "    Les autres spécialistes ont jugé leur signal insuffisant pour "
            "engager une position et ne contribuent pas au score."
        )
        abstained_names = [
            (lookup(s.name).label if lookup(s.name) else s.name) for s in abstained
        ]
        # Render names compactly in groups of 3 for podcast read-aloud friendliness
        for i in range(0, len(abstained_names), 3):
            chunk = ", ".join(abstained_names[i : i + 3])
            lines.append(f"      · {chunk}")

    return lines


def _wrap_indented(text: str, indent: str, width: int = 80) -> list[str]:
    """Soft-wrap ``text`` to lines of at most ``width`` chars, prefixed by indent.

    Word-aware, no hyphenation, preserves the original phrasing. Every wrapped
    line keeps the ``indent`` prefix so the brief stays visually aligned.
    """
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    current = indent  # holds the line currently being built, indent + payload
    for word in words:
        if current == indent:
            # No payload yet — start the line with the first word.
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


def _build_triggers(data: "EnsembleBriefData") -> list[str]:
    """Build the list of "reasons to re-evaluate" based on current diagnostics."""
    triggers: list[str] = []
    triggers.append("anomaly_score_z > 2.5 → bascule MONITOR forcée")
    triggers.append("dispersion fire (specialists désaccord soutenu)")
    triggers.append("sentiment shift > 1.5σ (press_review macro surprise)")

    # Add a contextual trigger if running_acc_5d is below a healthy threshold
    if data.running_acc_5d is not None:
        try:
            if float(data.running_acc_5d) < 0.6:
                triggers.append(
                    f"running_acc_5d={_fmt(data.running_acc_5d, 3)} sous 0.6 — "
                    "perf récente faible, override Compass actif"
                )
        except (TypeError, ValueError):
            pass
    return triggers


# Kept for backward-compat — used to be imported elsewhere. New callers should
# read profiles via the catalog directly.
def _classify_specialist(name: str) -> str:
    """Delegate to the catalog. Returns 'winter' / 'spring' / 'other'."""
    return cluster_of(name)


def _find_dissenters(
    specialists: list["SpecialistVote"], decision: str
) -> list["SpecialistVote"]:
    """Return specialists whose vote differs from the wrapped decision."""
    return [s for s in specialists if s.pred != decision]


# Exposed for compatibility with downstream callers that might import the
# catalog symbol from here. Re-exporting keeps the import path stable.
__all__ = [
    "render_brief",
    "SPECIALIST_CATALOG",
]

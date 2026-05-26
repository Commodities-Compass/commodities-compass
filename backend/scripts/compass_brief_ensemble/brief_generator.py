"""Render the ensemble brief from an :class:`EnsembleBriefData` instance.

7-section template (I-VII) — designed to leverage ensemble's structured outputs:
  I.   Signal ensemble + persistence + triggers réévaluation
  II.  Décomposition 14 spécialistes (clusters Winter + Spring)
  III. Macro radar ensemble (sentiment + anomaly + priors)
  IV.  Éco & press review (LLM narrative)
  V.   Weather watch
  VI.  Chiffres techniques
  VII. Recommandations opérationnelles

Pure formatter — no DB, no LLM. Takes the assembled data and returns a string.
"""

from __future__ import annotations

from datetime import date as date_type, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

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

# Heuristic mapping from specialist_name → cluster. Aligned with the R&D
# documentation in docs/onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md.
# Winter cluster = TB/FX-anchored specialists. Spring cluster = macro/ENSO
# anchored. We classify on the prefix/suffix of the specialist name; any
# unknown name falls into "uncategorised" and is still listed in the table.
_WINTER_TAGS = ("xpol_W", "xpol_w_", "exp_optim_002", "exp_optim_005", "exp_optim_008")
_SPRING_TAGS = ("xpol_S", "xpol_s_", "exp_optim_011", "macro_combined", "spring")


def _classify_specialist(name: str) -> str:
    n = name.lower()
    if any(t.lower() in n for t in _WINTER_TAGS):
        return "winter"
    if any(t.lower() in n for t in _SPRING_TAGS):
        return "spring"
    return "other"


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

    # ── I — Signal ensemble ───────────────────────────────────────────────
    lines.append("I — SIGNAL ENSEMBLE")
    lines.append(SEP_THIN)
    lines.append(f"  Position           : {data.decision}")
    if data.confidence is not None:
        lines.append(
            f"  Confiance          : {data.confidence}/5 (LLM-judged contextuel)"
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

    # ── II — Décomposition spécialistes ──────────────────────────────────
    lines.append("II — DÉCOMPOSITION 14 SPÉCIALISTES")
    lines.append(SEP_THIN)
    winter_glyph = _direction_glyph(data.winter_vote_signed)
    winter_tag = _cluster_tag(data.winter_vote_signed)
    spring_glyph = _direction_glyph(data.spring_vote_signed)
    spring_tag = _cluster_tag(data.spring_vote_signed)
    lines.append(
        f"  Cluster Winter (TB/FX)        : {_fmt(data.winter_vote_signed, 0)}  "
        f"{winter_glyph} {winter_tag}"
    )
    lines.append(
        f"  Cluster Spring (macro/ENSO)   : {_fmt(data.spring_vote_signed, 0)}  "
        f"{spring_glyph} {spring_tag}"
    )
    lines.append(
        f"  Specialists committed         : {_fmt(data.n_committed_specialists, 0)}/14"
    )

    dissenters = _find_dissenters(data.specialists, data.decision)
    if dissenters:
        lines.append(
            f"  Désaccord notable             : {', '.join(s.name for s in dissenters)} "
            f"(votent {dissenters[0].pred})"
        )
    lines.append("")
    lines.append("  Tableau détaillé :")
    for spec in data.specialists:
        cluster = _classify_specialist(spec.name)
        lines.append(
            f"    {spec.name:<32s} {spec.pred:<8s} window={spec.window_months}m  [{cluster}]"
        )
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


def _find_dissenters(
    specialists: list["SpecialistVote"], decision: str
) -> list["SpecialistVote"]:
    """Return specialists whose vote differs from the wrapped decision.

    Useful narrative element : "1 sceptique sur 14 vote HEDGE alors que le
    consensus est OPEN".
    """
    return [s for s in specialists if s.pred != decision]

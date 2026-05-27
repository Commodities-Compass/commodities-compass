"""Catalog of the 14 ensemble specialists with business-friendly labels.

The technical IDs (``exp_optim_002``, ``xpol_S_bear_garch_macro``, etc.) come
from the R&D vendor pack ([backend/vendor/campaign5_ensemble_v1.0.0/ensemble/
optimizer/specialists.py]). For the daily brief and podcast we want to surface
*what they actually do* in a way a trader or business reader understands —
without leaking the raw research IDs or the model family jargon (GARCH,
Triple-Barrier, calibrated-TB, etc.).

This catalog is the single source of truth for that translation. The brief
generator and any downstream consumer should import ``SPECIALIST_CATALOG`` to
look up a profile by its technical name.

Source of truth for cluster assignment :
[backend/vendor/campaign5_ensemble_v1.0.0/ensemble/orchestrator/transition_wrapper.py]
``DEFAULT_CLUSTER_MAPPING``. We mirror it here so the brief is decoupled from
the vendor module (which could be rewritten without warning at the next R&D
delivery).

Editorial rules respected in the descriptions :
  * never say "IA" or "AI" — these are proprietary ML-trained specialists
  * speak in business terms (tendance, FX, climat, volatilité)
  * keep each description ≤2 sentences for podcast read-aloud
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ClusterName = Literal["winter", "spring"]


@dataclass(frozen=True)
class SpecialistProfile:
    """Business-facing description of one specialist."""

    name: str
    """Technical ID written by cc-ensemble-compute on pl_specialist_prediction.specialist_name."""

    cluster: ClusterName
    """Mirrors DEFAULT_CLUSTER_MAPPING from the vendor wrapper."""

    code: str
    """Short R&D code (W1, W2... S1, S2... X1, X2...) kept for audit cross-reference."""

    label: str
    """Business-friendly title shown in the brief and read aloud in the podcast."""

    description: str
    """1-2 sentences describing what the specialist watches and how it votes,
    no technical jargon. Read aloud in the podcast when this specialist
    engages on a given day."""

    horizon_days: int
    """Forward-return horizon the specialist was trained on. 6 (~1 week) for
    most, 22 (~3 weeks) for the slow cycle specialist."""

    bias: Literal["neutral", "bearish", "bullish"]
    """Class-weight bias applied at training time. Most are neutral; some
    Spring specialists were intentionally tilted bearish (S1, S2, X4) or
    bullish (S3, S4, S5, S6, X3) to keep coverage on directional moves."""


# ───────────────────────────────────────────────────────────────────────────
# WINTER cluster (6) — tendance / structure de prix / FX hedging
# ───────────────────────────────────────────────────────────────────────────
WINTER_PROFILES: tuple[SpecialistProfile, ...] = (
    SpecialistProfile(
        name="exp_optim_002",
        cluster="winter",
        code="W1",
        label="Lecteur de tendance — référence",
        description=(
            "Identifie les retournements du marché via une méthode de barrières "
            "techniques (objectif, stop, horizon) calibrée sur dix ans de cocoa "
            "Londres. C'est le pilier purement technique du panel."
        ),
        horizon_days=6,
        bias="neutral",
    ),
    SpecialistProfile(
        name="exp_optim_005",
        cluster="winter",
        code="W2",
        label="Lecteur de tendance volatilité-conditionnel",
        description=(
            "Variante du lecteur de référence enrichie d'un modèle de volatilité "
            "qui pondère le signal selon le régime ambiant. Sa voix porte davantage "
            "quand le marché s'agite."
        ),
        horizon_days=6,
        bias="neutral",
    ),
    SpecialistProfile(
        name="exp_optim_006",
        cluster="winter",
        code="W3",
        label="Spécialiste cycle long — 3 semaines",
        description=(
            "Seul modèle du panel à raisonner sur un horizon de trois semaines "
            "boursières (~22 jours). Utile pour détecter les retournements lents "
            "que les autres spécialistes, calibrés sur cinq jours, ratent."
        ),
        horizon_days=22,
        bias="neutral",
    ),
    SpecialistProfile(
        name="exp_optim_011",
        cluster="winter",
        code="W4",
        label="Stratège macro global",
        description=(
            "Croise les conditions climatiques globales (El Niño / La Niña) "
            "et les mouvements de la livre face au dollar — historiquement "
            "le scorer le plus régulier de l'équipe."
        ),
        horizon_days=6,
        bias="neutral",
    ),
    SpecialistProfile(
        name="xpol_W_TB_garch",
        cluster="winter",
        code="X1",
        label="Lecteur de tendance + ajustement volatilité",
        description=(
            "Combinaison du lecteur de tendance de référence et de l'ajustement "
            "volatilité-conditionnel. Quand ces deux approches convergent sur le "
            "même verdict, le signal est considéré comme doublement filtré."
        ),
        horizon_days=6,
        bias="neutral",
    ),
    SpecialistProfile(
        name="xpol_W_TB_macro",
        cluster="winter",
        code="X2",
        label="Lecteur de tendance contextualisé macro",
        description=(
            "Identique au lecteur de tendance de référence, mais enrichi des "
            "conditions climatiques ENSO et FX. Tire son signal quand la macro "
            "renforce la dynamique purement technique."
        ),
        horizon_days=6,
        bias="neutral",
    ),
)


# ───────────────────────────────────────────────────────────────────────────
# SPRING cluster (8) — macro/ENSO/sentiment, biais directionnels assumés
# ───────────────────────────────────────────────────────────────────────────
SPRING_PROFILES: tuple[SpecialistProfile, ...] = (
    SpecialistProfile(
        name="exp_optim_017_bear_4",
        cluster="spring",
        code="S1",
        label="Sentinelle baissière FX",
        description=(
            "Calibrée pour repérer les retournements baissiers via les "
            "mouvements de change. Vote rarement à l'achat par construction — "
            "quand elle s'engage, c'est presque toujours pour couvrir."
        ),
        horizon_days=6,
        bias="bearish",
    ),
    SpecialistProfile(
        name="exp_optim_017_bear_8",
        cluster="spring",
        code="S2",
        label="Sentinelle baissière macro + FX",
        description=(
            "Variante de la sentinelle baissière qui ajoute le signal climatique "
            "ENSO. Plus prudente : elle ne s'engage que si pression FX et stress "
            "hydrique se cumulent."
        ),
        horizon_days=6,
        bias="bearish",
    ),
    SpecialistProfile(
        name="exp_optim_017_bull_4",
        cluster="spring",
        code="S6",
        label="Stratège haussier FX",
        description=(
            "Calibré pour détecter les phases de hausse soutenue, lit "
            "principalement la livre face au dollar. Vote rarement à la "
            "couverture par construction."
        ),
        horizon_days=6,
        bias="bullish",
    ),
    SpecialistProfile(
        name="exp_optim_017_bull_5",
        cluster="spring",
        code="S3",
        label="Stratège haussier baseline (approche logistique)",
        description=(
            "Approche statistique logistique pure, fortement biaisée à l'achat. "
            "Vote tranché — peu de zones grises, soit elle est à l'achat soit "
            "elle se retire."
        ),
        horizon_days=6,
        bias="bullish",
    ),
    SpecialistProfile(
        name="exp_optim_017_bull_7",
        cluster="spring",
        code="S4",
        label="Stratège haussier FX renforcé",
        description=(
            "Variante du stratège haussier FX avec un biais encore plus marqué "
            "(poids triple sur les phases de hausse). Voix la plus offensive du "
            "panel quand la livre se renforce."
        ),
        horizon_days=6,
        bias="bullish",
    ),
    SpecialistProfile(
        name="exp_optim_017_bull_8",
        cluster="spring",
        code="S5",
        label="Stratège haussier multi-facteur",
        description=(
            "Utilise la palette de features la plus large du panel — une "
            "cinquantaine de dimensions techniques et fondamentales. Sa voix "
            "compte particulièrement quand le marché présente des signaux mixtes."
        ),
        horizon_days=6,
        bias="bullish",
    ),
    SpecialistProfile(
        name="xpol_S_bull_garch_fx",
        cluster="spring",
        code="X3",
        label="Stratège haussier volatilité-conditionnel FX",
        description=(
            "Combine biais haussier, ajustement volatilité et lecture FX. "
            "Tire son signal sur les phases de hausse soutenue où la "
            "volatilité reste maîtrisée."
        ),
        horizon_days=6,
        bias="bullish",
    ),
    SpecialistProfile(
        name="xpol_S_bear_garch_macro",
        cluster="spring",
        code="X4",
        label="Sentinelle baissière complète",
        description=(
            "Combine toutes les défenses du panel : biais baissier, ajustement "
            "volatilité, FX et ENSO. La voix la plus prudente — vote à la "
            "couverture seulement quand tous les facteurs s'alignent en pression "
            "baissière."
        ),
        horizon_days=6,
        bias="bearish",
    ),
)


# Public — full catalog indexed by technical name.
SPECIALIST_CATALOG: dict[str, SpecialistProfile] = {
    p.name: p for p in (*WINTER_PROFILES, *SPRING_PROFILES)
}


def lookup(name: str) -> SpecialistProfile | None:
    """Return the profile for a specialist name, or None if unknown.

    Unknown names should NOT crash the brief — the profile is missing only
    in the case of a future R&D rename (which should be flagged by tests).
    """
    return SPECIALIST_CATALOG.get(name)


def cluster_of(name: str) -> str:
    """Cluster lookup with safe fallback for unknown names."""
    profile = lookup(name)
    return profile.cluster if profile is not None else "other"

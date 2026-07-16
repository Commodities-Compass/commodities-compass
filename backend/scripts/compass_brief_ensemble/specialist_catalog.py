"""Catalog of the Compass specialists with business-friendly labels.

The catalog is the single source of truth for the brief generator and any
downstream consumer that needs to look up a profile by its technical name.

Editorial rules (the brief is read aloud by NotebookLM, so any wording here
ends up in the daily podcast):

  * never name the model family (no "barrières techniques", no "GARCH", no
    "calibrated-TB", no "modèle entraîné"). Speak in business terms only :
    tendance, FX, climat, volatilité, macro.
  * never reveal training scope ("calibrée sur dix ans") nor architecture
    ("seul modèle du panel à raisonner sur trois semaines").
  * keep each description ≤2 sentences for podcast read-aloud.

Bilingual (EN/Ghana edition, US-4a): each profile carries a native-English
``label_en`` / ``description_en`` alongside the French pair. These are a
re-write, not a translation — British / West-African trader register, same
redaction rules. The brief generator picks the pair per output language via
``label_for`` / ``description_for``.

Internal R&D fields (cluster, code, horizon_days, bias) stay in the catalog
because they are useful for audit / dashboard / tests, but they are *not*
rendered into the brief.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ClusterName = Literal["winter", "spring"]
ThemeName = Literal["technique", "fx", "macro", "climat", "volatilité"]


@dataclass(frozen=True)
class SpecialistProfile:
    """Business-facing description of one specialist."""

    name: str
    """Technical ID written by cc-ensemble-compute on
    pl_specialist_prediction.specialist_name."""

    cluster: ClusterName
    """Internal R&D grouping. Not rendered in the brief."""

    code: str
    """Short R&D code (W1, S1...). Not rendered in the brief."""

    label: str
    """Business-friendly title shown in the brief and read aloud in the
    podcast (French edition)."""

    label_en: str
    """Native-English counterpart of ``label`` (EN/Ghana edition)."""

    description: str
    """1-2 sentences describing what the specialist watches and how it votes,
    no technical jargon, no training-scope hints. Read aloud in the podcast
    when this specialist is the headline lecture of the day (French edition)."""

    description_en: str
    """Native-English counterpart of ``description`` (EN/Ghana edition)."""

    theme: ThemeName
    """Business theme used to group specialists in editorial mode :
    `une lecture FX convergente`, `plusieurs lectures macro`, etc."""

    horizon_days: int
    """Internal field — not rendered in the brief."""

    bias: Literal["neutral", "bearish", "bullish"]
    """Internal field — used by the brief generator to pick the headline
    specialist whose architectural bias aligns with the daily decision. Not
    rendered in the brief itself."""

    def label_for(self, language: str) -> str:
        """Business title for the given output language (``fr`` default)."""
        return self.label_en if language == "en" else self.label

    def description_for(self, language: str) -> str:
        """Description for the given output language (``fr`` default)."""
        return self.description_en if language == "en" else self.description


# ───────────────────────────────────────────────────────────────────────────
# WINTER cluster
# ───────────────────────────────────────────────────────────────────────────
WINTER_PROFILES: tuple[SpecialistProfile, ...] = (
    SpecialistProfile(
        name="exp_optim_002",
        cluster="winter",
        code="W1",
        label="Lecteur de tendance — référence",
        label_en="Trend reader — benchmark",
        description=(
            "Lit la structure de prix du cocoa Londres pour repérer les "
            "retournements. C'est le pilier purement technique du signal."
        ),
        description_en=(
            "Reads the price structure of London cocoa to catch the turns. "
            "It's the purely technical backbone of the signal."
        ),
        theme="technique",
        horizon_days=6,
        bias="neutral",
    ),
    SpecialistProfile(
        name="exp_optim_005",
        cluster="winter",
        code="W2",
        label="Lecteur de tendance volatilité-conditionnel",
        label_en="Volatility-aware trend reader",
        description=(
            "Variante du lecteur de référence qui pondère son verdict selon "
            "le régime de volatilité ambiant. Sa voix porte davantage quand "
            "le marché s'agite."
        ),
        description_en=(
            "A variant of the benchmark reader that weights its verdict by "
            "the prevailing volatility regime. Its voice carries more weight "
            "when the market turns choppy."
        ),
        theme="volatilité",
        horizon_days=6,
        bias="neutral",
    ),
    SpecialistProfile(
        name="exp_optim_006",
        cluster="winter",
        code="W3",
        label="Spécialiste cycle long",
        label_en="Long-cycle specialist",
        description=(
            "Lit la structure de prix sur un horizon plus large que les "
            "autres lectures. Utile pour détecter les retournements lents "
            "que les approches courtes manquent."
        ),
        description_en=(
            "Reads price structure over a wider horizon than the other "
            "reads. Useful for catching the slow turns that shorter "
            "approaches miss."
        ),
        theme="technique",
        horizon_days=22,
        bias="neutral",
    ),
    SpecialistProfile(
        name="exp_optim_011",
        cluster="winter",
        code="W4",
        label="Stratège macro global",
        label_en="Global macro strategist",
        description=(
            "Croise les conditions climatiques globales et les mouvements "
            "de la livre face au dollar. Historiquement la lecture la plus "
            "régulière de l'équipe."
        ),
        description_en=(
            "Cross-reads global weather conditions against sterling's moves "
            "versus the dollar. Historically the steadiest read on the desk."
        ),
        theme="macro",
        horizon_days=6,
        bias="neutral",
    ),
    SpecialistProfile(
        name="xpol_W_TB_garch",
        cluster="winter",
        code="X1",
        label="Lecteur de tendance avec contrôle de volatilité",
        label_en="Trend reader with volatility control",
        description=(
            "Combine la lecture de tendance de référence et le filtre de "
            "volatilité. Quand les deux approches convergent, le signal "
            "est considéré comme doublement filtré."
        ),
        description_en=(
            "Combines the benchmark trend read with a volatility filter. "
            "When both approaches agree, the signal counts as doubly "
            "filtered."
        ),
        theme="volatilité",
        horizon_days=6,
        bias="neutral",
    ),
    SpecialistProfile(
        name="xpol_W_TB_macro",
        cluster="winter",
        code="X2",
        label="Lecteur de tendance contextualisé macro",
        label_en="Macro-contextualised trend reader",
        description=(
            "Lecture de tendance enrichie des conditions climatiques et "
            "FX. Tire son signal quand la toile macro renforce la dynamique "
            "purement technique."
        ),
        description_en=(
            "A trend read enriched with weather and FX conditions. It fires "
            "when the macro backdrop reinforces the purely technical "
            "momentum."
        ),
        theme="macro",
        horizon_days=6,
        bias="neutral",
    ),
)


# ───────────────────────────────────────────────────────────────────────────
# SPRING cluster
# ───────────────────────────────────────────────────────────────────────────
SPRING_PROFILES: tuple[SpecialistProfile, ...] = (
    SpecialistProfile(
        name="exp_optim_017_bear_4",
        cluster="spring",
        code="S1",
        label="Sentinelle baissière FX",
        label_en="Bearish FX sentinel",
        description=(
            "Suit les mouvements de change pour repérer les retournements "
            "baissiers. Vote rarement à l'achat — quand elle s'engage, c'est "
            "presque toujours pour couvrir."
        ),
        description_en=(
            "Tracks currency moves to spot bearish turns. It rarely votes to "
            "buy — when it commits, it's almost always to hedge."
        ),
        theme="fx",
        horizon_days=6,
        bias="bearish",
    ),
    SpecialistProfile(
        name="exp_optim_017_bear_8",
        cluster="spring",
        code="S2",
        label="Sentinelle baissière climat + FX",
        label_en="Bearish weather + FX sentinel",
        description=(
            "Variante de la sentinelle FX qui ajoute la lecture climatique. "
            "Plus prudente : elle ne s'engage que si pression FX et stress "
            "hydrique se cumulent."
        ),
        description_en=(
            "A variant of the FX sentinel that adds the weather read. More "
            "cautious: it only commits when currency pressure and water "
            "stress pile up together."
        ),
        theme="climat",
        horizon_days=6,
        bias="bearish",
    ),
    SpecialistProfile(
        name="exp_optim_017_bull_4",
        cluster="spring",
        code="S6",
        label="Stratège haussier FX",
        label_en="Bullish FX strategist",
        description=(
            "Détecte les phases de hausse soutenue, lit principalement la "
            "livre face au dollar. Vote rarement à la couverture."
        ),
        description_en=(
            "Spots sustained upswings, reading mainly sterling against the "
            "dollar. It rarely votes to hedge."
        ),
        theme="fx",
        horizon_days=6,
        bias="bullish",
    ),
    SpecialistProfile(
        name="exp_optim_017_bull_5",
        cluster="spring",
        code="S3",
        label="Stratège haussier baseline",
        label_en="Baseline bullish strategist",
        description=(
            "Approche statistique pure, fortement biaisée à l'achat. Vote "
            "tranché — peu de zones grises, soit à l'achat soit en retrait."
        ),
        description_en=(
            "A pure statistical approach with a strong buy bias. It votes "
            "decisively — few grey zones, either buying or standing aside."
        ),
        theme="technique",
        horizon_days=6,
        bias="bullish",
    ),
    SpecialistProfile(
        name="exp_optim_017_bull_7",
        cluster="spring",
        code="S4",
        label="Stratège haussier FX renforcé",
        label_en="Reinforced bullish FX strategist",
        description=(
            "Variante du stratège haussier FX avec un biais encore plus "
            "marqué. Voix la plus offensive quand la livre se renforce."
        ),
        description_en=(
            "A variant of the bullish FX strategist with an even sharper "
            "bias. The most aggressive voice when sterling strengthens."
        ),
        theme="fx",
        horizon_days=6,
        bias="bullish",
    ),
    SpecialistProfile(
        name="exp_optim_017_bull_8",
        cluster="spring",
        code="S5",
        label="Stratège haussier multi-facteur",
        label_en="Multi-factor bullish strategist",
        description=(
            "Utilise la palette de lectures la plus large — une cinquantaine "
            "d'angles techniques et fondamentaux. Sa voix compte "
            "particulièrement quand le marché présente des signaux mixtes."
        ),
        description_en=(
            "Draws on the widest palette of reads — some fifty technical and "
            "fundamental angles. Its voice matters most when the market "
            "throws up mixed signals."
        ),
        theme="macro",
        horizon_days=6,
        bias="bullish",
    ),
    SpecialistProfile(
        name="xpol_S_bull_garch_fx",
        cluster="spring",
        code="X3",
        label="Stratège haussier FX avec contrôle de volatilité",
        label_en="Bullish FX strategist with volatility control",
        description=(
            "Combine biais haussier, filtre de volatilité et lecture FX. "
            "Tire son signal sur les phases de hausse soutenue où la "
            "volatilité reste maîtrisée."
        ),
        description_en=(
            "Combines a bullish bias, a volatility filter and the FX read. "
            "It fires on sustained upswings where volatility stays "
            "contained."
        ),
        theme="fx",
        horizon_days=6,
        bias="bullish",
    ),
    SpecialistProfile(
        name="xpol_S_bear_garch_macro",
        cluster="spring",
        code="X4",
        label="Sentinelle baissière complète",
        label_en="Full bearish sentinel",
        description=(
            "Combine toutes les défenses : biais baissier, filtre de "
            "volatilité, FX et climat. La voix la plus prudente — vote à la "
            "couverture seulement quand tous les facteurs s'alignent."
        ),
        description_en=(
            "Combines every defence: a bearish bias, a volatility filter, FX "
            "and weather. The most cautious voice — it votes to hedge only "
            "when every factor lines up."
        ),
        theme="macro",
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


def theme_of(name: str) -> str:
    """Business theme lookup with safe fallback for unknown names."""
    profile = lookup(name)
    return profile.theme if profile is not None else "macro"

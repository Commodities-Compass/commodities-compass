"""Weather enrichment service.

Fetches seasonal scores from pl_seasonal_score and enriches the weather
response with campaign health, season statuses, and location diagnostics.
"""

import logging
import re
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import PlSeasonalScore
from app.schemas.dashboard import HarmattanStatus, LocationDiagnostic, SeasonStatus

logger = logging.getLogger(__name__)

# Location → country mapping (matches meteo agent config)
LOCATION_COUNTRIES: dict[str, str] = {
    "Daloa": "CIV",
    "San-Pédro": "CIV",
    "Soubré": "CIV",
    "Kumasi": "GHA",
    "Takoradi": "GHA",
    "Goaso": "GHA",
}

# Season display labels and canonical month ranges (Oct→Sep campaign)
SEASON_META: dict[str, dict[str, str]] = {
    "saison_seche": {"label": "Saison Sèche", "months": "Déc-Mars"},
    "transition_pluies": {"label": "Transition Pluies", "months": "Avril"},
    "grande_saison_pluies": {"label": "Grande Saison Pluies", "months": "Mai-Juil"},
    "petite_saison_seche": {"label": "Petite Saison Sèche", "months": "Août"},
    "petite_saison_pluies": {"label": "Petite Saison Pluies", "months": "Sep-Nov"},
}

# Canonical season order within a campaign (Oct→Sep)
SEASON_ORDER = [
    "petite_saison_pluies",
    "saison_seche",
    "transition_pluies",
    "grande_saison_pluies",
    "petite_saison_seche",
]

# Month → season mapping for determining current season
_MONTH_TO_SEASON: dict[int, str] = {
    1: "saison_seche",
    2: "saison_seche",
    3: "saison_seche",
    4: "transition_pluies",
    5: "grande_saison_pluies",
    6: "grande_saison_pluies",
    7: "grande_saison_pluies",
    8: "petite_saison_seche",
    9: "petite_saison_pluies",
    10: "petite_saison_pluies",
    11: "petite_saison_pluies",
    12: "saison_seche",
}


def get_current_campaign(reference_date: date) -> str:
    """Determine campaign identifier for a given date.

    Campaign runs Oct Y → Sep Y+1. E.g. any date from Oct 2025 to Sep 2026
    belongs to campaign "2025-2026".
    """
    if reference_date.month >= 10:
        return f"{reference_date.year}-{reference_date.year + 1}"
    return f"{reference_date.year - 1}-{reference_date.year}"


def get_current_season(reference_date: date) -> str:
    """Return the season_name for the given date's month."""
    return _MONTH_TO_SEASON[reference_date.month]


async def get_seasonal_scores(db: AsyncSession, campaign: str) -> list[PlSeasonalScore]:
    """Fetch all seasonal scores for a campaign."""
    query = (
        select(PlSeasonalScore)
        .where(PlSeasonalScore.campaign == campaign)
        .order_by(PlSeasonalScore.start_date, PlSeasonalScore.location_name)
    )
    result = await db.execute(query)
    return list(result.scalars().all())


def compute_campaign_health(scores: list[PlSeasonalScore]) -> Optional[float]:
    """Average score across all location-season rows. None if no data."""
    if not scores:
        return None
    total = sum(float(s.score) for s in scores)
    return round(total / len(scores), 1)


def build_season_statuses(
    scores: list[PlSeasonalScore], reference_date: date
) -> list[SeasonStatus]:
    """Build status for each of the 5 canonical seasons."""
    current_season = get_current_season(reference_date)

    # Group scores by season → compute average score per season
    season_scores: dict[str, list[float]] = {}
    season_months: dict[str, str] = {}
    for s in scores:
        season_scores.setdefault(s.season_name, []).append(float(s.score))
        season_months[s.season_name] = s.months_covered

    # Determine order-based status: seasons before current = completed,
    # current = in_progress, after = upcoming
    current_idx = (
        SEASON_ORDER.index(current_season) if current_season in SEASON_ORDER else 0
    )

    statuses: list[SeasonStatus] = []
    for i, season_name in enumerate(SEASON_ORDER):
        meta = SEASON_META.get(season_name, {"label": season_name, "months": ""})
        avg_score = None
        score_list = season_scores.get(season_name, [])
        if score_list:
            avg_score = round(sum(score_list) / len(score_list), 1)

        if i < current_idx:
            status = "completed"
        elif i == current_idx:
            status = "in_progress"
        else:
            status = "upcoming"

        statuses.append(
            SeasonStatus(
                season_name=season_name,
                label=meta["label"],
                months_covered=season_months.get(season_name, meta["months"]),
                score=avg_score,
                status=status,
            )
        )

    return statuses


def build_location_diagnostics(
    scores: list[PlSeasonalScore],
) -> list[LocationDiagnostic]:
    """Build per-location diagnostics from seasonal scores.

    Score thresholds (on 1-5 scale):
      >= 3.5 → normal
      2.5-3.4 → degraded
      < 2.5 → stress
    """
    location_scores: dict[str, list[float]] = {}
    location_harmattan: dict[str, int] = {}
    for s in scores:
        location_scores.setdefault(s.location_name, []).append(float(s.score))
        if s.season_name == "saison_seche" and s.harmattan_days is not None:
            location_harmattan[s.location_name] = int(s.harmattan_days)

    diagnostics: list[LocationDiagnostic] = []
    for loc_name in LOCATION_COUNTRIES:
        score_list = location_scores.get(loc_name, [])
        avg_score = round(sum(score_list) / len(score_list), 1) if score_list else None

        if avg_score is None:
            status = "normal"
        elif avg_score >= 3.5:
            status = "normal"
        elif avg_score >= 2.5:
            status = "degraded"
        else:
            status = "stress"

        diagnostics.append(
            LocationDiagnostic(
                location_name=loc_name,
                country=LOCATION_COUNTRIES[loc_name],
                score=avg_score,
                status=status,
                harmattan_days=location_harmattan.get(loc_name),
            )
        )

    return diagnostics


_HARMATTAN_SEASON_MONTHS = (11, 12, 1, 2, 3)
_HARMATTAN_IMPACT_DAYS = 24


async def get_harmattan_status(
    db: AsyncSession, campaign: str, reference_date: date
) -> HarmattanStatus:
    """Compute Harmattan index from pl_seasonal_score for the current campaign."""
    query = await db.execute(
        select(
            PlSeasonalScore.harmattan_days,
        ).where(
            PlSeasonalScore.campaign == campaign,
            PlSeasonalScore.season_name == "saison_seche",
            PlSeasonalScore.harmattan_days.is_not(None),
        )
    )
    rows = query.fetchall()
    total_days = sum(int(r[0]) for r in rows) if rows else 0
    in_season = reference_date.month in _HARMATTAN_SEASON_MONTHS

    return HarmattanStatus(
        days=total_days,
        threshold=_HARMATTAN_IMPACT_DAYS,
        risk=total_days > _HARMATTAN_IMPACT_DAYS,
        in_season=in_season,
    )


# Fuzzy-match LLM location names to canonical names
_LOCATION_ALIASES: dict[str, str] = {
    "san-pedro": "San-Pédro",
    "san-pédro": "San-Pédro",
    "san pedro": "San-Pédro",
    "soubre": "Soubré",
    "soubré": "Soubré",
    "daloa": "Daloa",
    "kumasi": "Kumasi",
    "takoradi": "Takoradi",
    "goaso": "Goaso",
}


def _normalize_location(name: str) -> str | None:
    """Resolve an LLM location name to the canonical form."""
    lower = name.strip().lower()
    if lower in _LOCATION_ALIASES:
        return _LOCATION_ALIASES[lower]
    # Direct match (already canonical)
    if name.strip() in LOCATION_COUNTRIES:
        return name.strip()
    return None


def build_daily_diagnostics(
    diagnostics_json: dict | None,
) -> list[LocationDiagnostic]:
    """Convert LLM diagnostics dict to LocationDiagnostic list.

    Input: {"Daloa": "normal", "San-Pédro": "degraded", ...}
    Falls back to "normal" for missing locations.
    """
    if not diagnostics_json or not isinstance(diagnostics_json, dict):
        return []

    resolved: dict[str, str] = {}
    for raw_name, status in diagnostics_json.items():
        canonical = _normalize_location(raw_name)
        if canonical and status in ("normal", "degraded", "stress"):
            resolved[canonical] = status

    return [
        LocationDiagnostic(
            location_name=loc,
            country=LOCATION_COUNTRIES[loc],
            score=None,
            status=resolved.get(loc, "normal"),
            harmattan_days=None,
        )
        for loc in LOCATION_COUNTRIES
    ]


def parse_impact_score(impact_text: str) -> Optional[int]:
    """Extract numeric impact score from text like '4/10; justification...'."""
    match = re.match(r"(\d{1,2})/10", impact_text.strip())
    if match:
        val = int(match.group(1))
        return val if 1 <= val <= 10 else None
    return None

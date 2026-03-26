"""Seasonal memory — cumulative campaign scores for LLM context.

Computes a score (1-5) per season × location from Open-Meteo historical data.
Stored in pl_seasonal_score, injected into the meteo agent prompt so the LLM
can contextualize daily weather against the campaign's cumulative history.

Scoring is deterministic (no LLM) — based on deviation from seasonal norms.

Campaign year: Oct Y → Sep Y+1 (e.g., "2025-2026" = Oct 2025 → Sep 2026).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.meteo_agent.config import (
    HTTP_TIMEOUT,
    LOCATIONS,
    SEASONAL_PROFILES,
    SeasonalProfile,
)

logger = logging.getLogger(__name__)

OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"

# Approximate 30-day precipitation norms (mm) by season for the cocoa belt.
# Used to compute deviation scores. To be refined with actual historical data.
_PRECIP_30D_NORMS: dict[str, tuple[float, float]] = {
    "saison_seche": (10.0, 60.0),
    "transition_pluies": (60.0, 150.0),
    "grande_saison_pluies": (150.0, 350.0),
    "petite_saison_seche": (40.0, 120.0),
    "petite_saison_pluies": (100.0, 250.0),
}


@dataclass(frozen=True)
class SeasonDateRange:
    """Resolved date range for a season within a specific campaign."""

    season: SeasonalProfile
    campaign: str
    start_date: date
    end_date: date
    months_covered: str


@dataclass(frozen=True)
class LocationSeasonStats:
    """Raw stats for one location over one season."""

    location_name: str
    country: str
    total_precip_mm: float
    total_et0_mm: float
    cumulative_balance_mm: float
    days_rain: int
    days_stress_temp: int
    avg_tmax: float
    total_days: int


def get_campaign(target_date: date) -> str:
    """Get campaign string for a date. Campaign runs Oct→Sep."""
    if target_date.month >= 10:
        return f"{target_date.year}-{target_date.year + 1}"
    return f"{target_date.year - 1}-{target_date.year}"


def get_completed_seasons(target_date: date) -> list[SeasonDateRange]:
    """Get all completed seasons for the current campaign up to target_date."""
    campaign = get_campaign(target_date)
    start_year = int(campaign.split("-")[0])

    seasons: list[SeasonDateRange] = []
    for profile in SEASONAL_PROFILES:
        season_range = _resolve_season_dates(profile, start_year)
        if season_range is None:
            continue
        # Only include fully completed seasons, or the current in-progress one
        if season_range.end_date <= target_date:
            seasons.append(season_range)
        elif season_range.start_date <= target_date:
            # Current season — compute up to yesterday
            seasons.append(
                SeasonDateRange(
                    season=profile,
                    campaign=campaign,
                    start_date=season_range.start_date,
                    end_date=target_date - timedelta(days=1),
                    months_covered=season_range.months_covered + " (en cours)",
                )
            )
    return seasons


def _resolve_season_dates(
    profile: SeasonalProfile, campaign_start_year: int
) -> SeasonDateRange | None:
    """Convert a season profile + campaign year into concrete date range."""
    months = sorted(profile.months)
    if not months:
        return None

    # Determine year for each month
    # Campaign starts in October: months 10-12 are in start_year,
    # months 1-9 are in start_year + 1
    first_month = months[0]
    last_month = months[-1]

    if first_month >= 10:
        start_year = campaign_start_year
    else:
        start_year = campaign_start_year + 1

    if last_month >= 10:
        end_year = campaign_start_year
    else:
        end_year = campaign_start_year + 1

    start_date = date(start_year, first_month, 1)

    # End date = last day of last month
    if last_month == 12:
        end_date = date(end_year, 12, 31)
    else:
        end_date = date(end_year, last_month + 1, 1) - timedelta(days=1)

    month_names = [date(2000, m, 1).strftime("%b") for m in months]
    months_str = f"{month_names[0]}-{month_names[-1]} {start_year}"
    campaign = f"{campaign_start_year}-{campaign_start_year + 1}"

    return SeasonDateRange(
        season=profile,
        campaign=campaign,
        start_date=start_date,
        end_date=end_date,
        months_covered=months_str,
    )


def fetch_season_weather(start_date: date, end_date: date) -> list[dict]:
    """Fetch daily precip, ET0, Tmax from Open-Meteo for all locations."""
    latitudes = ",".join(str(loc.latitude) for loc in LOCATIONS)
    longitudes = ",".join(str(loc.longitude) for loc in LOCATIONS)

    # Use archive API for past data, forecast API for recent/current
    today = date.today()
    if end_date < today - timedelta(days=5):
        base_url = OPEN_METEO_ARCHIVE
    else:
        base_url = OPEN_METEO_FORECAST

    url = (
        f"{base_url}"
        f"?latitude={latitudes}"
        f"&longitude={longitudes}"
        f"&daily=precipitation_sum,et0_fao_evapotranspiration,temperature_2m_max"
        f"&start_date={start_date.isoformat()}"
        f"&end_date={end_date.isoformat()}"
        f"&timezone=auto"
    )

    logger.info(
        "Fetching weather %s → %s from %s",
        start_date,
        end_date,
        "archive" if "archive" in base_url else "forecast",
    )

    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        response = client.get(url)
        response.raise_for_status()

    data = response.json()
    return data if isinstance(data, list) else [data]


def compute_season_stats(
    location_data: dict,
    loc_name: str,
    loc_country: str,
    tmax_threshold: float,
) -> LocationSeasonStats:
    """Compute cumulative stats for one location over a season."""
    daily = location_data.get("daily", {})
    precip = [p or 0.0 for p in daily.get("precipitation_sum", [])]
    et0 = [e or 0.0 for e in daily.get("et0_fao_evapotranspiration", [])]
    tmax = [t or 0.0 for t in daily.get("temperature_2m_max", [])]

    n = min(len(precip), len(et0), len(tmax))
    if n == 0:
        return LocationSeasonStats(
            location_name=loc_name,
            country=loc_country,
            total_precip_mm=0,
            total_et0_mm=0,
            cumulative_balance_mm=0,
            days_rain=0,
            days_stress_temp=0,
            avg_tmax=0,
            total_days=0,
        )

    return LocationSeasonStats(
        location_name=loc_name,
        country=loc_country,
        total_precip_mm=round(sum(precip[:n]), 1),
        total_et0_mm=round(sum(et0[:n]), 1),
        cumulative_balance_mm=round(sum(precip[:n]) - sum(et0[:n]), 1),
        days_rain=sum(1 for p in precip[:n] if p > 0.5),
        days_stress_temp=sum(1 for t in tmax[:n] if t > tmax_threshold),
        avg_tmax=round(sum(tmax[:n]) / n, 1),
        total_days=n,
    )


def compute_score(
    stats: LocationSeasonStats,
    season: SeasonalProfile,
) -> float:
    """Deterministic score (1.0-5.0) based on deviation from seasonal norms.

    Starts at 5.0 (perfect) and applies penalties.
    """
    score = 5.0
    norm_range = _PRECIP_30D_NORMS.get(season.name, (0, 999))

    # Scale norms to actual season length (norms are per 30 days)
    scale = stats.total_days / 30.0 if stats.total_days > 0 else 1.0
    norm_low = norm_range[0] * scale
    norm_high = norm_range[1] * scale

    # Precipitation penalty
    if norm_low > 0:
        precip_ratio = stats.total_precip_mm / norm_low
    else:
        precip_ratio = 1.0

    if precip_ratio < 0.5:
        score -= 2.0  # severe deficit
    elif precip_ratio < 0.75:
        score -= 1.0  # moderate deficit
    elif stats.total_precip_mm > norm_high * 1.5:
        score -= 2.0  # severe excess
    elif stats.total_precip_mm > norm_high:
        score -= 1.0  # moderate excess

    # Temperature stress penalty
    if stats.total_days > 0:
        stress_ratio = stats.days_stress_temp / stats.total_days
        if stress_ratio > 0.5:
            score -= 2.0
        elif stress_ratio > 0.3:
            score -= 1.0
        elif stress_ratio > 0.15:
            score -= 0.5

    # Water balance bonus/penalty
    if stats.total_days > 0:
        avg_daily_balance = stats.cumulative_balance_mm / stats.total_days
        if avg_daily_balance < -5.0:
            score -= 0.5  # persistent deep deficit

    return max(1.0, min(5.0, round(score * 2) / 2))  # clamp + round to 0.5


def write_seasonal_scores(
    session: Session,
    season_range: SeasonDateRange,
    stats_list: list[LocationSeasonStats],
    scores: list[float],
) -> int:
    """Upsert seasonal scores to pl_seasonal_score."""
    rows_written = 0
    for stats, score_val in zip(stats_list, scores):
        session.execute(
            text("""
                INSERT INTO pl_seasonal_score
                    (id, campaign, season_name, location_name, months_covered,
                     start_date, end_date,
                     total_precip_mm, total_et0_mm, cumulative_balance_mm,
                     days_rain, days_stress_temp, avg_tmax, score)
                VALUES
                    (:id, :campaign, :season_name, :location_name, :months_covered,
                     :start_date, :end_date,
                     :total_precip_mm, :total_et0_mm, :cumulative_balance_mm,
                     :days_rain, :days_stress_temp, :avg_tmax, :score)
                ON CONFLICT ON CONSTRAINT uq_seasonal_score
                DO UPDATE SET
                    months_covered = EXCLUDED.months_covered,
                    start_date = EXCLUDED.start_date,
                    end_date = EXCLUDED.end_date,
                    total_precip_mm = EXCLUDED.total_precip_mm,
                    total_et0_mm = EXCLUDED.total_et0_mm,
                    cumulative_balance_mm = EXCLUDED.cumulative_balance_mm,
                    days_rain = EXCLUDED.days_rain,
                    days_stress_temp = EXCLUDED.days_stress_temp,
                    avg_tmax = EXCLUDED.avg_tmax,
                    score = EXCLUDED.score,
                    computed_at = NOW()
            """),
            {
                "id": uuid.uuid4(),
                "campaign": season_range.campaign,
                "season_name": season_range.season.name,
                "location_name": stats.location_name,
                "months_covered": season_range.months_covered,
                "start_date": season_range.start_date,
                "end_date": season_range.end_date,
                "total_precip_mm": stats.total_precip_mm,
                "total_et0_mm": stats.total_et0_mm,
                "cumulative_balance_mm": stats.cumulative_balance_mm,
                "days_rain": stats.days_rain,
                "days_stress_temp": stats.days_stress_temp,
                "avg_tmax": stats.avg_tmax,
                "score": score_val,
            },
        )
        rows_written += 1
    session.commit()
    return rows_written


def compute_and_store_season(
    session: Session,
    season_range: SeasonDateRange,
) -> list[tuple[str, float]]:
    """Fetch weather, compute scores, store in DB for one season.

    Returns list of (location_name, score) tuples.
    """
    raw_data = fetch_season_weather(season_range.start_date, season_range.end_date)

    stats_list: list[LocationSeasonStats] = []
    scores: list[float] = []

    for i, loc in enumerate(LOCATIONS):
        if i >= len(raw_data):
            break
        stats = compute_season_stats(
            raw_data[i],
            loc.name,
            loc.country,
            season_range.season.tmax_stress_threshold,
        )
        score_val = compute_score(stats, season_range.season)
        stats_list.append(stats)
        scores.append(score_val)
        logger.info(
            "  %s: precip=%.0fmm, ET0=%.0fmm, balance=%+.0fmm, "
            "rain=%dd, stress_temp=%dd, score=%.1f/5",
            loc.name,
            stats.total_precip_mm,
            stats.total_et0_mm,
            stats.cumulative_balance_mm,
            stats.days_rain,
            stats.days_stress_temp,
            score_val,
        )

    written = write_seasonal_scores(session, season_range, stats_list, scores)
    logger.info("Season %s: %d scores written", season_range.season.name, written)
    return list(zip([s.location_name for s in stats_list], scores))


def bootstrap_campaign(session: Session, target_date: date | None = None) -> None:
    """Backfill all seasons for the current campaign from Open-Meteo history.

    Safe to re-run — uses upsert.
    """
    if target_date is None:
        target_date = date.today()

    campaign = get_campaign(target_date)
    logger.info("Bootstrapping campaign %s (up to %s)...", campaign, target_date)

    seasons = get_completed_seasons(target_date)
    for season_range in seasons:
        logger.info(
            "Computing %s (%s → %s)...",
            season_range.season.name,
            season_range.start_date,
            season_range.end_date,
        )
        compute_and_store_season(session, season_range)

    logger.info("Bootstrap complete for campaign %s", campaign)


def build_campaign_memory(session: Session, target_date: date | None = None) -> str:
    """Build the campaign memory block for the meteo agent prompt.

    Reads pl_seasonal_score for the current campaign and formats
    a structured summary. Returns empty string if no data.
    """
    if target_date is None:
        target_date = date.today()

    campaign = get_campaign(target_date)

    result = session.execute(
        text("""
            SELECT season_name, location_name, months_covered,
                   total_precip_mm, total_et0_mm, cumulative_balance_mm,
                   days_stress_temp, score
            FROM pl_seasonal_score
            WHERE campaign = :campaign
            ORDER BY start_date, location_name
        """),
        {"campaign": campaign},
    )
    rows = result.fetchall()
    if not rows:
        return ""

    # Group by season
    seasons: dict[str, list] = {}
    for row in rows:
        season_name = row[0]
        if season_name not in seasons:
            seasons[season_name] = []
        seasons[season_name].append(row)

    # Get norm ranges for context
    lines = [f"HISTORIQUE CAMPAGNE {campaign} :"]

    for season_name, season_rows in seasons.items():
        months = season_rows[0][2]  # months_covered from first location
        avg_score = sum(float(r[7]) for r in season_rows) / len(season_rows)
        avg_precip = sum(float(r[3] or 0) for r in season_rows) / len(season_rows)
        avg_balance = sum(float(r[5] or 0) for r in season_rows) / len(season_rows)
        total_stress = sum(int(r[6] or 0) for r in season_rows)

        norm = _PRECIP_30D_NORMS.get(season_name, (0, 999))
        status = "en cours" if "(en cours)" in months else "terminée"

        # Find worst and best locations
        sorted_locs = sorted(season_rows, key=lambda r: float(r[7]))
        worst = f"{sorted_locs[0][1]} ({float(sorted_locs[0][7]):.1f}/5)"
        best = f"{sorted_locs[-1][1]} ({float(sorted_locs[-1][7]):.1f}/5)"

        display_name = season_name.replace("_", " ").title()
        lines.append(
            f"• {display_name} ({months}) : {avg_score:.1f}/5 — "
            f"Précip moy {avg_precip:.0f}mm (norme {norm[0]}-{norm[1]}mm/30j), "
            f"bilan hydrique moy {avg_balance:+.0f}mm, "
            f"{total_stress}j stress thermique total. "
            f"Meilleure: {best}, pire: {worst}. [{status}]"
        )

    # Summary line
    all_scores = [float(r[7]) for r in rows]
    campaign_avg = sum(all_scores) / len(all_scores)
    if campaign_avg >= 4.0:
        health = "Réserves hydriques bien constituées. Stress ponctuel absorbable."
    elif campaign_avg >= 3.0:
        health = "Campagne correcte. Vigilance sur les localités les plus faibles."
    elif campaign_avg >= 2.0:
        health = "Campagne dégradée. Stress cumulé significatif, sensibilité élevée."
    else:
        health = "Campagne critique. Déficits cumulés importants, tout stress additionnel est amplifié."

    lines.append(f"→ Santé campagne : {campaign_avg:.1f}/5 — {health}")

    return "\n".join(lines)

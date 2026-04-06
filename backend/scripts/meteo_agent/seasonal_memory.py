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
    HARMATTAN_IMPACT_DAYS,
    HARMATTAN_RH_THRESHOLD,
    HARMATTAN_SEASON_MONTHS,
    HARMATTAN_WIND_DIR_MAX,
    HARMATTAN_WIND_DIR_MIN,
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
        elif season_range.start_date < target_date:
            # Current season — compute up to yesterday (skip if no full day yet)
            effective_end = target_date - timedelta(days=1)
            if effective_end >= season_range.start_date:
                seasons.append(
                    SeasonDateRange(
                        season=profile,
                        campaign=campaign,
                        start_date=season_range.start_date,
                        end_date=effective_end,
                        months_covered=season_range.months_covered + " (en cours)",
                    )
                )
    return seasons


def _resolve_season_dates(
    profile: SeasonalProfile, campaign_start_year: int
) -> SeasonDateRange | None:
    """Convert a season profile + campaign year into concrete date range.

    Campaign runs Oct→Sep. Months 10-12 belong to campaign_start_year,
    months 1-9 belong to campaign_start_year + 1.
    Saison sèche (12, 1, 2, 3) spans two calendar years.
    """
    if not profile.months:
        return None

    # Assign each month to its calendar year within the campaign.
    # Campaign runs Oct Y → Sep Y+1.
    # Base rule: months 10-12 → start_year, months 1-9 → start_year+1
    # Special case: petite_saison_pluies (9,10,11) — all pre-campaign,
    # so all months belong to start_year.
    has_oct_plus = any(m >= 10 for m in profile.months)
    has_pre_oct = any(1 <= m <= 9 for m in profile.months)
    # If season has months on both sides of Oct AND the low months are
    # close to Oct (>=9), it's a pre-campaign season — all in start_year.
    # If the low months are <=3, it's a cross-year season (saison sèche).
    pre_campaign_season = (
        has_oct_plus and has_pre_oct and min(m for m in profile.months if m < 10) >= 9
    )

    month_years: list[tuple[int, int]] = []
    for m in profile.months:
        if pre_campaign_season:
            year = campaign_start_year
        elif m >= 10:
            year = campaign_start_year
        else:
            year = campaign_start_year + 1
        month_years.append((m, year))

    # Sort by (year, month) to get chronological order
    month_years.sort(key=lambda my: (my[1], my[0]))

    first_month, first_year = month_years[0]
    last_month, last_year = month_years[-1]

    start_date = date(first_year, first_month, 1)
    if last_month == 12:
        end_date = date(last_year, 12, 31)
    else:
        end_date = date(last_year, last_month + 1, 1) - timedelta(days=1)

    month_names = [date(2000, m, 1).strftime("%b") for m in profile.months]
    months_str = f"{month_names[0]}-{month_names[-1]} {first_year}"
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

    # Archive API covers historical data (up to ~5 days ago).
    # Forecast API only covers ~2 weeks back. For seasonal data that spans
    # months, always use archive and cap end_date to 5 days ago.
    today = date.today()
    capped_end = min(end_date, today - timedelta(days=5))
    if capped_end < start_date:
        # Season hasn't started long enough ago — use forecast for short window
        base_url = OPEN_METEO_FORECAST
        capped_end = end_date
    else:
        base_url = OPEN_METEO_ARCHIVE
        end_date = capped_end

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


def fetch_harmattan_weather(start_date: date, end_date: date) -> list[dict]:
    """Fetch daily wind direction + hourly RH from Open-Meteo for Harmattan detection.

    Always uses archive API since Harmattan season is Nov-Mar (historical).
    Fetches for all locations in a single request.
    """
    latitudes = ",".join(str(loc.latitude) for loc in LOCATIONS)
    longitudes = ",".join(str(loc.longitude) for loc in LOCATIONS)

    today = date.today()
    capped_end = min(end_date, today - timedelta(days=5))
    if capped_end < start_date:
        capped_end = min(end_date, today - timedelta(days=1))

    url = (
        f"{OPEN_METEO_ARCHIVE}"
        f"?latitude={latitudes}"
        f"&longitude={longitudes}"
        f"&daily=winddirection_10m_dominant"
        f"&hourly=relative_humidity_2m"
        f"&start_date={start_date.isoformat()}"
        f"&end_date={capped_end.isoformat()}"
        f"&timezone=auto"
    )

    logger.info("Fetching Harmattan data %s → %s", start_date, capped_end)
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        response = client.get(url)
        response.raise_for_status()

    data = response.json()
    return data if isinstance(data, list) else [data]


def _is_harmattan_direction(wind_dir: float) -> bool:
    """True if wind direction is in the NE/N quadrant (315°-360° or 0°-90°)."""
    return wind_dir >= HARMATTAN_WIND_DIR_MIN or wind_dir <= HARMATTAN_WIND_DIR_MAX


def compute_harmattan_days(
    location_data: dict,
    start_date: date,
) -> int:
    """Count cumulative Harmattan days for one location.

    A Harmattan day requires:
    - Daily dominant wind direction in NE/N quadrant (315°-360° or 0°-90°)
    - Daily minimum RH < HARMATTAN_RH_THRESHOLD (55%)
    - Date within Nov-Mar window

    Returns cumulative count of qualifying days.
    """
    daily = location_data.get("daily", {})
    hourly = location_data.get("hourly", {})

    wind_dirs = daily.get("winddirection_10m_dominant", [])
    rh_hourly = hourly.get("relative_humidity_2m", [])
    time_daily = daily.get("time", [])

    if not wind_dirs or not rh_hourly:
        return 0

    # Compute daily min RH from hourly data (24 values per day)
    n_days = len(wind_dirs)
    daily_rh_min: list[float] = []
    for day_idx in range(n_days):
        start_h = day_idx * 24
        end_h = start_h + 24
        day_rh = [v for v in rh_hourly[start_h:end_h] if v is not None]
        daily_rh_min.append(min(day_rh) if day_rh else 100.0)

    harmattan_count = 0
    for i, (wind_dir, rh_min) in enumerate(zip(wind_dirs, daily_rh_min)):
        if wind_dir is None:
            continue
        # Check date is in Harmattan season
        if i < len(time_daily):
            try:
                day_date = date.fromisoformat(time_daily[i])
                if day_date.month not in HARMATTAN_SEASON_MONTHS:
                    continue
            except (ValueError, TypeError):
                pass
        if _is_harmattan_direction(float(wind_dir)) and rh_min < HARMATTAN_RH_THRESHOLD:
            harmattan_count += 1

    return harmattan_count


def get_campaign_harmattan_days(session: Session, campaign: str) -> int:
    """Sum harmattan_days across all saison_seche rows for the campaign.

    Returns 0 if no data (before first bootstrap or outside season).
    """
    result = session.execute(
        text("""
            SELECT COALESCE(SUM(harmattan_days), 0)
            FROM pl_seasonal_score
            WHERE campaign = :campaign
              AND season_name = 'saison_seche'
              AND harmattan_days IS NOT NULL
        """),
        {"campaign": campaign},
    )
    row = result.fetchone()
    return int(row[0]) if row else 0


def build_harmattan_context(harmattan_days: int, current_month: int) -> str:
    """Build the Harmattan block for the LLM prompt.

    Three states:
    - Hors saison (Apr-Oct): empty string — don't pollute the prompt
    - En saison, sous seuil: informational note
    - Seuil franchi (>24j): quality risk warning
    """
    if current_month not in HARMATTAN_SEASON_MONTHS:
        return ""

    if harmattan_days > HARMATTAN_IMPACT_DAYS:
        return (
            f"\nHARMATTAN — {harmattan_days} jours cumulés depuis nov. 1 "
            f"(seuil critique : {HARMATTAN_IMPACT_DAYS}j) : "
            "⚠ RISQUE QUALITÉ confirmé — conditions propices aux petites fèves. "
            "Mentionner dans le texte et les mots-clés."
        )
    return (
        f"\nHARMATTAN — {harmattan_days}j/{HARMATTAN_IMPACT_DAYS}j cumulés depuis nov. 1 "
        "(sous le seuil critique — surveiller)."
    )


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
    harmattan_days_per_location: list[int] | None = None,
) -> int:
    """Upsert seasonal scores to pl_seasonal_score."""
    rows_written = 0
    for i, (stats, score_val) in enumerate(zip(stats_list, scores)):
        harmattan = (
            harmattan_days_per_location[i]
            if harmattan_days_per_location and i < len(harmattan_days_per_location)
            else None
        )
        session.execute(
            text("""
                INSERT INTO pl_seasonal_score
                    (id, campaign, season_name, location_name, months_covered,
                     start_date, end_date,
                     total_precip_mm, total_et0_mm, cumulative_balance_mm,
                     days_rain, days_stress_temp, avg_tmax, harmattan_days, score)
                VALUES
                    (:id, :campaign, :season_name, :location_name, :months_covered,
                     :start_date, :end_date,
                     :total_precip_mm, :total_et0_mm, :cumulative_balance_mm,
                     :days_rain, :days_stress_temp, :avg_tmax, :harmattan_days, :score)
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
                    harmattan_days = EXCLUDED.harmattan_days,
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
                "harmattan_days": harmattan,
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

    # Fetch Harmattan data only for saison_seche (Nov-Mar)
    harmattan_raw: list[dict] = []
    if season_range.season.name == "saison_seche":
        try:
            harmattan_raw = fetch_harmattan_weather(
                season_range.start_date, season_range.end_date
            )
        except Exception as e:
            logger.warning("Harmattan fetch failed (non-blocking): %s", e)

    stats_list: list[LocationSeasonStats] = []
    scores: list[float] = []
    harmattan_days_per_location: list[int] = []

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

        # Compute Harmattan days if data available
        h_days = None
        if harmattan_raw and i < len(harmattan_raw):
            h_days = compute_harmattan_days(harmattan_raw[i], season_range.start_date)
            harmattan_days_per_location.append(h_days)

        logger.info(
            "  %s: precip=%.0fmm, ET0=%.0fmm, balance=%+.0fmm, "
            "rain=%dd, stress_temp=%dd%s, score=%.1f/5",
            loc.name,
            stats.total_precip_mm,
            stats.total_et0_mm,
            stats.cumulative_balance_mm,
            stats.days_rain,
            stats.days_stress_temp,
            f", harmattan={h_days}d" if h_days is not None else "",
            score_val,
        )

    written = write_seasonal_scores(
        session,
        season_range,
        stats_list,
        scores,
        harmattan_days_per_location if harmattan_days_per_location else None,
    )
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

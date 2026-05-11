"""Data types for the seasonal backtest pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.meteo_agent.seasonal_memory import LocationSeasonStats, SeasonDateRange


@dataclass(frozen=True)
class LocationDailyRow:
    """One day of weather data for one location, ready for CSV export."""

    date: str  # ISO YYYY-MM-DD
    precip_mm: float | None
    et0_mm: float | None
    tmax_c: float | None
    tmin_c: float | None
    sunshine_s: float | None
    wind_dir_dominant_deg: float | None
    min_rh_pct: float | None  # only populated when hourly RH fetched (saison_seche)
    harmattan_flag: bool | None  # only populated when hourly RH fetched


@dataclass(frozen=True)
class LocationBacktest:
    """All artifacts for one (season × location): stats, score, raw daily rows."""

    location_name: str
    country: str
    stats: LocationSeasonStats
    score: float
    harmattan_days: int | None  # only for saison_seche
    daily_rows: tuple[LocationDailyRow, ...]
    expected_days: int  # full span of the season range, inclusive
    diagnostic: str  # "normal" / "degraded" / "stress" (matches dashboard thresholds)


@dataclass(frozen=True)
class SeasonBacktest:
    """All artifacts for one season across all locations."""

    season_range: SeasonDateRange
    locations: tuple[LocationBacktest, ...]


@dataclass(frozen=True)
class CampaignBacktest:
    """All artifacts for the full campaign backtest."""

    campaign: str
    target_date: str  # ISO YYYY-MM-DD
    seasons: tuple[SeasonBacktest, ...]

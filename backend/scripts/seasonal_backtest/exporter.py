"""CSV exporters: raw daily weather (one file per season × location) + summary."""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

from scripts.seasonal_backtest.types import (
    CampaignBacktest,
    LocationBacktest,
    SeasonBacktest,
)

logger = logging.getLogger(__name__)

DAILY_CSV_COLUMNS = (
    "date",
    "precip_mm",
    "et0_mm",
    "tmax_c",
    "tmin_c",
    "sunshine_s",
    "wind_dir_dominant_deg",
    "min_rh_pct",
    "harmattan_flag",
)

SUMMARY_CSV_COLUMNS = (
    "campaign",
    "season",
    "location",
    "country",
    "start_date",
    "end_date",
    "expected_days",
    "fetched_days",
    "total_precip_mm",
    "total_et0_mm",
    "cumulative_balance_mm",
    "days_rain",
    "days_heavy_rain",
    "days_stress_temp",
    "avg_tmax_c",
    "harmattan_days",
    "score",
    "diagnostic",
)


def _sanitize(name: str) -> str:
    """Make a string safe for use as a filename segment."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")


def _format_flag(flag: bool | None) -> str:
    if flag is None:
        return ""
    return "1" if flag else "0"


def _format_number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.3f}"


def export_daily_csv(
    season: SeasonBacktest,
    location: LocationBacktest,
    raw_dir: Path,
) -> Path:
    """Write one CSV per (season × location) with the full daily series."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_sanitize(season.season_range.season.name)}_{_sanitize(location.location_name)}.csv"
    path = raw_dir / filename

    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow(DAILY_CSV_COLUMNS)
        for row in location.daily_rows:
            writer.writerow(
                (
                    row.date,
                    _format_number(row.precip_mm),
                    _format_number(row.et0_mm),
                    _format_number(row.tmax_c),
                    _format_number(row.tmin_c),
                    _format_number(row.sunshine_s),
                    _format_number(row.wind_dir_dominant_deg),
                    _format_number(row.min_rh_pct),
                    _format_flag(row.harmattan_flag),
                )
            )
    return path


def export_summary_csv(backtest: CampaignBacktest, output_dir: Path) -> Path:
    """Write one flat summary CSV — easy to diff against an external reference."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"summary_{backtest.campaign}.csv"

    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow(SUMMARY_CSV_COLUMNS)
        for season in backtest.seasons:
            for loc in season.locations:
                writer.writerow(
                    (
                        backtest.campaign,
                        season.season_range.season.name,
                        loc.location_name,
                        loc.country,
                        season.season_range.start_date.isoformat(),
                        season.season_range.end_date.isoformat(),
                        loc.expected_days,
                        loc.stats.total_days,
                        _format_number(loc.stats.total_precip_mm),
                        _format_number(loc.stats.total_et0_mm),
                        _format_number(loc.stats.cumulative_balance_mm),
                        loc.stats.days_rain,
                        loc.stats.days_heavy_rain,
                        loc.stats.days_stress_temp,
                        _format_number(loc.stats.avg_tmax),
                        "" if loc.harmattan_days is None else loc.harmattan_days,
                        _format_number(loc.score),
                        loc.diagnostic,
                    )
                )
    return path


def export_all(backtest: CampaignBacktest, output_dir: Path) -> tuple[Path, list[Path]]:
    """Write summary CSV + one CSV per (season × location). Returns (summary, raw_paths)."""
    summary_path = export_summary_csv(backtest, output_dir)
    raw_dir = output_dir / "raw"
    raw_paths: list[Path] = []
    for season in backtest.seasons:
        for loc in season.locations:
            raw_paths.append(export_daily_csv(season, loc, raw_dir))
    logger.info(
        "Exported summary (%s) + %d raw daily CSV(s) under %s",
        summary_path.name,
        len(raw_paths),
        raw_dir,
    )
    return summary_path, raw_paths

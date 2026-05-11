"""CLI entry point for the seasonal score backtest.

Usage:
    poetry run backtest-seasonal --target-date 2025-09-30
    poetry run backtest-seasonal --target-date 2025-09-30 --write-db --db local
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from scripts.meteo_agent.config import HARMATTAN_RH_THRESHOLD, LOCATIONS
from scripts.meteo_agent.seasonal_memory import (
    SeasonDateRange,
    _is_harmattan_direction,
    compute_harmattan_days,
    compute_score,
    compute_season_stats,
    fetch_harmattan_weather,
    get_campaign,
    get_completed_seasons,
    write_seasonal_scores,
)
from scripts.seasonal_backtest.exporter import export_all
from scripts.seasonal_backtest.fetcher import fetch_extended_season_weather
from scripts.seasonal_backtest.report import build_report, classify_diagnostic
from scripts.seasonal_backtest.types import (
    CampaignBacktest,
    LocationBacktest,
    LocationDailyRow,
    SeasonBacktest,
)

logger = logging.getLogger(__name__)

LOCAL_DB_URL = "postgresql://postgres:password@localhost:5433/commodities_compass"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest the seasonal score system on a past campaign."
    )
    parser.add_argument(
        "--target-date",
        type=date.fromisoformat,
        default=date(2025, 9, 30),
        help="ISO date that resolves to a campaign (Oct Y → Sep Y+1). "
        "Default 2025-09-30 → campaign 2024-2025.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("../docs/backtests/2024-2025-seasonal"),
        help="Where to write report.md + CSVs (relative to backend/).",
    )
    parser.add_argument(
        "--write-db",
        action="store_true",
        help="Also upsert results to pl_seasonal_score (idempotent). "
        "Off by default — the report stands alone.",
    )
    parser.add_argument(
        "--db",
        choices=("local", "gcp"),
        default="local",
        help="Which DB to write to when --write-db is set. "
        "'local' uses localhost:5433; 'gcp' uses DATABASE_SYNC_URL.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser.parse_args(argv)


def _build_daily_rows(
    weather: dict,
    harmattan_data: dict | None,
) -> tuple[LocationDailyRow, ...]:
    """Merge extended daily fields + harmattan daily flags into a row list."""
    daily = weather.get("daily", {})
    time_daily = daily.get("time", [])
    precip = daily.get("precipitation_sum", [])
    et0 = daily.get("et0_fao_evapotranspiration", [])
    tmax = daily.get("temperature_2m_max", [])
    tmin = daily.get("temperature_2m_min", [])
    sunshine = daily.get("sunshine_duration", [])
    wind_dir = daily.get("winddirection_10m_dominant", [])

    # Harmattan optional — pull daily wind + hourly RH from a parallel fetch
    h_daily = (harmattan_data or {}).get("daily", {}) if harmattan_data else {}
    h_hourly = (harmattan_data or {}).get("hourly", {}) if harmattan_data else {}
    h_time = h_daily.get("time", [])
    h_wind_dir = h_daily.get("winddirection_10m_dominant", [])
    h_rh_hourly = h_hourly.get("relative_humidity_2m", [])

    # Pre-compute min RH per day from hourly series, indexed by ISO date
    min_rh_by_date: dict[str, float] = {}
    if h_rh_hourly and h_time:
        for day_idx, day_iso in enumerate(h_time):
            start_h = day_idx * 24
            end_h = start_h + 24
            day_rh = [v for v in h_rh_hourly[start_h:end_h] if v is not None]
            if day_rh:
                min_rh_by_date[day_iso] = float(min(day_rh))

    # Build harmattan flag lookup keyed by date
    harmattan_flag_by_date: dict[str, bool] = {}
    if h_wind_dir and h_time:
        for day_idx, day_iso in enumerate(h_time):
            if day_idx >= len(h_wind_dir):
                break
            wd = h_wind_dir[day_idx]
            if wd is None:
                continue
            rh_min = min_rh_by_date.get(day_iso)
            if rh_min is None:
                continue
            harmattan_flag_by_date[day_iso] = (
                _is_harmattan_direction(float(wd)) and rh_min < HARMATTAN_RH_THRESHOLD
            )

    rows: list[LocationDailyRow] = []
    n = min(
        len(time_daily),
        len(precip),
        len(et0),
        len(tmax),
        len(tmin),
        len(sunshine),
        len(wind_dir),
    )
    for i in range(n):
        day_iso = time_daily[i]
        rows.append(
            LocationDailyRow(
                date=day_iso,
                precip_mm=_safe_float(precip[i]),
                et0_mm=_safe_float(et0[i]),
                tmax_c=_safe_float(tmax[i]),
                tmin_c=_safe_float(tmin[i]),
                sunshine_s=_safe_float(sunshine[i]),
                wind_dir_dominant_deg=_safe_float(wind_dir[i]),
                min_rh_pct=min_rh_by_date.get(day_iso) if harmattan_data else None,
                harmattan_flag=harmattan_flag_by_date.get(day_iso)
                if harmattan_data
                else None,
            )
        )
    return tuple(rows)


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _run_season(season_range: SeasonDateRange) -> SeasonBacktest:
    """Fetch + compute everything for one season, across all 6 locations."""
    logger.info(
        "── %s (%s → %s)",
        season_range.season.name,
        season_range.start_date,
        season_range.end_date,
    )
    weather = fetch_extended_season_weather(
        season_range.start_date, season_range.end_date
    )

    harmattan_raw: list[dict] = []
    if season_range.season.name == "saison_seche":
        try:
            harmattan_raw = fetch_harmattan_weather(
                season_range.start_date, season_range.end_date
            )
        except Exception as e:
            logger.warning("Harmattan fetch failed (non-blocking): %s", e)

    expected_days = (season_range.end_date - season_range.start_date).days + 1

    locations: list[LocationBacktest] = []
    for i, loc in enumerate(LOCATIONS):
        if i >= len(weather):
            logger.warning("Missing weather data for %s (index %d)", loc.name, i)
            continue
        loc_weather = weather[i]
        loc_harmattan = harmattan_raw[i] if i < len(harmattan_raw) else None

        stats = compute_season_stats(
            loc_weather,
            loc.name,
            loc.country,
            season_range.season.tmax_stress_threshold,
        )
        h_days = (
            compute_harmattan_days(loc_harmattan, season_range.start_date)
            if loc_harmattan
            else None
        )
        score = compute_score(stats, season_range.season, harmattan_days=h_days)
        daily_rows = _build_daily_rows(loc_weather, loc_harmattan)

        locations.append(
            LocationBacktest(
                location_name=loc.name,
                country=loc.country,
                stats=stats,
                score=score,
                harmattan_days=h_days,
                daily_rows=daily_rows,
                expected_days=expected_days,
                diagnostic=classify_diagnostic(score),
            )
        )
        logger.info(
            "  %-12s precip=%6.0f mm | bal=%+6.0f | stress=%2dd | tmax=%.1f°C | "
            "harm=%s | score=%.1f",
            loc.name,
            stats.total_precip_mm,
            stats.cumulative_balance_mm,
            stats.days_stress_temp,
            stats.avg_tmax,
            "—" if h_days is None else f"{h_days}d",
            score,
        )

    return SeasonBacktest(season_range=season_range, locations=tuple(locations))


def _resolve_db_url(db_choice: str) -> str:
    if db_choice == "local":
        return LOCAL_DB_URL
    url = os.getenv("DATABASE_SYNC_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_SYNC_URL not set — required for --db gcp. "
            "Open a bastion tunnel and export the connection string first."
        )
    return url


def _write_results_to_db(backtest: CampaignBacktest, db_url: str) -> None:
    """Upsert all (season × location) rows via existing write_seasonal_scores."""
    from scripts.db import get_session

    logger.info("Writing %d seasons to DB at %s", len(backtest.seasons), db_url)
    with get_session(url=db_url) as session:
        for season in backtest.seasons:
            stats_list = [loc.stats for loc in season.locations]
            scores = [loc.score for loc in season.locations]
            harmattan_days = [
                loc.harmattan_days if loc.harmattan_days is not None else 0
                for loc in season.locations
            ]
            had_any_harmattan = any(
                loc.harmattan_days is not None for loc in season.locations
            )
            write_seasonal_scores(
                session,
                season.season_range,
                stats_list,
                scores,
                harmattan_days_per_location=harmattan_days
                if had_any_harmattan
                else None,
            )


def run_backtest(args: argparse.Namespace) -> CampaignBacktest:
    """Pure orchestration — fetch + compute + return aggregated artifacts."""
    campaign = get_campaign(args.target_date)
    logger.info("Backtesting campaign %s (target_date=%s)", campaign, args.target_date)

    seasons = get_completed_seasons(args.target_date)
    if not seasons:
        raise RuntimeError(
            f"No completed seasons for target_date={args.target_date} "
            f"(campaign={campaign}). Pick a date later in the campaign."
        )
    logger.info("Found %d season(s) to backtest", len(seasons))

    season_backtests = tuple(_run_season(s) for s in seasons)
    return CampaignBacktest(
        campaign=campaign,
        target_date=args.target_date.isoformat(),
        seasons=season_backtests,
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path(__file__).parent.parent.parent / ".env")

    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    logger.info("=" * 60)
    logger.info("Seasonal Backtest")
    logger.info("=" * 60)

    try:
        backtest = run_backtest(args)
    except Exception as e:
        logger.exception("Backtest failed: %s", e)
        return 1

    summary_path, raw_paths = export_all(backtest, args.output_dir)
    report_path = build_report(backtest, args.output_dir)

    logger.info("")
    logger.info("Output:")
    logger.info("  report:  %s", report_path)
    logger.info("  summary: %s", summary_path)
    logger.info("  raw:     %d files under %s/raw/", len(raw_paths), args.output_dir)

    if args.write_db:
        db_url = _resolve_db_url(args.db)
        try:
            _write_results_to_db(backtest, db_url)
        except Exception as e:
            logger.exception("DB write failed (report + CSVs still written): %s", e)
            return 1

    logger.info("=" * 60)
    logger.info("Backtest complete")
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())

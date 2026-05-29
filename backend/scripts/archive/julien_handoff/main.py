"""CLI entry point — produce the Julien R&D handoff bundle.

Usage:
    poetry run julien-handoff --from 2026-05-01 --to 2026-05-23 \\
        --output ./output/julien_handoff_202605

By default, the database URL is read from ``DATABASE_SYNC_URL`` (the same
environment variable the Compass scrapers use). To run against GCP prod via
the bastion tunnel, point it at ``postgresql+psycopg2://...@127.0.0.1:5434/...``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from app.core.config import settings  # noqa: E402

from . import aux_loaders, loaders, writers  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=_parse_date, required=True)
    parser.add_argument("--to", dest="end", type=_parse_date, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output directory for the bundle.",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help=(
            "Override DATABASE_SYNC_URL (e.g. bastion tunnel URL pointing at "
            "GCP prod). Defaults to settings.DATABASE_SYNC_URL."
        ),
    )
    parser.add_argument(
        "--cot-history-days",
        type=int,
        default=400,
        help=(
            "How many extra days of COT history to pull before --from so the "
            "26-week rolling z-scores have enough context. Default 400."
        ),
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def build_main_dataset(
    engine,
    *,
    window: loaders.DateRange,
    cot_history_days: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assemble the daily-wide main DataFrame for the export window.

    Returns (main_df, algorithm_versions_df).
    """
    logger.info("Loading front-month OHLCV for [%s, %s]…", window.start, window.end)
    prices = loaders.load_front_month_ohlcv(engine, window)
    if prices.empty:
        raise RuntimeError(
            f"pl_contract_data_daily returned 0 rows for [{window.start}, {window.end}]. "
            "Wrong DB? Empty window?"
        )
    logger.info("  → %d trading rows", len(prices))

    logger.info("Loading derived technicals…")
    technicals = loaders.load_derived_indicators(engine, window, prices)
    logger.info("  → %d rows aligned on front-month", len(technicals))

    logger.info("Loading COT EU + rolling 26w z-scores (full history)…")
    cot = loaders.load_cot_eu_with_zscores(engine)
    logger.info("  → %d weekly rows", len(cot))

    logger.info("Loading sentiment (long → wide pivot)…")
    trading_dates = pd.DatetimeIndex(prices["date"].unique()).sort_values()
    sentiment = loaders.load_sentiment_pivot(engine, trading_dates)
    sentiment_cols = [c for c in sentiment.columns if c != "date"]
    logger.info("  → %d sentiment/count columns", len(sentiment_cols))

    logger.info("Loading external indicators (ENSO + FX)…")
    external = loaders.load_external_indicators(engine)
    logger.info("  → %d rows", len(external))

    logger.info("Loading Compass signal (prod-active algorithm)…")
    compass = loaders.load_compass_signal(engine, window, prices)
    logger.info("  → %d rows", len(compass))

    logger.info("Loading algorithm versions registry…")
    algo_versions = aux_loaders.load_algorithm_versions(engine)
    logger.info("  → %d versions", len(algo_versions))

    # Restrict COT history to a useful window: rolling 26w needs ~6 months of
    # context. Pull cot_history_days before the export start so the z-score
    # rolling has enough context, then asof-merge.
    history_cutoff = window.start - timedelta(days=cot_history_days)
    cot_windowed = cot[cot["release_date"] >= pd.Timestamp(history_cutoff)].copy()
    logger.info(
        "Using %d COT rows in [%s, …] for asof join (z-score context)…",
        len(cot_windowed),
        history_cutoff,
    )

    logger.info("Joining all blocks…")
    df = prices.merge(technicals, on="date", how="left", validate="one_to_one")
    df = loaders.join_cot_to_prices(df, cot_windowed)
    df = df.merge(sentiment, on="date", how="left", validate="one_to_one")
    df = loaders.join_external_to_prices(df, external)
    if not compass.empty:
        df = df.merge(compass, on="date", how="left", validate="one_to_one")

    ordered = writers.order_main_columns(df).sort_values("date").reset_index(drop=True)
    return ordered, algo_versions


def write_auxiliary_csvs(
    engine,
    paths: writers.BundlePaths,
    *,
    window: loaders.DateRange,
    algo_versions: pd.DataFrame,
) -> dict[str, int]:
    """Write all auxiliary CSVs. Returns name → row count."""
    summary: dict[str, int] = {}

    pairs: list[tuple[str, pd.DataFrame]] = [
        (
            "cocoa_specialist_predictions",
            aux_loaders.load_specialist_predictions(engine, window.start, window.end),
        ),
        (
            "cocoa_orchestrator_decisions",
            aux_loaders.load_orchestrator_decisions(engine, window.start, window.end),
        ),
        (
            "cocoa_signal_components",
            aux_loaders.load_signal_components(engine, window.start, window.end),
        ),
        (
            "cocoa_article_segments",
            aux_loaders.load_article_segments(engine, window.start, window.end),
        ),
        (
            "cocoa_fundamental_articles",
            aux_loaders.load_fundamental_articles(engine, window.start, window.end),
        ),
        (
            "cocoa_weather_observations",
            aux_loaders.load_weather_observations(engine, window.start, window.end),
        ),
        (
            "cocoa_sentiment_features",
            aux_loaders.load_sentiment_features(engine, window.start, window.end),
        ),
    ]
    for name, df in pairs:
        path = paths.aux_csv(name)
        rows = writers.write_aux_csv(df, path)
        summary[path.name] = rows
        logger.info("  → %s (%d rows)", path.name, rows)

    # Static (window-agnostic) auxiliaries.
    seasonal_path = paths.aux_csv_static("cocoa_seasonal_scores")
    rows = writers.write_aux_csv(
        aux_loaders.load_seasonal_scores(engine), seasonal_path
    )
    summary[seasonal_path.name] = rows
    logger.info("  → %s (%d rows)", seasonal_path.name, rows)

    algo_path = paths.aux_csv_static("compass_algorithm_versions")
    rows = writers.write_aux_csv(algo_versions, algo_path)
    summary[algo_path.name] = rows
    logger.info("  → %s (%d rows)", algo_path.name, rows)

    return summary


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if args.end < args.start:
        logger.error("--to (%s) is before --from (%s)", args.end, args.start)
        return 2

    db_url = (
        args.db_url
        or os.environ.get("DATABASE_SYNC_URL")
        or str(settings.DATABASE_SYNC_URL)
    )
    if not db_url:
        logger.error("No database URL. Set --db-url or DATABASE_SYNC_URL env var.")
        return 2

    logger.info("=" * 70)
    logger.info("Julien R&D handoff bundle")
    logger.info("Window: %s → %s", args.start, args.end)
    logger.info("Output: %s", args.output)
    logger.info("DB URL: %s", _sanitize_url(db_url))
    logger.info("=" * 70)

    engine = create_engine(db_url, pool_pre_ping=True)

    window = loaders.DateRange(start=args.start, end=args.end)
    main_df, algo_versions = build_main_dataset(
        engine, window=window, cot_history_days=args.cot_history_days
    )

    paths = writers.BundlePaths(
        out_dir=args.output,
        run_stamp=args.end.strftime("%Y%m%d"),
        month_stamp=args.end.strftime("%Y%m"),
    )

    logger.info("Writing auxiliary CSVs…")
    aux_summary = write_auxiliary_csvs(
        engine, paths, window=window, algo_versions=algo_versions
    )

    logger.info("Writing main CSV + meta.json + dictionary.md…")
    main_sha = writers.write_main_csv_and_metadata(
        main_df,
        paths,
        window_start=window.start,
        window_end=window.end,
        aux_files=sorted(aux_summary.keys()),
        algorithm_versions=algo_versions,
    )

    logger.info("Validating main CSV (Julien-style hard checks)…")
    writers.validate_main_csv(main_df)

    logger.info("Writing README_HANDOFF.md…")
    writers.write_readme(
        paths,
        window_start=window.start,
        window_end=window.end,
        main_sha=main_sha,
        aux_summary=aux_summary,
    )

    logger.info("=" * 70)
    logger.info("Bundle ready: %s", args.output)
    logger.info(
        "Main: %s (%d rows × %d cols, SHA-256 %s)",
        paths.main_csv.name,
        len(main_df),
        main_df.shape[1],
        main_sha[:12],
    )
    null_top = (main_df.isna().mean() * 100).sort_values(ascending=False).head(5)
    logger.info("Top-5 null% cols:")
    for col, pct in null_top.items():
        logger.info("  %-40s  %5.2f%%", col, pct)
    logger.info("=" * 70)
    return 0


def _sanitize_url(url: str) -> str:
    """Strip credentials for logging."""
    import re

    return re.sub(r"://[^@]+@", "://***@", url)


if __name__ == "__main__":
    sys.exit(main())

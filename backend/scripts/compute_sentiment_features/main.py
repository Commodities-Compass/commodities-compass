"""CLI entry point for computing sentiment z-delta features (shadow mode).

Reads raw sentiment scores from pl_article_segment (inline_v1),
computes rolling z-score (21d) + delta (3d) per theme, and upserts
into pl_sentiment_feature.
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import func, select, text

from app.engine.sentiment_features import compute_sentiment_zdelta
from app.models.pipeline import PlArticleSegment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

TARGET_N = 250  # EXP-014: minimum observations for reliable signal

load_dotenv(Path(__file__).parent.parent.parent / ".env")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute sentiment z-delta features (shadow mode)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Compute but don't write"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    from scripts.db import get_session

    # Step 1: Read raw sentiment scores from pl_article_segment
    logger.info("Step 1: Reading raw sentiment scores from pl_article_segment...")
    with get_session() as session:
        rows = session.execute(
            select(
                PlArticleSegment.article_date.label("date"),
                PlArticleSegment.theme,
                func.avg(PlArticleSegment.sentiment_score).label("raw_score"),
            )
            .where(
                PlArticleSegment.extraction_version == "inline_v1",
                PlArticleSegment.zone == "all",
                PlArticleSegment.sentiment_score.isnot(None),
            )
            .group_by(PlArticleSegment.article_date, PlArticleSegment.theme)
            .order_by(PlArticleSegment.article_date)
        ).all()

    if not rows:
        logger.info("No inline_v1 sentiment data found. Nothing to compute.")
        return 0

    df = pd.DataFrame(rows, columns=["date", "theme", "raw_score"])
    df["raw_score"] = df["raw_score"].astype(float)
    logger.info(f"Loaded {len(df)} date×theme observations")

    # Log accumulation per theme
    for theme, group in df.groupby("theme"):
        n = len(group)
        status = "ready" if n >= TARGET_N else f"{n}/{TARGET_N}"
        logger.info(f"  {theme}: n={n} ({status})")

    # Step 2: Compute z-delta features
    logger.info("Step 2: Computing z-score delta features...")
    features = compute_sentiment_zdelta(df)
    logger.info(f"Computed {len(features)} feature rows")

    if args.dry_run:
        logger.info(
            "[DRY RUN] Would upsert %d rows into pl_sentiment_feature", len(features)
        )
        for _, row in features.tail(8).iterrows():
            logger.info(
                "  %s | %s | raw=%.3f | z=%.3f | delta=%.3f | min_met=%s",
                row["date"],
                row["theme"],
                row["raw_score"],
                row.get("zscore", float("nan")),
                row.get("zscore_delta", float("nan")),
                row["min_periods_met"],
            )
        return 0

    # Step 3: Upsert into pl_sentiment_feature
    logger.info("Step 3: Upserting into pl_sentiment_feature...")
    upserted = 0
    with get_session() as session:
        for _, row in features.iterrows():
            raw = row["raw_score"]
            z = row["zscore"]
            zd = row["zscore_delta"]

            session.execute(
                text("""
                    INSERT INTO pl_sentiment_feature (id, date, theme, raw_score, zscore, zscore_delta, min_periods_met)
                    VALUES (gen_random_uuid(), :date, :theme, :raw_score, :zscore, :zscore_delta, :min_periods_met)
                    ON CONFLICT (date, theme) DO UPDATE SET
                        raw_score = EXCLUDED.raw_score,
                        zscore = EXCLUDED.zscore,
                        zscore_delta = EXCLUDED.zscore_delta,
                        min_periods_met = EXCLUDED.min_periods_met
                """),
                {
                    "date": row["date"],
                    "theme": row["theme"],
                    "raw_score": None if pd.isna(raw) else round(float(raw), 3),
                    "zscore": None if pd.isna(z) else round(float(z), 3),
                    "zscore_delta": None if pd.isna(zd) else round(float(zd), 3),
                    "min_periods_met": bool(row["min_periods_met"]),
                },
            )
            upserted += 1

    logger.info(f"Upserted {upserted} rows into pl_sentiment_feature")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""One-time backfill: extract per-location diagnostics from existing weather observations.

Reads the summary + impact_assessment text and uses OpenAI to extract
the diagnostics JSON that was previously discarded.

Usage:
    poetry run python scripts/backfill_diagnostics.py [--dry-run] [--days 10]
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from openai import OpenAI  # noqa: E402
from sqlalchemy import text  # noqa: E402

from scripts.db import get_session  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """Extract per-location weather diagnostics from this cocoa weather report.

Locations: Daloa, San-Pédro, Soubré (Côte d'Ivoire), Kumasi, Takoradi, Goaso (Ghana).

Rules:
- "stress" = 2+ indicators beyond threshold simultaneously
- "degraded" = 1 indicator slightly beyond threshold
- "normal" = within seasonal norms

Return ONLY a JSON object with exactly 6 keys (the location names above).
Each value must be exactly one of: "normal", "degraded", "stress".
No markdown fences, no commentary."""


def extract_diagnostics(summary: str, impact: str) -> dict | None:
    """Call OpenAI to extract diagnostics from existing text."""
    client = OpenAI()
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": EXTRACTION_PROMPT},
            {
                "role": "user",
                "content": f"Summary: {summary}\n\nImpact: {impact}",
            },
        ],
        temperature=0,
        max_tokens=200,
    )
    raw = response.choices[0].message.content or ""
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Failed to parse LLM response: %s", raw[:200])
        return None

    # Validate
    valid_statuses = {"normal", "degraded", "stress"}
    expected_locations = {"Daloa", "San-Pédro", "Soubré", "Kumasi", "Takoradi", "Goaso"}
    for loc in expected_locations:
        if loc not in parsed:
            logger.error("Missing location %s in response: %s", loc, parsed)
            return None
        if parsed[loc] not in valid_statuses:
            logger.error("Invalid status for %s: %s", loc, parsed[loc])
            return None

    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill diagnostics JSONB")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--days", type=int, default=10)
    args = parser.parse_args()

    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT id, date, summary, impact_assessment
                FROM pl_weather_observation
                WHERE diagnostics IS NULL
                  AND summary IS NOT NULL
                ORDER BY date DESC
                LIMIT :days
            """),
            {"days": args.days},
        ).fetchall()

        if not rows:
            logger.info("No rows to backfill")
            return 0

        logger.info("Found %d rows to backfill", len(rows))

        for row in rows:
            row_id, row_date, summary, impact = row
            logger.info("Processing %s...", row_date)

            diagnostics = extract_diagnostics(summary or "", impact or "")
            if not diagnostics:
                logger.error(
                    "FAILED to extract diagnostics for %s — skipping", row_date
                )
                continue

            logger.info("  %s → %s", row_date, diagnostics)

            if args.dry_run:
                logger.info("  [DRY RUN] Would update id=%s", row_id)
                continue

            session.execute(
                text("""
                    UPDATE pl_weather_observation
                    SET diagnostics = CAST(:diag AS jsonb)
                    WHERE id = :id
                """),
                {"diag": json.dumps(diagnostics), "id": str(row_id)},
            )

        if not args.dry_run:
            session.commit()
            logger.info("Committed %d updates", len(rows))

    return 0


if __name__ == "__main__":
    sys.exit(main())

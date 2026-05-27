"""CLI entry point for the ensemble brief generator.

Runs at 19:35 UTC daily (P2b calendar-aware gate), AFTER cc-ensemble-explainer
(19:25) has enriched the ensemble row with narrative LLM fields.

Sequence:
  1. Resolve active contract
  2. Read all data (ensemble row + orchestrator + 14 specialists + press +
     meteo + technicals + persistence) via db_reader
  3. Render the 7-section brief via brief_generator (pure formatter)
  4. Save locally if --output specified, upload to Drive otherwise
  5. Idempotent: re-uploading the same filename overwrites (Drive uploader
     behaviour) so manual re-runs are safe.

Fail-loud per pipeline-error-handling rules. Independent of legacy
cc-compass-brief — both can coexist in Drive (distinct filenames).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date as date_type
from pathlib import Path

import sentry_sdk
from dotenv import load_dotenv
from sentry_sdk.crons import monitor
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.sentry import init_sentry
from scripts.compass_brief.drive_uploader import DriveUploader
from scripts.compass_brief_ensemble.brief_generator import render_brief
from scripts.compass_brief_ensemble.config import (
    FILENAME_PATTERN,
    LOG_FORMAT,
    get_credentials_json,
    get_drive_briefs_folder_id,
)
from scripts.compass_brief_ensemble.db_reader import (
    EnsembleBriefDataMissingError,
    read_brief_data,
)

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).parent.parent.parent / ".env")
init_sentry("compass-brief-ensemble")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compass Brief Ensemble — daily ensemble brief generator + Drive upload"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Generate + print, no Drive upload"
    )
    parser.add_argument(
        "--output", type=str, default=None, help="Save brief to local file path"
    )
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass eve-of-trading-day gate (backfill/debugging)",
    )
    parser.add_argument(
        "--target-date",
        type=date_type.fromisoformat,
        default=None,
        help=(
            "Trading session date the brief targets (YYYY-MM-DD). Defaults to "
            "get_next_session_date(today()) per P2b. Drives filename suffix."
        ),
    )
    return parser.parse_args()


@monitor(monitor_slug="compass-brief-ensemble")
def main() -> int:
    args = _parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # P2b gate
    from scripts.db import (
        get_next_session_date,
        get_previous_session_date,
        is_eve_of_trading_day,
    )

    target_date: date_type = args.target_date or get_next_session_date()
    if not args.force and args.target_date is None:
        if not is_eve_of_trading_day():
            logger.info(
                "Phase-B gate: tomorrow is not a trading day — skipping cleanly."
            )
            return 0

    # ``data_date`` = last completed session = the row date in
    # pl_indicator_daily / pl_orchestrator_decision / pl_specialist_prediction.
    # ``target_date`` remains the upcoming session for filename + press/meteo
    # which are P2b-keyed to the upcoming session.
    data_date: date_type = get_previous_session_date(target_date)

    logger.info("=" * 60)
    logger.info("Compass Brief Ensemble")
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE UPLOAD")
    logger.info("Target session: %s | Data session: %s", target_date, data_date)
    logger.info("=" * 60)

    # Filename is keyed on the SESSION date (= data_date), not the publication
    # date (target_date / display_date). This keeps brief + NotebookLM audio +
    # dashboard audio lookup aligned: audio_service.get_audio_file_info uses
    # the resolved session_date when the dashboard calendar fetches audio for
    # the user-facing display_date. See `_parse_and_validate_date` in
    # dashboard endpoint.
    filename = FILENAME_PATTERN.format(date=data_date.strftime("%Y%m%d"))

    try:
        from scripts.contract_resolver import resolve_active

        db_url = str(settings.DATABASE_SYNC_URL)
        engine = create_engine(db_url)

        with Session(engine) as session:
            contract_id = resolve_active(session)
            logger.info("Active contract id: %s", contract_id)
            data = read_brief_data(
                session, target_date, contract_id, data_date=data_date
            )

        brief = render_brief(data)
        logger.info("Generated brief: %s (%d chars)", filename, len(brief))

        if args.output:
            Path(args.output).write_text(brief, encoding="utf-8")
            logger.info("Saved to %s", args.output)

        if args.dry_run:
            print("\n" + brief)
            return 0

        # Upload to Drive (same folder as legacy brief; filename suffix
        # discriminates them).
        creds = get_credentials_json()
        uploader = DriveUploader(creds)
        folder_id = get_drive_briefs_folder_id()
        file_id = uploader.upload(brief, filename, folder_id)

        sentry_sdk.set_context(
            "compass_brief_ensemble",
            {
                "target_date": target_date.isoformat(),
                "filename": filename,
                "file_id": file_id,
                "decision": data.decision,
                "persistence_days": data.persistence_days,
                "n_specialists": len(data.specialists),
            },
        )

        logger.info("=" * 60)
        logger.info("SUCCESS — %s uploaded (id=%s)", filename, file_id)
        logger.info("=" * 60)
        return 0

    except (KeyboardInterrupt, SystemExit):
        raise
    except EnsembleBriefDataMissingError as exc:
        logger.exception("Ensemble brief data missing: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1
    except Exception as exc:
        logger.exception("Compass brief ensemble failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

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
from app.core.i18n import LANGUAGE_CLI_CHOICES, expand_languages
from app.core.sentry import init_sentry
from scripts.compass_brief.drive_uploader import DriveUploader
from scripts.compass_brief_ensemble.brief_generator import render_brief
from scripts.compass_brief_ensemble.config import (
    LOG_FORMAT,
    filename_for,
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
        "--session-date",
        type=date_type.fromisoformat,
        default=None,
        help=(
            "Session date to (re)generate, YYYY-MM-DD (= the row date and the "
            "filename stem). Default (cron): the last completed trading session. "
            "Explicit --session-date bypasses the eve-of-trading-day gate "
            "(backfills, manual reruns)."
        ),
    )
    parser.add_argument(
        "--language",
        choices=LANGUAGE_CLI_CHOICES,
        default="fr",
        help=(
            "Brief language (default: fr). 'en' renders the native-English "
            "(Ghana) ensemble brief → '-EN' filename; 'both' renders fr then "
            "en in one execution (no per-language jobs). The EN edition is "
            "ensemble-only (US-4 scope)."
        ),
    )
    return parser.parse_args()


@monitor(monitor_slug="compass-brief-ensemble")
def main() -> int:
    args = _parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Phase-B date pair — single source of truth (scripts/db.py). ``data_date``
    # (= last completed session) is the row date in pl_indicator_daily /
    # pl_orchestrator_decision / pl_specialist_prediction AND the filename stem;
    # ``target_date`` (upcoming session) frames the press/meteo upper-bound
    # reads. --force / --session-date bypass the eve-of-trading-day gate.
    from scripts.db import phase_b_should_skip, resolve_phase_b_dates

    if phase_b_should_skip(args.session_date, args.force):
        logger.info("Phase-B gate: tomorrow is not a trading day — skipping cleanly.")
        return 0

    dates = resolve_phase_b_dates(args.session_date)
    target_date: date_type = dates.target_date
    data_date: date_type = dates.data_date

    # Filename stem is keyed on the SESSION date (= data_date), not the
    # publication date (target_date / display_date). This keeps brief +
    # NotebookLM audio + dashboard audio lookup aligned: audio_service resolves
    # the session_date when the dashboard calendar fetches audio for the
    # user-facing display_date. See `_parse_and_validate_date` in the dashboard
    # endpoint. The per-language suffix (`-EN`) is added by config.filename_for.
    date_stem = data_date.strftime("%Y%m%d")
    langs = expand_languages(args.language)

    logger.info("=" * 60)
    logger.info("Compass Brief Ensemble")
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE UPLOAD")
    logger.info("Language: %s -> %s", args.language, [str(lang) for lang in langs])
    logger.info("Target session: %s | Data session: %s", target_date, data_date)
    logger.info("=" * 60)

    try:
        from scripts.contract_resolver import resolve_active

        db_url = str(settings.DATABASE_SYNC_URL)
        engine = create_engine(db_url)

        # Drive handles are resolved once, only when actually uploading.
        uploader: DriveUploader | None = None
        folder_id: str | None = None
        if not args.dry_run:
            uploader = DriveUploader(get_credentials_json())
            folder_id = get_drive_briefs_folder_id()

        uploaded: list[tuple[str, str]] = []
        last_data = None

        # fr-first, sequential per language: read → render → publish, then move
        # to the next language. If the EN read/render fails, the FR brief has
        # already been uploaded (committed-language preserved), and the raised
        # error still fails the job (exit 1) so the EN gap is visible in Sentry.
        with Session(engine) as session:
            contract_id = resolve_active(session)
            logger.info("Active contract id: %s", contract_id)

            for language in (str(lang) for lang in langs):
                logger.info("--- Brief [%s] ---", language)
                data = read_brief_data(
                    session,
                    target_date,
                    contract_id,
                    data_date=data_date,
                    language=language,
                )
                brief = render_brief(data, language=language)
                filename = filename_for(date_stem, language)
                logger.info("Generated brief: %s (%d chars)", filename, len(brief))

                if args.output:
                    out_path = Path(args.output)
                    # For a multi-language run, keep FR at the given path and
                    # write EN to a `-en` sibling so neither overwrites.
                    if len(langs) > 1 and language != "fr":
                        out_path = out_path.with_name(
                            f"{out_path.stem}-{language}{out_path.suffix}"
                        )
                    out_path.write_text(brief, encoding="utf-8")
                    logger.info("Saved to %s", out_path)

                if args.dry_run:
                    print(f"\n===== {filename} [{language}] =====\n" + brief)
                    last_data = data
                    continue

                assert uploader is not None and folder_id is not None
                file_id = uploader.upload(brief, filename, folder_id)
                uploaded.append((filename, file_id))
                last_data = data
                logger.info("Uploaded %s (id=%s)", filename, file_id)

        if args.dry_run:
            return 0

        sentry_sdk.set_context(
            "compass_brief_ensemble",
            {
                "target_date": target_date.isoformat(),
                "language": args.language,
                "uploaded": [name for name, _ in uploaded],
                "decision": last_data.decision if last_data else None,
                "persistence_days": (last_data.persistence_days if last_data else None),
                "n_specialists": len(last_data.specialists) if last_data else 0,
            },
        )

        logger.info("=" * 60)
        logger.info(
            "SUCCESS — %d brief(s) uploaded: %s",
            len(uploaded),
            ", ".join(name for name, _ in uploaded),
        )
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

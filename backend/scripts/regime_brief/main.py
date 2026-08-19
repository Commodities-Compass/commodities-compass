"""cc-regime-brief — narrative + Drive brief for the regime+judge system.

Per language, in order: read → narrate → persist → render → upload.

This job merges what used to be two: the explainer (LLM narrative into
pl_indicator_daily) and the brief (render + upload). Keeping them apart would
mean two LLM-bearing jobs for one text, and a window where the dashboard and
the brief disagree. Here the prose is written once per language and is the same
in both places by construction.

Native per language — not translated. Each call composes in its own language
from the judge's English working notes.

Fail-loud everywhere: a missing input, a partial narrative, a narrative that
mentions the machinery, or a missing adapter row all abort the run. There is no
cross-algorithm fallback anywhere in this path.

Usage:
    poetry run regime-brief --language both
    poetry run regime-brief --session-date 2026-08-17 --language fr
    poetry run regime-brief --dry-run --verbose
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import sentry_sdk
from sentry_sdk.crons import monitor
from sqlalchemy import text

from app.core.i18n import LANGUAGE_CLI_CHOICES, expand_languages
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper
from scripts._shared.drive_uploader import DriveUploader
from scripts.regime_brief.brief_generator import render_brief
from scripts.regime_brief.config import (
    ALGORITHM_NAME,
    ALGORITHM_VERSION,
    filename_for,
    get_credentials_json,
    get_drive_briefs_folder_id,
)
from scripts.regime_brief.db_reader import read_brief_data
from scripts.regime_brief.db_writer import write_narrative
from scripts.regime_brief.narrator import narrate

configure_logging()
logger = logging.getLogger(__name__)

bootstrap_scraper("regime-brief", script_file=__file__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compass Brief — regime+judge narrative generator + Drive upload"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate + print. No Drive upload, no DB write.",
    )
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    parser.add_argument(
        "--session-date",
        type=str,
        default=None,
        help="Session date to (re)generate, YYYY-MM-DD (= the row date).",
    )
    parser.add_argument(
        "--language",
        choices=LANGUAGE_CLI_CHOICES,
        default="fr",
        help="Output language(s). 'both' generates fr then en.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write to this path instead of uploading (debug).",
    )
    return parser.parse_args()


def _resolve_version_id(session):  # noqa: ANN001 — sync Session
    row = session.execute(
        text("SELECT id FROM pl_algorithm_version WHERE name = :n AND version = :v"),
        {"n": ALGORITHM_NAME, "v": ALGORITHM_VERSION},
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"pl_algorithm_version {ALGORITHM_NAME}@{ALGORITHM_VERSION} not found"
        )
    return row[0]


def _resolve_session_date(session, explicit: str | None):  # noqa: ANN001
    """The session to write for — explicit, else the latest regime decision.

    Anchored on pl_regime_shadow rather than the calendar: the brief speaks for
    a decision, so it can only exist where that decision does.
    """
    from datetime import datetime

    if explicit:
        return datetime.strptime(explicit, "%Y-%m-%d").date()
    row = session.execute(
        text("SELECT MAX(date) AS d FROM pl_regime_shadow")
    ).fetchone()
    if row is None or row.d is None:
        raise RuntimeError("pl_regime_shadow is empty — no session to brief")
    return row.d


@monitor(monitor_slug="regime-brief")
def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    from scripts.db import get_session

    langs = [str(lang) for lang in expand_languages(args.language)]
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("Languages: %s", langs)

    uploaded: list[tuple[str, str]] = []
    uploader: DriveUploader | None = None
    folder_id: str | None = None
    if not args.dry_run and not args.output:
        uploader = DriveUploader(get_credentials_json())
        folder_id = get_drive_briefs_folder_id()

    with get_session() as session:
        version_id = _resolve_version_id(session)
        session_date = _resolve_session_date(session, args.session_date)
        date_stem = session_date.strftime("%Y%m%d")
        logger.info("Session %s (algorithm %s)", session_date, ALGORITHM_NAME)

        # fr first, sequentially. If EN fails, FR is already committed and
        # uploaded; the raised error still fails the job so the EN gap is
        # visible in Sentry the same evening.
        for language in langs:
            logger.info("--- [%s] ---", language)
            data = read_brief_data(
                session,
                session_date=session_date,
                algorithm_version_id=version_id,
                language=language,
            )
            narrative = narrate(data)
            brief = render_brief(data, narrative)
            filename = filename_for(date_stem, language)

            if args.dry_run:
                print(f"\n===== {filename} =====\n{brief}")
                continue

            # Persist BEFORE publishing: the dashboard and the brief must carry
            # the same text, and a failed upload is recoverable while a
            # published brief with no stored narrative is a visible split.
            write_narrative(
                session,
                narrative,
                session_date=session_date,
                algorithm_version_id=version_id,
                language=language,
            )
            session.commit()

            if args.output:
                path = Path(args.output)
                if len(langs) > 1 and language != "fr":
                    path = path.with_name(f"{path.stem}-{language}{path.suffix}")
                path.write_text(brief, encoding="utf-8")
                logger.info("Saved to %s", path)
                continue

            assert uploader is not None and folder_id is not None
            file_id = uploader.upload(brief, filename, folder_id)
            uploaded.append((filename, file_id))
            logger.info("Uploaded %s (id=%s)", filename, file_id)

    sentry_sdk.set_context(
        "regime_brief",
        {
            "session_date": str(session_date),
            "languages": langs,
            "uploaded": [name for name, _ in uploaded],
            "dry_run": args.dry_run,
        },
    )
    logger.info("SUCCESS — %d brief(s) uploaded", len(uploaded))
    return 0


if __name__ == "__main__":
    sys.exit(main())

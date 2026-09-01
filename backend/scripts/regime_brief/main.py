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
from datetime import date as date_cls
from datetime import datetime
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

# Must match app/services/audio_service._candidate_suffixes — the dashboard finds
# the episode by this name and nothing else.
AUDIO_FILENAME = "{stem}-CompassAudio-Regime{suffix}.wav"

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
        "--skip-audio",
        action="store_true",
        help="Narrative and brief only — no script, no synthesis, no audio upload",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Upload the episode to the WATCHED audio folder, which publishes it. "
        "Without it the episode goes to the shadow folder.",
    )
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the eve-of-trading-day gate (manual rerun on a non-eve day).",
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


def _resolve_session_date(session, explicit: date_cls | None):  # noqa: ANN001
    """The session to write for — explicit, else the latest regime decision.

    Anchored on pl_regime_shadow rather than the calendar: the brief speaks for
    a decision, so it can only exist where that decision does.

    ⚠️ This answers WHICH session, never WHETHER to run. Un-gated, it silently
    re-briefs the newest decision every time the decision table stops advancing
    (weekends, holidays) — see the Phase-B gate in main() and
    .claude/rules/pipeline-phase-contract.md.
    """
    if explicit:
        return explicit
    row = session.execute(
        text("SELECT MAX(date) AS d FROM pl_regime_shadow")
    ).fetchone()
    if row is None or row.d is None:
        raise RuntimeError("pl_regime_shadow is empty — no session to brief")
    return row.d


@monitor(monitor_slug="regime-brief")
def _produce_episode(
    data,  # noqa: ANN001 — BriefData, imported lazily to keep the brief path light
    narrative,  # noqa: ANN001 — Narrative
    session_date,  # noqa: ANN001 — date
    language: str,
    *,
    publish: bool,
) -> str:
    """Write the script, speak it, and put the file where it belongs.

    Merged into this job rather than scheduled separately: it needs exactly what
    the brief has just assembled, and two jobs would mean two executions racing
    on the same session. The brief half is on its way out anyway once the manual
    NotebookLM step stops.
    """
    from scripts._shared.drive_config import get_drive_audio_folder_id
    from scripts.podcast_audio.script_writer import assess_quality, write_script
    from scripts.podcast_audio.tts import get_synthesizer

    script = write_script(data, narrative)
    report = assess_quality(script)
    shares = ", ".join(f"{k} {v:.0%}" for k, v in sorted(report.speech_share.items()))
    logger.info(
        "[%s] script: %d turns, %d chars, ~%.0fs — %s, cv %.2f",
        language,
        report.turns,
        report.chars,
        report.seconds,
        shares,
        report.length_cv,
    )
    for warning in report.warnings:
        logger.warning("[%s] off the house style: %s", language, warning)
    if report.warnings:
        sentry_sdk.capture_message(
            f"Podcast script [{language}] off the house style: "
            + " | ".join(report.warnings),
            level="warning",
        )

    audio = get_synthesizer().synthesize(script)
    filename = AUDIO_FILENAME.format(
        stem=session_date.strftime("%Y%m%d"),
        suffix="-EN" if language == "en" else "",
    )
    folder = get_drive_audio_folder_id(shadow=not publish)
    uploader = DriveUploader(get_credentials_json())
    file_id = uploader.upload_bytes(audio, filename, "audio/wav", folder)
    logger.info(
        "[%s] uploaded %s to the %s folder (id=%s)",
        language,
        filename,
        "WATCHED" if publish else "shadow",
        file_id,
    )
    return filename


def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    from scripts.db import get_session, phase_b_should_skip

    explicit_session = (
        datetime.strptime(args.session_date, "%Y-%m-%d").date()
        if args.session_date
        else None
    )

    # Phase-B gate. The brief is scheduled DAILY because the eve of Monday is a
    # Sunday, so it must decide for itself whether tonight precedes a session.
    # Without this it re-briefs whatever MAX(pl_regime_shadow) holds — on every
    # weekend and holiday that is an ALREADY PUBLISHED session, and re-briefing
    # burns two LLM calls, overwrites the narrative on the served row and
    # overwrites the Drive .txt the NotebookLM podcast is cut from.
    # See .claude/rules/pipeline-phase-contract.md
    if phase_b_should_skip(explicit_session, args.force):
        logger.info(
            "regime-brief: not eve of a trading day + no --session-date/--force, skipping"
        )
        return 0

    langs = [str(lang) for lang in expand_languages(args.language)]
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("Languages: %s", langs)

    uploaded: list[tuple[str, str]] = []
    episodes: list[str] = []
    uploader: DriveUploader | None = None
    folder_id: str | None = None
    if not args.dry_run and not args.output:
        uploader = DriveUploader(get_credentials_json())
        folder_id = get_drive_briefs_folder_id()

    with get_session() as session:
        version_id = _resolve_version_id(session)
        session_date = _resolve_session_date(session, explicit_session)
        date_stem = session_date.strftime("%Y%m%d")
        logger.info("Session %s (algorithm %s)", session_date, ALGORITHM_NAME)

        # Pass 1 — narrative and brief, every language. This is what the
        # dashboard reads, so it completes before a single byte of audio is
        # synthesised: a TTS failure must never cost the dashboard its prose.
        #
        # fr first, sequentially. If EN fails, FR is already committed and
        # uploaded; the raised error still fails the job so the EN gap is
        # visible in Sentry the same evening.
        prepared: list[tuple[str, object, object]] = []
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
                watch_lines=data.watch_lines,
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
            prepared.append((language, data, narrative))

        # Pass 2 — the episode. Everything above is already committed, so a
        # failure here is loud and recoverable: re-run with --skip-brief.
        if args.skip_audio or args.dry_run or args.output:
            logger.info("Audio skipped")
        else:
            for language, data, narrative in prepared:
                logger.info("--- [%s] audio ---", language)
                episodes.append(
                    _produce_episode(
                        data, narrative, session_date, language, publish=args.publish
                    )
                )

    sentry_sdk.set_context(
        "regime_brief",
        {
            "session_date": str(session_date),
            "languages": langs,
            "uploaded": [name for name, _ in uploaded],
            "episodes": episodes,
            "dry_run": args.dry_run,
        },
    )
    logger.info(
        "SUCCESS — %d brief(s) uploaded, %d episode(s) produced",
        len(uploaded),
        len(episodes),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

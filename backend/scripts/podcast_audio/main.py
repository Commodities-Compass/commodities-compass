"""cc-podcast-audio — the daily episode, from the served row to a script.

Runs after ``cc-regime-brief``: it reads the narrative that job wrote onto the
served row and turns it into a two-voice conversation. Speech synthesis is the
next increment; today the job stops at the script, which is deliberate — P0
established that the conversational quality is decided by the script and not by
the engine, so the script is what has to be reviewed first.

    poetry run podcast-audio --session-date 2026-08-24 --language fr --script-only
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path

import sentry_sdk
from dotenv import load_dotenv

from scripts._shared.cli import build_base_argparser
from scripts._shared.drive_config import (
    get_credentials_json,
    get_drive_audio_folder_id,
)
from scripts._shared.drive_uploader import DriveUploader
from scripts._shared.logging import configure_logging
from scripts.db import get_session
from scripts.podcast_audio.db_reader import (
    EpisodeInputsMissingError,
    read_episode_inputs,
)
from scripts.podcast_audio.script_writer import (
    PodcastScript,
    ScriptError,
    assess_quality,
    write_script,
)
from scripts.podcast_audio.tts import SynthesisError, get_synthesizer

load_dotenv(Path(__file__).parent.parent.parent / ".env")

logger = logging.getLogger(__name__)

# Must match app/services/audio_service._candidate_suffixes — the dashboard finds
# the episode by this name and nothing else.
AUDIO_FILENAME = "{stem}-CompassAudio-Regime{suffix}.wav"


def _parse_args():
    parser = build_base_argparser(
        description="Compass daily podcast — script generation", include_force=False
    )
    parser.add_argument(
        "--session-date",
        required=True,
        help="Session date to voice (YYYY-MM-DD) — the row date, as everywhere else",
    )
    parser.add_argument(
        "--language",
        default="fr",
        choices=["fr", "en", "both"],
        help="Episode language",
    )
    parser.add_argument(
        "--script-only",
        action="store_true",
        help="Write the script and stop — no synthesis, no upload",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Upload to the WATCHED audio folder, which publishes the episode. "
        "Without it the upload goes to the shadow folder.",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Synthesise and write the audio locally, do not touch Drive",
    )
    parser.add_argument(
        "--out",
        help="Directory to write the script (and the audio with --no-upload) into",
    )
    return parser.parse_args()


def _render(script: PodcastScript) -> str:
    header = (
        f"# {script.language.upper()} — {len(script.turns)} turns, "
        f"{script.total_chars} chars, ~{script.estimated_seconds:.0f}s\n"
    )
    body = "\n\n".join(f"{t.speaker}: {t.text}" for t in script.turns)
    return header + "\n" + body + "\n"


def _report_quality(script: PodcastScript) -> None:
    """Log the episode's texture, and flag drift without blocking on it.

    These are style signals, not defects: an episode outside the reference band
    still says the right thing, and refusing to publish it would leave the
    client with nothing. Reporting them makes the drift visible day after day so
    the prompt can be improved on real data.
    """
    report = assess_quality(script)
    shares = ", ".join(f"{k} {v:.0%}" for k, v in sorted(report.speech_share.items()))
    logger.info(
        "[%s] %d turns, %d chars, ~%.0fs — %s, cv %.2f",
        report.language,
        report.turns,
        report.chars,
        report.seconds,
        shares,
        report.length_cv,
    )
    for warning in report.warnings:
        logger.warning("[%s] off the house style: %s", report.language, warning)
    if report.warnings:
        sentry_sdk.capture_message(
            f"Podcast script [{report.language}] off the house style: "
            + " | ".join(report.warnings),
            level="warning",
        )


def _languages(choice: str) -> list[str]:
    return ["fr", "en"] if choice == "both" else [choice]


def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    session_date = datetime.strptime(args.session_date, "%Y-%m-%d").date()
    written: list[str] = []

    with get_session() as session:
        for language in _languages(args.language):
            try:
                inputs = read_episode_inputs(
                    session, session_date=session_date, language=language
                )
                script = write_script(inputs.data, inputs.narrative)
            except (EpisodeInputsMissingError, ScriptError) as exc:
                # Producer: it either succeeds fully or fails fully
                # (.claude/rules/pipeline-error-handling.md).
                logger.error("[%s] %s", language, exc)
                return 1

            rendered = _render(script)
            if args.out:
                path = _out_path(args.out, session_date, language)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(rendered)
                written.append(path)
                logger.info("[%s] wrote %s", language, path)
            elif args.script_only:
                print(rendered)

            _report_quality(script)
            if args.script_only:
                continue

            try:
                audio = get_synthesizer().synthesize(script)
            except SynthesisError as exc:
                logger.error("[%s] %s", language, exc)
                return 1

            filename = AUDIO_FILENAME.format(
                stem=session_date.strftime("%Y%m%d"),
                suffix="-EN" if language == "en" else "",
            )
            if args.no_upload:
                local = f"{(args.out or '.').rstrip('/')}/{filename}"
                with open(local, "wb") as handle:
                    handle.write(audio)
                written.append(local)
                logger.info(
                    "[%s] wrote %s (%.1f MB)", language, local, len(audio) / 1e6
                )
                continue

            folder = get_drive_audio_folder_id(shadow=not args.publish)
            uploader = DriveUploader(get_credentials_json())
            file_id = uploader.upload_bytes(audio, filename, "audio/wav", folder)
            written.append(filename)
            logger.info(
                "[%s] uploaded %s to the %s folder (id=%s)",
                language,
                filename,
                "WATCHED" if args.publish else "shadow",
                file_id,
            )

    if written:
        logger.info("SUCCESS — %s", json.dumps(written))
    return 0


def _out_path(out: str, session_date: date_cls, language: str) -> str:
    """``--out`` is always a directory: one language or both, same convention."""
    stem = session_date.strftime("%Y%m%d")
    suffix = "-EN" if language == "en" else ""
    return f"{out.rstrip('/')}/{stem}-CompassScript-Regime{suffix}.txt"


if __name__ == "__main__":
    sys.exit(main())

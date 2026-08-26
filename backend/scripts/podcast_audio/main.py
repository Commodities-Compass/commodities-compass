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

from dotenv import load_dotenv

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts.db import get_session
from scripts.podcast_audio.db_reader import (
    EpisodeInputsMissingError,
    read_episode_inputs,
)
from scripts.podcast_audio.script_writer import PodcastScript, ScriptError, write_script

load_dotenv(Path(__file__).parent.parent.parent / ".env")

logger = logging.getLogger(__name__)


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
        help="Write the script and stop. The only mode until the TTS adapter lands",
    )
    parser.add_argument(
        "--out",
        help="Write the script here instead of stdout (a directory for --language both)",
    )
    return parser.parse_args()


def _render(script: PodcastScript) -> str:
    header = (
        f"# {script.language.upper()} — {len(script.turns)} turns, "
        f"{script.total_chars} chars, ~{script.estimated_seconds:.0f}s\n"
    )
    body = "\n\n".join(f"{t.speaker}: {t.text}" for t in script.turns)
    return header + "\n" + body + "\n"


def _languages(choice: str) -> list[str]:
    return ["fr", "en"] if choice == "both" else [choice]


def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    if not args.script_only:
        logger.error(
            "Only --script-only is implemented; the TTS adapter is the next step"
        )
        return 2

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
                path = _out_path(args.out, session_date, language, args.language)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(rendered)
                written.append(path)
                logger.info("[%s] wrote %s", language, path)
            else:
                print(rendered)

            logger.info(
                "[%s] %d turns, %d chars, ~%.0fs",
                language,
                len(script.turns),
                script.total_chars,
                script.estimated_seconds,
            )

    if written:
        logger.info("SUCCESS — %s", json.dumps(written))
    return 0


def _out_path(out: str, session_date: date_cls, language: str, choice: str) -> str:
    if choice != "both":
        return out
    stem = session_date.strftime("%Y%m%d")
    suffix = "-EN" if language == "en" else ""
    return f"{out.rstrip('/')}/{stem}-CompassScript-Regime{suffix}.txt"


if __name__ == "__main__":
    sys.exit(main())

"""cc-publish-session — release the newest ready session to the dashboard.

The dashboard's "latest session" (the default/newest view) is gated on
``pl_session_release``: a session (row date T = ``data_date``) is exposed only
once a row exists here. This job stamps that row so the flip is **atomic** (all
sections + the NotebookLM audio at once) and can happen the **same evening** T,
instead of waiting for the T+1 calendar date the way the old
``MAX(display_date) <= today()`` gate did.

Per candidate session T (recent, has an indicator row, not yet released):

  * **Normal path** — data fully complete (indicator + press + meteo) AND the
    audio file is present in Drive → release with ``has_audio=true``. This is
    what fires the same evening once you upload the NotebookLM audio.
  * **Morning fallback** — if the audio never arrives, release anyway (data
    only, ``has_audio=false``) once we pass ``display_date(T)`` 09:00 UTC (the
    morning after T's data lands). This guarantees the dashboard never gets
    stuck on yesterday. The audio still plays when uploaded later — the audio
    endpoint fetches Drive independently; ``has_audio`` is only metadata.
  * Otherwise → skip (wait for audio / completeness).

Runs every 30 min across the evening→next-morning window (see scheduler.tf):
no-ops until a candidate is ready, then publishes. Idempotent (a released
session is never re-processed).

Usage:
    poetry run publish-session
    poetry run publish-session --dry-run --verbose
    poetry run publish-session --session-date 2026-07-06     # target one session
    poetry run publish-session --session-date 2026-07-06 --force   # release now, audio-agnostic

Cron (prod):
    */30 20-23,0-9 * * *    # evening (after the last Phase-B job) → 09:30 UTC next morning
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

import sentry_sdk
from sentry_sdk.crons import monitor
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper

configure_logging()
logger = logging.getLogger(__name__)

bootstrap_scraper("publish-session", script_file=__file__)

# Publish data-only by this UTC hour on display_date(T) if the audio never
# arrives — the safety net that keeps the dashboard from freezing on yesterday.
FALLBACK_HOUR_UTC = 9
# How far back to look for unreleased sessions. Bounds the candidate set so a
# fresh/empty pl_session_release doesn't try to release all of history (the
# dashboard's safe fallback already covers pre-first-release navigation).
DEFAULT_WINDOW_DAYS = 7


@dataclass(frozen=True)
class Decision:
    session_date: date
    action: str  # "release" | "skip"
    has_audio: bool
    reason: str


def _parse_args() -> argparse.Namespace:
    parser = build_base_argparser("Release ready sessions to the dashboard")
    parser.add_argument(
        "--session-date",
        type=date.fromisoformat,
        default=None,
        help=(
            "Publish only this session date (YYYY-MM-DD) instead of scanning the "
            "recent window. Still runs the completeness/audio checks unless "
            "--force is also passed."
        ),
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help=f"Lookback for unreleased sessions (default {DEFAULT_WINDOW_DAYS}).",
    )
    return parser.parse_args()


def _candidate_sessions(
    session: Session, window_days: int, only: date | None
) -> list[date]:
    """Recent sessions that have an indicator row and no release row yet.

    Keyed on ``pl_indicator_daily`` (the core signal): a session without a
    decision row can't be shown — the dashboard would fail to resolve its
    algorithm version — so it is never a publish candidate.
    """
    if only is not None:
        return [only]
    rows = session.execute(
        text(
            "SELECT DISTINCT i.date FROM pl_indicator_daily i "
            "WHERE i.date >= :start "
            "AND NOT EXISTS (SELECT 1 FROM pl_session_release r "
            "                WHERE r.session_date = i.date) "
            "ORDER BY i.date"
        ),
        {"start": date.today() - timedelta(days=window_days)},
    ).fetchall()
    return [r[0] for r in rows]


def _completeness(session: Session, d: date) -> tuple[bool, bool, bool]:
    """Return (has_core, has_press, has_meteo) for session ``d``."""
    row = session.execute(
        text(
            "SELECT "
            "EXISTS(SELECT 1 FROM pl_indicator_daily WHERE date = :d) AS core, "
            "EXISTS(SELECT 1 FROM pl_fundamental_article "
            "       WHERE date = :d AND is_active = true) AS press, "
            "EXISTS(SELECT 1 FROM pl_weather_observation WHERE date = :d) AS meteo"
        ),
        {"d": d},
    ).fetchone()
    return bool(row.core), bool(row.press), bool(row.meteo)


def _has_audio(d: date) -> bool:
    """True iff the served-version audio for session ``d`` exists in Drive.

    Degrades to False (logged) on a Drive error rather than crashing the run —
    the morning fallback still guarantees eventual release. This is a
    consumer-side check, not a producer, so graceful degradation is allowed.
    """
    from app.services.audio_service import get_audio_service

    try:
        info = asyncio.run(get_audio_service().get_audio_file_info(d))
        return info is not None
    except Exception as exc:  # noqa: BLE001 — degrade, don't crash the run
        logger.warning("Audio check failed for %s (treating as absent): %s", d, exc)
        return False


def _fallback_deadline(d: date) -> datetime:
    """``display_date(d)`` at 09:00 UTC — the morning after ``d``'s data lands.

    Uses ``get_display_date`` (= next trading day) so the deadline lands on the
    real morning the data surfaces: Mon session → Tue 09:00; Fri session (whose
    Phase-B rows are written Sunday eve) → Mon 09:00.
    """
    from scripts.db import get_display_date

    disp = get_display_date(d)
    return datetime.combine(disp, time(FALLBACK_HOUR_UTC), tzinfo=timezone.utc)


def _decide(session: Session, d: date, now: datetime, force: bool) -> Decision:
    has_core, has_press, has_meteo = _completeness(session, d)
    if not has_core:
        # Shouldn't happen (candidates come from pl_indicator_daily) but guard.
        return Decision(d, "skip", False, "no indicator row")

    fully_complete = has_press and has_meteo
    audio = _has_audio(d)

    if fully_complete and audio:
        return Decision(d, "release", True, "complete+audio")
    if force:
        return Decision(d, "release", audio, "manual --force")
    if now >= _fallback_deadline(d):
        # Past the 09:00 deadline: release regardless of what's still missing so
        # the dashboard never freezes on yesterday. State the actual gap.
        gap = "audio absent" if not audio else "data incomplete"
        return Decision(d, "release", audio, f"morning-fallback past deadline ({gap})")
    return Decision(
        d,
        "skip",
        audio,
        f"waiting (press={has_press} meteo={has_meteo} audio={audio})",
    )


def _release(session: Session, d: Decision) -> None:
    session.execute(
        text(
            "INSERT INTO pl_session_release (session_date, published_at, "
            "has_audio, source) VALUES (:d, now(), :audio, 'publish-session') "
            "ON CONFLICT (session_date) DO NOTHING"
        ),
        {"d": d.session_date, "audio": d.has_audio},
    )


@monitor(monitor_slug="publish-session")
def main() -> int:
    args = _parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    from scripts.db import get_session

    now = datetime.now(timezone.utc)
    released = 0

    logger.info("=" * 60)
    logger.info("Publish Session — dashboard release gate")
    logger.info("Now (UTC): %s | Mode: %s", now, "DRY RUN" if args.dry_run else "LIVE")
    logger.info("=" * 60)

    with get_session() as session:
        candidates = _candidate_sessions(session, args.window_days, args.session_date)
        if not candidates:
            logger.info("No unreleased sessions with data — nothing to do.")
            return 0

        logger.info("Candidates: %s", ", ".join(str(c) for c in candidates))
        for d in candidates:
            decision = _decide(session, d, now, args.force)
            if decision.action != "release":
                logger.info("SKIP  %s — %s", d, decision.reason)
                continue
            logger.info(
                "RELEASE %s — %s (has_audio=%s)",
                d,
                decision.reason,
                decision.has_audio,
            )
            if not args.dry_run:
                _release(session, decision)
                released += 1

        if not args.dry_run:
            session.commit()

    sentry_sdk.set_context(
        "publish_session",
        {"released": released, "candidates": len(candidates)},
    )
    logger.info("Done — %d session(s) released.", released)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

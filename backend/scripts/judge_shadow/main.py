"""cc-judge-shadow — compute the INERT judge macro overlay, log to pl_judge_shadow.

Campaign 6 Layer-3 overlay above ``regime``. Reads press + weather from the DB
(no Drive dependency), receives the base call from regime's shadow row, and
via a deterministic policy fused with an LLM verdict (o4-mini) may confirm,
MONITOR, or flip the base decision. Writes to ``pl_judge_shadow`` only —
NEVER to ``pl_indicator_daily``.

Phase-B daily cron gate: fires ~19:50 UTC every day (Sun-Thu eves target
Mon-Fri sessions); the in-agent ``phase_b_should_skip`` returns True on
Fri/Sat eve so a Sentry cron monitor treats a legit skip as success.

Usage (mirrors the other Phase-B jobs):
    poetry run judge-shadow-compute                          # cron: last completed session
    poetry run judge-shadow-compute --session-date 2026-08-03
    poetry run judge-shadow-compute --backfill-days 60       # last 60 sessions
    poetry run judge-shadow-compute --dry-run --verbose
    poetry run judge-shadow-compute --force                  # bypass the eve gate
"""

from __future__ import annotations

import logging
import sys
from datetime import date as date_cls
from datetime import datetime

import sentry_sdk
from sentry_sdk.crons import monitor

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper
from scripts.db import (
    get_previous_session_date,
    get_session,
    is_trading_day,
    phase_b_should_skip,
    resolve_phase_b_dates,
)
from scripts.judge_shadow.llm_openai import OpenAIJudgeLLM
from scripts.judge_shadow.runner import run_for_session

configure_logging()
logger = logging.getLogger(__name__)

bootstrap_scraper("judge-shadow", script_file=__file__)


def _parse_args():
    parser = build_base_argparser(
        "Compute the INERT judge macro overlay (Campaign 6 Layer-3)"
    )
    parser.add_argument(
        "--session-date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        help="Session date (data_date, the row date). Default: last completed session.",
    )
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=None,
        help="Compute the last N trading sessions. Ignored when --session-date is set.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the eve-of-trading gate (for manual reruns on non-eve days).",
    )
    return parser.parse_args()


def _resolve_target_dates(args) -> list[date_cls]:
    if args.session_date is not None:
        return [args.session_date]
    dates = resolve_phase_b_dates(session_date=None)
    if args.backfill_days is None:
        return [dates.data_date]
    # Walk back N-1 trading days from data_date.
    out: list[date_cls] = [dates.data_date]
    cur = dates.data_date
    for _ in range(args.backfill_days - 1):
        cur = get_previous_session_date(cur)
        out.append(cur)
    return list(reversed(out))


@monitor(monitor_slug="judge-shadow")
def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    # Phase-B eve-of-trading gate — clean skip (exit 0) on non-eve days when no
    # explicit --session-date is set. Sentry cron monitor reads exit 0 = success.
    if phase_b_should_skip(args.session_date, args.force):
        logger.info(
            "judge-shadow: not eve of a trading day + no --session-date/--force, skipping"
        )
        return 0

    if args.session_date is not None and not is_trading_day(args.session_date):
        raise ValueError(f"--session-date {args.session_date} is not a trading day.")

    dates = _resolve_target_dates(args)
    llm = OpenAIJudgeLLM() if not args.dry_run else _ProbeLLM()

    written = 0
    with get_session() as session:
        logger.info(
            "judge shadow: %d session(s) [%s..%s], dry_run=%s",
            len(dates),
            dates[0],
            dates[-1],
            args.dry_run,
        )
        for d in dates:
            written += run_for_session(
                session, data_date=d, llm=llm, dry_run=args.dry_run
            )
        if args.dry_run:
            logger.info("[DRY RUN] no writes")
        else:
            session.commit()
            logger.info("wrote %d judge shadow row(s)", written)

    sentry_sdk.set_context(
        "judge_shadow",
        {"n_dates": len(dates), "written": written, "dry_run": args.dry_run},
    )
    return 0


class _ProbeLLM:
    """Local no-op LLM for --dry-run: returns a NEUTRAL verdict without a call.

    We DO NOT hit the OpenAI endpoint on --dry-run so a smoke run stays free.
    The verdict is forced to NEUTRAL/conf=1 (matches the parser's grounding
    fallback when <2 evidence quotes are cited).
    """

    def judge(self, rendered: dict[str, str], *, session_date: str):
        from judge.llm import verdict_from_dict  # type: ignore

        _ = rendered, session_date  # silence unused
        return verdict_from_dict(
            {
                "suggested_direction": "NONE",
                "confidence": 1,
                "stance": "NEUTRAL",
                "is_anomaly": False,
                "evidence": [],
                "drift_summary": "[dry-run] no LLM call",
                "disconfirming_case": "",
                "key_risk": "",
            },
            prompt_version="judge_prompt_v1",
            model_id="dry-run",
        )


if __name__ == "__main__":
    sys.exit(main())

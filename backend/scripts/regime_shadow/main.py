"""cc-regime-shadow — INERT shadow-compute for regime + judge (Layer-3 overlay).

Campaign 6 bundled shadow job. Runs the two-layer regime router+specialist
(Layer-1+2, self-computing, writes ``pl_regime_shadow``) then invokes the judge
macro overlay (Layer-3, o4-mini LLM reading press + weather from the DB, writes
``pl_judge_shadow``). Neither layer writes a shared table; both are inert until
their respective shadow-evals clear.

Scheduled 19:50 UTC daily with a Phase-B eve-of-trading gate (mirrors
brief-ensemble / press-review / meteo): fires Sun-Thu eve for Mon-Fri targets,
skips Fri/Sat eve cleanly (exit 0, Sentry treats as success). See
scheduler.tf § regime-shadow for rationale.

Usage:
    poetry run regime-shadow-compute                          # cron: latest session
    poetry run regime-shadow-compute --session-date 2026-07-27
    poetry run regime-shadow-compute --backfill-days 60       # seed a shadow history
    poetry run regime-shadow-compute --dry-run --verbose
    poetry run regime-shadow-compute --no-judge               # regime only, skip judge
    poetry run regime-shadow-compute --force                  # bypass the eve gate
"""

from __future__ import annotations

import logging
import sys
from datetime import date as date_cls
from datetime import datetime

import pandas as pd
import sentry_sdk
from regime.data_loader_protocol import DecideRequest
from sentry_sdk.crons import monitor
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper
from scripts.db import get_session, phase_b_should_skip
from scripts.regime_shadow.db_writer import write_regime_shadow
from scripts.regime_shadow.feature_engine import build_selfcomputed_features
from scripts.regime_shadow.panel_loader import slice_panel
from scripts.regime_shadow.pipeline_loader import load_regime_pipeline_from_db

configure_logging()
logger = logging.getLogger(__name__)

bootstrap_scraper("regime-shadow", script_file=__file__)

ALGO_VERSION_NAME = "regime"
ALGO_VERSION = "1.0.0"


def _parse_args():
    parser = build_base_argparser(
        "Compute the INERT regime shadow decision (Campaign 6)"
    )
    parser.add_argument(
        "--session-date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        help="Session date to compute (YYYY-MM-DD). Default: latest chained session.",
    )
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=None,
        help="Compute the last N chained sessions (seed a shadow history). "
        "Ignored when --session-date is set.",
    )
    # --force is provided by build_base_argparser (bypasses the Phase-B eve-of-
    # trading gate for manual reruns on non-eve days).
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip the Layer-3 judge overlay (regime only). Use for regime-only "
        "backfills or when the LLM path is unavailable.",
    )
    return parser.parse_args()


def _resolve_version_id(session: Session):
    row = session.execute(
        text("SELECT id FROM pl_algorithm_version WHERE name = :n AND version = :v"),
        {"n": ALGO_VERSION_NAME, "v": ALGO_VERSION},
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"pl_algorithm_version {ALGO_VERSION_NAME}@{ALGO_VERSION} not found — "
            "apply sql/001_seed_regime_algorithm.sql (or its migration) first."
        )
    return row[0]


def _resolve_target_dates(features: pd.DataFrame, args) -> list[date_cls]:
    if args.session_date:
        return [args.session_date]
    all_dates = sorted(d.date() for d in features["date"])
    if not all_dates:
        raise RuntimeError("self-computed feature chain is empty — no sessions")
    n = args.backfill_days or 1
    return all_dates[-n:]


@monitor(monitor_slug="regime-shadow")
def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    # Phase-B eve-of-trading gate (moved to daily scheduling 2026-08-10 to bundle
    # the Layer-3 judge overlay). Skip cleanly on Fri/Sat eve when tomorrow is
    # not a trading day, unless --session-date / --force are set.
    if phase_b_should_skip(args.session_date, args.force):
        logger.info(
            "regime-shadow: not eve of a trading day + no --session-date/--force, skipping"
        )
        return 0

    written = 0
    judge_written = 0
    with get_session() as session:
        aid = _resolve_version_id(session)
        pipe = load_regime_pipeline_from_db(session, algorithm_version_id=aid)
        features = build_selfcomputed_features(session)
        dates = _resolve_target_dates(features, args)
        logger.info(
            "regime shadow: %d date(s) [%s..%s]", len(dates), dates[0], dates[-1]
        )
        for d in dates:
            panel, contract_id = slice_panel(features, d)
            dec = pipe.decide(
                DecideRequest(
                    today=pd.Timestamp(d),
                    contract_id=contract_id,
                    market_history=panel,
                )
            )
            logger.info(
                "  %s: %-6s regime=%-11s specialist=%-11s P(up)=%.4f",
                d,
                dec.decision,
                dec.regime,
                dec.specialist,
                dec.prob_up,
            )
            if not args.dry_run:
                written += write_regime_shadow(
                    session,
                    dec,
                    session_date=d,
                    contract_id=contract_id,
                    algorithm_version_id=aid,
                )
        if args.dry_run:
            logger.info("[DRY RUN] computed %d decision(s), no writes", len(dates))
        else:
            # Commit regime rows FIRST so judge can read them in the same session
            # (judge reads via pl_regime_shadow). If judge crashes below, regime
            # data is durable (pipeline-error-handling.md: producer fail-loud,
            # but regime already succeeded so its shadow row is safe).
            session.commit()
            logger.info("wrote %d regime shadow row(s)", written)

        # --- Layer 3: judge macro overlay ------------------------------------
        # Bundled in the same Cloud Run job. Reads press + weather from the DB
        # (no Drive dependency, no race with brief-generation timing), pulls the
        # regime row we just committed as base_call, calls OpenAI o4-mini, and
        # writes pl_judge_shadow. Fail-loud: an OpenAI outage or a missing
        # brief article crashes the whole job — the recovery path is
        # `poetry run judge-shadow-compute --session-date T` for retry.
        if not args.dry_run and not args.no_judge:
            from scripts.judge_shadow.llm_openai import OpenAIJudgeLLM
            from scripts.judge_shadow.runner import run_for_session

            llm = OpenAIJudgeLLM()
            for d in dates:
                judge_written += run_for_session(
                    session, data_date=d, llm=llm, dry_run=False
                )
            session.commit()
            logger.info("wrote %d judge shadow row(s)", judge_written)
        elif args.no_judge:
            logger.info("--no-judge set, skipping Layer-3 overlay")

    sentry_sdk.set_context(
        "regime_shadow",
        {
            "n_dates": len(dates),
            "regime_written": written,
            "judge_written": judge_written,
            "dry_run": args.dry_run,
            "no_judge": args.no_judge,
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

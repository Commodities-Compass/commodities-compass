"""cc-regime-shadow — compute the INERT regime decision, log to pl_regime_shadow.

Campaign 6, two-layer causal-router + condition-specialist algo. Runs in SHADOW:
each session it builds the front-month derived-indicator panel, routes to one of
6 specialists, predicts J+1 direction, and writes the decision to
``pl_regime_shadow`` for the §6 shadow-eval. It NEVER writes
``pl_indicator_daily.decision`` and is NEVER served — promotion is a Compass flag
flip AFTER shadow clears the 0.50 hit-rate floor over >=30 sessions.

Usage:
    poetry run regime-shadow-compute                          # latest chained session
    poetry run regime-shadow-compute --session-date 2026-07-27
    poetry run regime-shadow-compute --backfill-days 60       # seed a shadow history
    poetry run regime-shadow-compute --dry-run --verbose
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
from scripts.db import get_session
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

    written = 0
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
            session.commit()
            logger.info("wrote %d regime shadow row(s)", written)

    sentry_sdk.set_context(
        "regime_shadow",
        {"n_dates": len(dates), "written": written, "dry_run": args.dry_run},
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

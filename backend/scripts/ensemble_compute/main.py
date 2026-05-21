"""cc-ensemble-compute — daily C5 ensemble decision.

Runs at 19:18 UTC weekdays (between cc-compute-indicators at 19:15 and
cc-daily-analysis at 19:20). Reads from prod tables, instantiates
``EnsemblePipeline``, writes 3 tables.

Usage:
    poetry run ensemble-compute                          # today, active contract
    poetry run ensemble-compute --date 2026-05-15
    poetry run ensemble-compute --dry-run --verbose
    poetry run ensemble-compute --date 2026-05-15 --force

Per CAMPAIGN_5_PROD_DEPLOYMENT.md §6.2:
    - Reads pl_contract_data_daily × pl_derived_indicators for market_history.
    - Reads pl_orchestrator_decision + pl_specialist_prediction for the
      wrapper's trailing window.
    - Uses MacroSignal stub (neutral) until the sentiment pipeline is live.
    - Writes pl_specialist_prediction (14), pl_orchestrator_decision (1),
      pl_indicator_daily (1 row UPSERT, decision = wrapped_decision).
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from datetime import date, datetime, timezone

import pandas as pd
import sentry_sdk
from ensemble.artifact_io import DBArtifactLoader
from ensemble.data_loader_protocol import DecideRequest
from ensemble.ensemble_pipeline import EnsemblePipeline
from sentry_sdk.crons import monitor
from sqlalchemy import text

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper
from scripts.contract_resolver import resolve_active, resolve_active_at_date
from scripts.ensemble_compute.cluster_mapping_loader import load_cluster_mapping
from scripts.ensemble_compute.compass_wrapper import (
    DEFAULT_DISPERSION_WITH_ACC_THRESHOLD,
    CompassTransitionWrapper,
)
from scripts.ensemble_compute.db_loader import (
    load_macro_signal,
    load_market_history,
    load_recent_orchestrator_decisions,
    load_recent_specialist_votes,
)
from scripts.ensemble_compute.db_writer import write_decision


class _SQLAlchemy2SessionAdapter:
    """Adapter so R&D's ``DBArtifactLoader`` works with SQLAlchemy 2.0.

    The R&D loader was written for SQLAlchemy 1.4-style sessions that
    accept raw SQL strings in ``session.execute(sql, params)``. SQLAlchemy
    2.0 requires explicit ``text()`` wrapping; this adapter intercepts the
    call and wraps. Identity-preserving for all other Session attributes.
    """

    def __init__(self, session) -> None:
        self._session = session

    def execute(self, sql, params=None):
        if isinstance(sql, str):
            sql = text(sql)
        if params is None:
            return self._session.execute(sql)
        return self._session.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._session, name)


configure_logging()
logger = logging.getLogger(__name__)

bootstrap_scraper("ensemble-compute", script_file=__file__)


ALGO_VERSION_NAME = "ensemble_v1_softgate_wrapper"
# Lookback for market_history: enough to cover GARCH features (~500d) plus
# rolling 12m vol/return windows for the structural priors (260d). 600d is a
# safe margin.
MARKET_LOOKBACK_DAYS = 600


def _parse_args() -> argparse.Namespace:
    parser = build_base_argparser("Compute C5 ensemble decision (soft-gate + wrapper)")
    parser.add_argument(
        "--date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        help="Target date (default: today UTC, business day)",
    )
    parser.add_argument(
        "--historical",
        action="store_true",
        help=(
            "Resolve the contract via front-month-by-OI on --date instead of "
            "the current ref_contract.is_active. Use this for backfills where "
            "the active contract on the target date wasn't yet today's roll."
        ),
    )
    return parser.parse_args()


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _resolve_algorithm_version_id(session, name: str) -> uuid.UUID:
    row = session.execute(
        text("SELECT id FROM pl_algorithm_version WHERE name = :name LIMIT 1"),
        {"name": name},
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"pl_algorithm_version row missing for name={name!r}. "
            "Run Alembic migration l6g7h8i9j0k1 to seed."
        )
    return row[0]


def _latest_training_month(session, algorithm_version_id: uuid.UUID) -> str:
    """Pick the most recent training_month from pl_model_artifact specialists.

    Frozen at 2026-04 in v1.0.0; monthly retrains will append new rows.
    """
    row = session.execute(
        text(
            "SELECT MAX(training_month) FROM pl_model_artifact "
            "WHERE algorithm_version_id = :aid "
            "AND artifact_kind = 'specialist_model' "
            "AND training_month IS NOT NULL"
        ),
        {"aid": algorithm_version_id},
    ).fetchone()
    if row is None or row[0] is None:
        raise RuntimeError(
            "No specialist_model rows in pl_model_artifact — "
            "run cc-ensemble-bootstrap-artifacts first."
        )
    return str(row[0])


@monitor(monitor_slug="ensemble-compute")
def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    from scripts.db import get_session, should_skip_non_trading_day

    if should_skip_non_trading_day(force=args.force):
        return 0

    target_date = args.date or _today_utc()

    logger.info("=" * 60)
    logger.info("Ensemble Compute (C5 v1.0.0)")
    logger.info("Date: %s", target_date)
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("=" * 60)

    try:
        with get_session() as session:
            if args.historical:
                contract_id = resolve_active_at_date(session, target_date)
                logger.info(
                    "Historical mode: resolved front-month-by-OI for %s",
                    target_date,
                )
            else:
                contract_id = resolve_active(session)
            algo_version_id = _resolve_algorithm_version_id(session, ALGO_VERSION_NAME)
            training_month = _latest_training_month(session, algo_version_id)
            cluster_mapping = load_cluster_mapping(session, algo_version_id)
            logger.info(
                "Resolved: contract=%s algo_version=%s training_month=%s",
                contract_id,
                algo_version_id,
                training_month,
            )

            loader = DBArtifactLoader(
                _SQLAlchemy2SessionAdapter(session), str(algo_version_id)
            )
            pipeline = EnsemblePipeline.from_loader(
                loader,
                training_month=training_month,
                cluster_mapping=cluster_mapping,
            )
            # Swap the vendor wrapper for the Compass override. The vendor
            # combines its 4 detectors with a pure OR — empirically too
            # aggressive: cluster_dispersion alone vetoed 28/63 commits on the
            # 2026 backfill while running_acc_5d averaged 0.981. The Compass
            # wrapper relaxes the dispersion-only veto when running_acc is
            # healthy. See compass_wrapper.py for the full rule.
            vendor_wrapper = pipeline.wrapper
            pipeline.wrapper = CompassTransitionWrapper(
                config=vendor_wrapper.config,
                cluster_mapping=vendor_wrapper.cluster_mapping,
                dispersion_with_acc_threshold=DEFAULT_DISPERSION_WITH_ACC_THRESHOLD,
            )
            logger.info(
                "Pipeline assembled: %d specialists + soft-gate + Compass wrapper (threshold=%.2f)",
                len(pipeline.specialists),
                DEFAULT_DISPERSION_WITH_ACC_THRESHOLD,
            )

            market = load_market_history(
                session,
                end_date=target_date,
                contract_id=contract_id,
                lookback_days=MARKET_LOOKBACK_DAYS,
            )
            recent_decisions = load_recent_orchestrator_decisions(
                session,
                end_date=target_date,
                contract_id=contract_id,
                algorithm_version_id=algo_version_id,
            )
            recent_votes = load_recent_specialist_votes(
                session,
                end_date=target_date,
                contract_id=contract_id,
                algorithm_version_id=algo_version_id,
            )
            macro = load_macro_signal(session, today=target_date)

            request = DecideRequest(
                today=pd.Timestamp(target_date),
                contract_id=str(contract_id),
                market_history=market,
                recent_decisions=recent_decisions,
                recent_votes=recent_votes,
                macro=macro,
            )
            decision = pipeline.decide(request)

            logger.info(
                "Decision: soft_gate=%s wrapped=%s (fired_run_acc=%s, fired_disp=%s)",
                decision.soft_gate_decision.decision,
                decision.wrapped_decision,
                decision.wrapper_fired_running_acc,
                decision.wrapper_fired_cluster_dispersion,
            )
            logger.info(
                "Diagnostics: running_acc_5d=%.3f winter=%+d spring=%+d",
                decision.running_acc_5d
                if decision.running_acc_5d == decision.running_acc_5d
                else float("nan"),
                decision.winter_vote_signed,
                decision.spring_vote_signed,
            )

            diagnostics = _build_diagnostics(decision, recent_decisions)

            if args.dry_run:
                logger.info("[DRY RUN] Skipping DB writes")
                return 0

            counts = write_decision(
                session,
                target_date=target_date,
                contract_id=contract_id,
                algorithm_version_id=algo_version_id,
                decision=decision,
                diagnostics=diagnostics,
            )
            session.commit()
            logger.info(
                "Wrote: %d specialist + %d orchestrator + %d indicator_daily rows",
                counts["specialist"],
                counts["orchestrator"],
                counts["indicator_daily"],
            )

        sentry_sdk.set_context(
            "ensemble_decision",
            {
                "target_date": target_date.isoformat(),
                "wrapped_decision": decision.wrapped_decision,
                "soft_gate_decision": decision.soft_gate_decision.decision,
                "wrapper_fired_running_acc": decision.wrapper_fired_running_acc,
                "wrapper_fired_dispersion": decision.wrapper_fired_cluster_dispersion,
                "n_specialists": len(decision.per_specialist_votes),
            },
        )

        logger.info("SUCCESS — ensemble-compute done for %s", target_date)
        return 0

    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # noqa: BLE001 — fail-loud top-level
        logger.exception("ensemble-compute failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


def _build_diagnostics(decision, recent_decisions) -> dict:
    """Pull supplementary fields not on EnsembleDecision into a flat dict.

    Used by db_writer to populate pl_orchestrator_decision diagnostics
    columns that aren't directly exposed on EnsembleDecision (weights_sum,
    n_committed_specialists, fired_trend, fired_three_way, etc.).
    """
    sg = decision.soft_gate_decision
    return {
        # From soft-gate decision object (read defensively — names may shift)
        "weights_sum": getattr(sg, "weights_sum", None),
        "n_committed_specialists": getattr(sg, "n_committed_specialists", None),
        "wrapper_active": (
            decision.wrapper_fired_running_acc
            or decision.wrapper_fired_cluster_dispersion
        ),
        # Detectors absent in v1.0.0 (use_trend_conflict=False,
        # use_three_way_disagreement=False per tuned_configs JSON). Storing
        # ``False`` is acceptable since the column is NOT NULL — they truly
        # did not fire because they're not present. If v1.1.0 enables them,
        # the column will accept actual True/False values; the v1.0.0 rows
        # are then unambiguously "False because absent".
        "fired_trend": False,
        "fired_three_way": False,
        "macro_half_life_days": None,
    }


if __name__ == "__main__":
    sys.exit(main())

"""cc-ensemble-compute — daily C5 ensemble decision (P2b Phase B).

Runs at 19:18 UTC every day, gated on ``is_eve_of_trading_day()`` so it
fires Mon-Thu eve and Sunday eve, skipping Friday + Saturday eves. The
move from weekday-only to daily-gated (PR #35) is what lets the
MacroSignal incorporate news that broke during the weekend: Sunday 19:05
press-review writes pl_article_segment with ``article_date = Friday``,
and Sunday 19:18 ensemble-compute reads it before deciding Friday's row.

Sequencing on a typical evening (eve of next session): cc-meteo-agent
(19:00) → cc-press-review-agent (19:05) → cc-ensemble-compute (19:18) →
cc-daily-analysis (19:20) → cc-ensemble-explainer (19:25) → briefs.

Usage:
    poetry run ensemble-compute                              # cron default = last completed session
    poetry run ensemble-compute --session-date 2026-05-15    # explicit row date, bypasses gate
    poetry run ensemble-compute --dry-run --verbose
    poetry run ensemble-compute --session-date 2026-05-15 --force

Per CAMPAIGN_5_PROD_DEPLOYMENT.md §6.2:
    - Reads pl_contract_data_daily × pl_derived_indicators for market_history.
    - Reads pl_orchestrator_decision + pl_specialist_prediction for the
      wrapper's trailing window.
    - Reads pl_article_segment (90d window, confidence ≥ 0.70) → MacroSignal
      via MacroEventLayer.
    - Writes pl_specialist_prediction (14), pl_orchestrator_decision (1),
      pl_indicator_daily (1 row UPSERT, decision = wrapped_decision).
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
import uuid
from datetime import datetime

import pandas as pd
import sentry_sdk
from ensemble.artifact_io import DBArtifactLoader
from ensemble.data_loader_protocol import DecideRequest
from ensemble.ensemble_pipeline import EnsemblePipeline
from ensemble.orchestrator.soft_gate import SoftGateOrchestrator
from sentry_sdk.crons import monitor
from sqlalchemy import text

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper
from scripts.contract_resolver import resolve_active
from scripts.front_month import front_month_for_date
from scripts.ensemble_compute.cluster_mapping_loader import (
    REGIME_MONITOR_ATR_PCTL_KEY,
    SOFTGATE_ALPHA_MACRO_CAP_KEY,
    load_cluster_mapping,
    load_compass_wrapper_threshold,
    load_optional_config_float,
    load_wrapper_config,
)
from scripts.ensemble_compute.compass_wrapper import CompassTransitionWrapper
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
        "--session-date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        help=(
            "Session date to (re)generate, YYYY-MM-DD — the WHERE/UPDATE key on "
            "pl_orchestrator_decision/pl_specialist_prediction/pl_indicator_daily. "
            "Default (cron): the last completed trading session. Explicit "
            "--session-date bypasses the eve-of-trading-day gate (backfills, reruns)."
        ),
    )
    parser.add_argument(
        "--historical",
        action="store_true",
        help=(
            "Resolve the contract via front-month-by-OI on --session-date "
            "instead of the current ref_contract.is_active. Use this for "
            "backfills where the active contract on that session wasn't yet "
            "today's roll."
        ),
    )
    return parser.parse_args()


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

    from scripts.db import get_session, phase_b_should_skip, resolve_phase_b_dates

    # P2b Phase B gate: skip cleanly when the upcoming day is not a trading
    # session. Explicit --session-date or --force bypass the gate (backfills,
    # reruns). Eve-of-trading semantics so Sunday eve fires for Monday's
    # session — letting the MacroSignal pick up weekend press-review writes
    # that land on Friday's data_date.
    if phase_b_should_skip(args.session_date, args.force):
        logger.info("Phase-B gate: tomorrow is not a trading day — skipping cleanly.")
        return 0

    # ``data_date`` = the session date this run computes for = the WHERE/UPDATE
    # key on pl_orchestrator_decision / pl_specialist_prediction /
    # pl_indicator_daily. Cron: the most recent completed session (= today
    # mid-week, = Friday on Sunday eve). ensemble-compute never uses target_date
    # (T+1) — it only writes the row, so we take data_date from the pair.
    data_date = resolve_phase_b_dates(args.session_date).data_date

    logger.info("=" * 60)
    logger.info("Ensemble Compute (C5 v1.0.0)")
    logger.info("Date: %s", data_date)
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("=" * 60)

    try:
        with get_session() as session:
            if args.historical:
                contract_id = front_month_for_date(session, data_date)
                logger.info(
                    "Historical mode: resolved front-month from roll calendar for %s",
                    data_date,
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
            # healthy. Threshold lives in pl_algorithm_config (config-as-data
            # per north-star rule #4) — see migration o9j0k1l2m3n4.
            compass_threshold = load_compass_wrapper_threshold(session, algo_version_id)
            vendor_wrapper = pipeline.wrapper
            # Config-as-data: the frozen tpw_v1 artifact gives R&D defaults, but the
            # ``wrapper_*`` rows in pl_algorithm_config are authoritative — they let us
            # enable detectors (e.g. trend-conflict) and tune thresholds without
            # re-freezing the artifact. ``_build_diagnostics`` reads the real fired_trend
            # / fired_three_way from the wrapper now, so no detector is hardcoded off.
            wrapper_config = load_wrapper_config(session, algo_version_id)
            pipeline.wrapper = CompassTransitionWrapper(
                config=wrapper_config,
                cluster_mapping=vendor_wrapper.cluster_mapping,
                dispersion_with_acc_threshold=compass_threshold,
            )
            logger.info(
                "Pipeline assembled: %d specialists + soft-gate + Compass wrapper (threshold=%.2f)",
                len(pipeline.specialists),
                compass_threshold,
            )

            # Compass lever — alpha_macro cap (config-as-data; absent row → OFF).
            # The tuned alpha_macro=1.477 makes the macro signal a HARD gate: with α>1
            # a specialist voting against macro_direction gets weight (1−α)→clamped 0
            # = excluded, which forced unanimous HEDGE (net_score=−1.000) through the
            # May-2026 rebound. Capping α<1.0 keeps (1+α·align)>0 so contrarians are
            # down-weighted, never zeroed. Tunable / disable-able via pl_algorithm_config.
            alpha_cap = load_optional_config_float(
                session, algo_version_id, SOFTGATE_ALPHA_MACRO_CAP_KEY
            )
            if (
                alpha_cap is not None
                and pipeline.soft_gate.config.alpha_macro > alpha_cap
            ):
                logger.info(
                    "Applying alpha_macro cap: %.4f -> %.4f",
                    pipeline.soft_gate.config.alpha_macro,
                    alpha_cap,
                )
                pipeline.soft_gate = SoftGateOrchestrator(
                    config=dataclasses.replace(
                        pipeline.soft_gate.config, alpha_macro=alpha_cap
                    ),
                    base_accuracy=pipeline.soft_gate.base_accuracy,
                )

            market = load_market_history(
                session,
                end_date=data_date,
                contract_id=contract_id,
                lookback_days=MARKET_LOOKBACK_DAYS,
            )
            recent_decisions = load_recent_orchestrator_decisions(
                session,
                end_date=data_date,
                contract_id=contract_id,
                algorithm_version_id=algo_version_id,
            )
            recent_votes = load_recent_specialist_votes(
                session,
                end_date=data_date,
                contract_id=contract_id,
                algorithm_version_id=algo_version_id,
            )
            macro = load_macro_signal(session, today=data_date)

            request = DecideRequest(
                today=pd.Timestamp(data_date),
                contract_id=str(contract_id),
                market_history=market,
                recent_decisions=recent_decisions,
                recent_votes=recent_votes,
                macro=macro,
            )
            decision = pipeline.decide(request)

            # Compass lever — regime-MONITOR (config-as-data; absent row → OFF).
            # EV result: in top-vol-percentile regimes the ensemble's directional
            # accuracy (~76%) sits below the score-grid break-even (~81%), so publishing
            # a direction is EV-negative vs MONITOR. When atr%-percentile > threshold we
            # override a committed decision to MONITOR. ``decision_wrapped`` keeps the
            # wrapper's output (audit); the PUBLISHED signal (pl_indicator_daily) is the
            # regime-adjusted ``final_decision``; ``regime_monitor_fired`` records it.
            regime_threshold = load_optional_config_float(
                session, algo_version_id, REGIME_MONITOR_ATR_PCTL_KEY
            )
            regime_monitor_fired = _regime_monitor_fires(
                market, regime_threshold, decision.wrapped_decision
            )
            final_decision = (
                "MONITOR" if regime_monitor_fired else decision.wrapped_decision
            )
            if regime_monitor_fired:
                logger.info(
                    "regime-MONITOR fired: wrapped=%s -> published MONITOR "
                    "(atr%%-pctl > %.2f)",
                    decision.wrapped_decision,
                    regime_threshold,
                )

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

            diagnostics = _build_diagnostics(
                decision, recent_decisions, pipeline.wrapper, macro
            )
            diagnostics["regime_monitor_fired"] = regime_monitor_fired

            if args.dry_run:
                logger.info("[DRY RUN] Skipping DB writes")
                return 0

            counts = write_decision(
                session,
                data_date=data_date,
                contract_id=contract_id,
                algorithm_version_id=algo_version_id,
                decision=decision,
                diagnostics=diagnostics,
                final_decision=final_decision,
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
                "data_date": data_date.isoformat(),
                "wrapped_decision": decision.wrapped_decision,
                "soft_gate_decision": decision.soft_gate_decision.decision,
                "wrapper_fired_running_acc": decision.wrapper_fired_running_acc,
                "wrapper_fired_dispersion": decision.wrapper_fired_cluster_dispersion,
                "n_specialists": len(decision.per_specialist_votes),
            },
        )

        logger.info("SUCCESS — ensemble-compute done for %s", data_date)
        return 0

    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # noqa: BLE001 — fail-loud top-level
        logger.exception("ensemble-compute failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


# Piecewise half-life from |surprise| — mirrors ensemble.macro_events.pipeline
# MacroEventLayer._half_life_for (HALF_LIFE_BREAKS = (0.30, 0.60)). Replicated here
# (not imported) because load_macro_signal collapses MacroEventScore → MacroSignal and
# drops half_life_days; recomputing from surprise is cheaper than threading it through
# the vendor Protocol. Keep in sync with the layer if R&D retunes the breaks.
_MACRO_HALF_LIFE_BREAKS = (0.30, 0.60)


def _macro_half_life_days(surprise: float) -> int:
    s = abs(float(surprise))
    if s < _MACRO_HALF_LIFE_BREAKS[0]:
        return 1
    if s < _MACRO_HALF_LIFE_BREAKS[1]:
        return 3
    return 7


_REGIME_ATR_WINDOW = 252  # trailing sessions for the causal atr%-percentile rank


def _regime_monitor_fires(
    market: pd.DataFrame, threshold: float | None, wrapped_decision: str
) -> bool:
    """True when today's ATR%-percentile exceeds ``threshold`` and the wrapper committed.

    OFF when ``threshold`` is None (config row absent) or the decision is already MONITOR.
    atr% = atr_14d / close; the percentile is the causal rank of today's value within the
    trailing ``_REGIME_ATR_WINDOW`` rows of market_history (last row is today, per
    load_market_history's end_date assertion). Returns False if there isn't enough
    history for a stable percentile.
    """
    if threshold is None or wrapped_decision == "MONITOR":
        return False
    m = market.dropna(subset=["atr_14d", "close"])
    if len(m) < 60:
        return False
    atr_pct = (m["atr_14d"].astype(float) / m["close"].astype(float)).to_numpy()
    window = atr_pct[-_REGIME_ATR_WINDOW:]
    pctl = float((window <= atr_pct[-1]).mean())
    return pctl > float(threshold)


def _build_diagnostics(decision, recent_decisions, wrapper, macro) -> dict[str, object]:
    """Pull supplementary fields not on EnsembleDecision into a flat dict.

    Used by db_writer to populate pl_orchestrator_decision diagnostics columns that
    aren't directly exposed on EnsembleDecision (weights_sum, n_committed_specialists,
    fired_trend, fired_three_way, macro_half_life_days).

    ``wrapper_active`` is derived from the wrapped decision changing the soft-gate
    decision — NOT from the raw fired_* flags. This way the Compass override of
    dispersion-only vetoes is correctly reflected: the fired_* flags stay TRUE in audit
    (the detectors did fire), but wrapper_active is FALSE when Compass released the veto.

    ``fired_trend`` / ``fired_three_way`` are read from the wrapper's captured today-row
    states (``CompassTransitionWrapper.last_fired_*``) — no longer hardcoded False, so
    enabling the trend-conflict detector via config is correctly audited.
    """
    _ = recent_decisions  # kept for ABI compat; future detectors may use it
    sg = decision.soft_gate_decision
    return {
        # From soft-gate decision object (read defensively — names may shift)
        "weights_sum": getattr(sg, "weights_sum", None),
        "n_committed_specialists": getattr(sg, "n_committed_specialists", None),
        "wrapper_active": decision.wrapped_decision != sg.decision,
        # Real detector states captured from today's wrapped row (config-driven now).
        "fired_trend": bool(getattr(wrapper, "last_fired_trend", False)),
        "fired_three_way": bool(getattr(wrapper, "last_fired_three_way", False)),
        # Computed from macro surprise (was hardcoded None — a pipeline-continuity leak).
        "macro_half_life_days": _macro_half_life_days(getattr(macro, "surprise", 0.0)),
    }


if __name__ == "__main__":
    sys.exit(main())

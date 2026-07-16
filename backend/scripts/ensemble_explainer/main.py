"""cc-ensemble-explainer — LLM narrative writer on the ensemble row of pl_indicator_daily.

Thin wrapper around scripts.daily_analysis.db_analysis_engine.DBAnalysisEngine.
The legacy daily-analysis pipeline already has built-in auto-alignment on the
ensemble row when no algorithm_version_name is pinned : when
pl_orchestrator_decision has a row for the (date, contract) at the ensemble
algorithm version, the engine resolves writes to the ensemble row instead of
the legacy row, and Call#2 injects the ensemble diagnostics block + force-aligns
the LLM decision to decision_wrapped.

This wrapper invokes that auto-align path, so the ensemble row is enriched with
the SAME narrative structure as the legacy row (eco + confidence + direction +
conclusion in the long-form "> ... • ... > A SURVEILLER AUJOURD'HUI: ..." that
the frontend recommendation parser expects). The legacy daily-analysis job
(cc-daily-analysis) stays pinned to legacy via --algorithm-version legacy in
deploy.yml and continues to populate the legacy row independently.

Pre-conditions (fail-loud per .claude/rules/pipeline-error-handling.md):
  * cc-ensemble-compute must have written the ensemble row in
    pl_orchestrator_decision + pl_indicator_daily for the resolved data_date.
  * cc-compute-indicators must have written z-scores on the ensemble row
    (the engine's _compute_final_indicator reads them).

Date semantics (P2b):
  * target_date  = upcoming trading session the narrative addresses
  * data_date    = previous_session(target_date) = the row date that
                   compute-indicators + ensemble-compute wrote at, matching
                   the dashboard's session_date convention.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date as date_type
from pathlib import Path

import sentry_sdk
from dotenv import load_dotenv
from sentry_sdk.crons import monitor
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGE_CLI_CHOICES,
    expand_languages,
)
from app.core.sentry import init_sentry
from scripts.daily_analysis.db_analysis_engine import (
    AnalysisWriteError,
    DBAnalysisEngine,
)
from scripts.ensemble_explainer.config import (
    ALGORITHM_NAME,
    ALGORITHM_VERSION,
    LOG_FORMAT,
)

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).parent.parent.parent / ".env")
init_sentry("ensemble-explainer")


class EnsembleRowMissingError(RuntimeError):
    """Raised when cc-ensemble-compute has not (yet) written the ensemble row.

    Fail-loud : the explainer cannot enrich a row that doesn't exist. If we
    let the engine fall through to legacy fallback we'd write the narrative
    to the wrong row, polluting the legacy track and silencing the upstream
    failure.
    """


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ensemble narrative writer — wraps the legacy DBAnalysisEngine "
            "with auto-align on the ensemble row."
        )
    )
    parser.add_argument("--dry-run", action="store_true", help="Log only, no DB write")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass eve-of-trading-day gate (backfills / manual reruns)",
    )
    parser.add_argument(
        "--session-date",
        type=date_type.fromisoformat,
        default=None,
        help=(
            "Session date to (re)generate, YYYY-MM-DD (= the row date the "
            "narrative enriches). Default (cron): the last completed trading "
            "session. Explicit --session-date bypasses the eve-of-trading-day "
            "gate (backfills, manual reruns)."
        ),
    )
    parser.add_argument(
        "--contract",
        default=None,
        help="Contract code (default: active contract from DB)",
    )
    # Content language of the ensemble narrative's 3 prose fields. Default 'fr'
    # (source-of-truth ensemble row). 'en' copies the numbers from the fr
    # ensemble row and writes only EN prose (D3-EN-rows) — the fr explainer must
    # have written first.
    parser.add_argument(
        "--language",
        choices=LANGUAGE_CLI_CHOICES,
        default="fr",
        help=(
            "Content language of the narrative prose fields (default: fr). "
            "'both' runs fr then en in one execution (fr first — en copies "
            "the fr ensemble row)."
        ),
    )
    return parser.parse_args()


def _assert_ensemble_row_present(
    session: Session, data_date: date_type, contract_code: str
) -> None:
    """Pre-flight : confirm cc-ensemble-compute has written the ensemble row.

    Without this check the engine's auto-align would silently fall back to
    the legacy row when no ensemble row exists, breaking the dual-track
    invariant. Fail-loud early before wasting 2 gpt-4-turbo calls.

    The row that must exist is always the source-of-truth (fr) ensemble row:
    the fr explainer enriches it in place, and an en run copies its numbers
    (D3-EN-rows). So this gate is language-independent — it always checks fr.
    """
    row = session.execute(
        text(
            """
            SELECT 1
            FROM pl_indicator_daily i
            JOIN ref_contract c ON i.contract_id = c.id
            JOIN pl_algorithm_version v ON i.algorithm_version_id = v.id
            WHERE c.code = :contract
              AND v.name = :ensemble_algo
              AND v.version = :ensemble_ver
              AND i.date = :data_date
              AND i.language = :src_language
            LIMIT 1
            """
        ),
        {
            "contract": contract_code,
            "ensemble_algo": ALGORITHM_NAME,
            "ensemble_ver": ALGORITHM_VERSION,
            "data_date": data_date,
            "src_language": DEFAULT_LANGUAGE.value,
        },
    ).fetchone()
    if row is None:
        raise EnsembleRowMissingError(
            f"No ensemble row in pl_indicator_daily for date={data_date} "
            f"contract={contract_code} algo={ALGORITHM_NAME} v{ALGORITHM_VERSION}. "
            "cc-ensemble-compute must run first."
        )


@monitor(monitor_slug="ensemble-explainer")
def main() -> int:
    args = _parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    from scripts.contract_resolver import resolve_active_code
    from scripts.db import (
        get_session,
        phase_b_should_skip,
        resolve_phase_b_dates,
    )

    # Phase-B date pair — single source of truth (scripts/db.py). The narrative
    # addresses target_date (upcoming session) but enriches the ensemble row at
    # data_date (= last completed session).
    if phase_b_should_skip(args.session_date, args.force):
        logger.info("Phase-B gate: tomorrow is not a trading day — skipping cleanly.")
        return 0

    dates = resolve_phase_b_dates(args.session_date)
    target_date: date_type = dates.target_date
    data_date: date_type = dates.data_date

    logger.info("=" * 60)
    logger.info("Ensemble Explainer (DBAnalysisEngine auto-align wrapper)")
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("Language: %s", args.language)
    logger.info(
        "Target session: %s | Data session (row date): %s", target_date, data_date
    )
    logger.info("=" * 60)

    try:
        contract_code = args.contract
        if contract_code is None:
            with get_session() as session:
                contract_code = resolve_active_code(session)
            logger.info("Resolved active contract: %s", contract_code)

        # Pre-flight : ensemble row must exist
        with get_session() as session:
            _assert_ensemble_row_present(session, data_date, contract_code)
        logger.info("Pre-flight OK — ensemble row present at date=%s", data_date)

        # Invoke the legacy DBAnalysisEngine WITHOUT pinning algorithm_version
        # → engine.run() auto-aligns on the ensemble row in
        # pl_orchestrator_decision, builds the ensemble-aware Call #2 voice
        # prompt (voice_prompts.build_call2_voice_prompt_ensemble, which injects
        # the diagnostics block), and writes the narrative to the ensemble row.
        #
        # 'both' → fr first (its own session commits), then en (copies the fr
        # ensemble row). A failure in any language raises and is caught below;
        # any already-committed language is left intact.
        db_url = str(settings.DATABASE_SYNC_URL)
        sqla_engine = create_engine(db_url)
        result = None
        for lang in expand_languages(args.language):
            with Session(sqla_engine) as session:
                db_engine = DBAnalysisEngine(session)  # NO algorithm_version_name
                result = db_engine.run(
                    target_date=target_date,
                    contract_code=contract_code,
                    data_date=data_date,
                    dry_run=args.dry_run,
                    language=str(lang),
                )

            if not result.ensemble_aligned:
                # Defense in depth : the pre-flight already guarantees the
                # ensemble row exists, so reaching this branch would mean the
                # engine resolved to a different row (a race between pre-flight
                # and engine.run).
                raise EnsembleRowMissingError(
                    f"DBAnalysisEngine did NOT auto-align on ensemble for "
                    f"date={data_date} contract={contract_code} language={lang}. "
                    "Investigate pl_orchestrator_decision freshness."
                )
            logger.info("Ensemble narrative written for language=%s", lang)

        # `expand_languages` never returns empty, so result is always set here.
        assert result is not None

        sentry_sdk.set_context(
            "ensemble_explainer",
            {
                "target_date": target_date.isoformat(),
                "data_date": data_date.isoformat(),
                "language": args.language,
                "decision": result.trading.decision,
                "confidence": result.trading.confiance,
                "direction": result.trading.direction,
                "macroeco_bonus": result.macro.macroeco_bonus,
                "call1_tokens": (
                    result.call1_response.input_tokens
                    + result.call1_response.output_tokens
                ),
                "call2_tokens": (
                    result.call2_response.input_tokens
                    + result.call2_response.output_tokens
                ),
            },
        )

        logger.info("=" * 60)
        logger.info(
            "SUCCESS — ensemble row narrative written for date=%s "
            "(decision=%s confidence=%d direction=%s)",
            data_date,
            result.trading.decision,
            result.trading.confiance,
            result.trading.direction,
        )
        logger.info("=" * 60)
        return 0

    except (KeyboardInterrupt, SystemExit):
        raise
    except (EnsembleRowMissingError, AnalysisWriteError) as exc:
        logger.exception("Ensemble explainer failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1
    except Exception as exc:
        logger.exception("Ensemble explainer failed (unexpected): %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""End-to-end: DB rows -> regime -> judge -> pl_judge_shadow.

One target session per call. Wired from both the standalone CLI
(``poetry run judge-shadow-compute``) and from ``cc-regime-shadow``'s main.py
after regime has committed its own row (Option 1 in the design: single Cloud
Run job, judge as layer-3 of regime — same job, same session, sequential
writes).

The judge job is fail-loud (per pipeline-error-handling.md): a missing regime
row, a missing brief article, or an LLM failure crashes the whole job. The
recovery path is manual — fix root cause, re-run ``judge-shadow-compute
--session-date <T>``.
"""

from __future__ import annotations

import logging
from datetime import date as date_cls

from judge.config import BRIEF_WINDOW  # type: ignore
from judge.integration import prob_up_to_confidence  # type: ignore
from judge.runner import decide as judge_decide  # type: ignore
from judge.schema import BaseCall, Brief, Decision  # type: ignore
from sqlalchemy.orm import Session

from scripts.db import get_previous_session_date, get_next_session_date
from scripts.judge_shadow.brief_builder import build_brief_from_db
from scripts.judge_shadow.db_writer import write_judge_shadow
from scripts.judge_shadow.llm_openai import OpenAIJudgeLLM
from scripts.judge_shadow.regime_reader import (
    RegimeShadowRow,
    load_regime_for,
    resolve_algorithm_version_id,
    resolve_front_month_contract_id,
)

logger = logging.getLogger(__name__)

# Judge is meant to work with a window of daily briefs — cap the window at
# BRIEF_WINDOW (=3) and pull the last N trading days.
_WINDOW = BRIEF_WINDOW


def _prior_data_dates(session: Session, data_date: date_cls, n: int) -> list[date_cls]:
    """Return the ``n`` most recent trading dates <= data_date, oldest-first."""
    dates: list[date_cls] = [data_date]
    cur = data_date
    for _ in range(n - 1):
        cur = get_previous_session_date(cur)
        dates.append(cur)
    return list(reversed(dates))


def _build_window(session: Session, data_date: date_cls) -> list[Brief]:
    """Build the ``BRIEF_WINDOW`` briefs ending on ``data_date`` (oldest-first).

    Today's Brief has ``include_algo_base=False`` because ``run_shadow`` /
    ``decide(base_override=...)`` will overwrite the base call with regime.
    Priors populate their own base_decision from the ensemble row (contextual
    for the prompt; not gating).
    """
    window: list[Brief] = []
    dates = _prior_data_dates(session, data_date, _WINDOW)
    for i, d in enumerate(dates):
        target = get_next_session_date(d)
        include_base = i < len(dates) - 1  # False only for the today brief
        window.append(
            build_brief_from_db(
                session, data_date=d, target_date=target, include_algo_base=include_base
            )
        )
    return window


def _regime_base_call(regime: RegimeShadowRow) -> BaseCall:
    """Adapt a ``RegimeShadowRow`` to judge's ``BaseCall``."""
    decision = Decision(regime.decision)
    direction = {
        Decision.OPEN: "UP",
        Decision.HEDGE: "DOWN",
        Decision.MONITOR: "NEUTRAL",
    }[decision]
    return BaseCall(
        decision=decision,
        confidence=prob_up_to_confidence(regime.prob_up),
        direction_label=direction,
        source="regime/1.0.0",
    )


def run_for_session(
    session: Session,
    *,
    data_date: date_cls,
    llm: OpenAIJudgeLLM | None = None,
    dry_run: bool = False,
) -> int:
    """Compute + write the judge overlay for one session. Returns rows written."""
    aid = resolve_algorithm_version_id(session)
    contract_id = resolve_front_month_contract_id(session, data_date)
    if contract_id is None:
        raise RuntimeError(
            f"no front-month contract resolvable for {data_date} — "
            "check v_contract_data_chained + ref_contract.is_active"
        )

    regime = load_regime_for(session, data_date, allow_stale=True)
    if regime.source_date != data_date:
        logger.warning(
            "judge(%s): using stale regime row from %s (gap = %d days)",
            data_date,
            regime.source_date,
            (data_date - regime.source_date).days,
        )

    window = _build_window(session, data_date)
    base_call = _regime_base_call(regime)

    if llm is None:
        llm = OpenAIJudgeLLM()

    outcome = judge_decide(window, llm, base_override=base_call)

    logger.info(
        "  %s: base=%-7s -> final=%-7s (changed=%s) judge=%s/%s conf=%d",
        data_date,
        outcome.base_decision.value,
        outcome.final_decision.value,
        outcome.changed,
        outcome.verdict.stance.value,
        outcome.verdict.suggested_direction.value,
        outcome.verdict.confidence,
    )

    if dry_run:
        return 0

    return write_judge_shadow(
        session,
        outcome,
        session_date=data_date,
        contract_id=contract_id,
        algorithm_version_id=aid,
        regime_row=regime,
    )

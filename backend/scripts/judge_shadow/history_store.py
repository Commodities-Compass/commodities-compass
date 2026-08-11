"""Load the judge's own prior decisions from ``pl_judge_shadow`` (v0.2 fine-tune).

Implements the ``judge.integration.JudgeHistoryStore`` Protocol: returns the
N most recent judge shadow rows STRICTLY BEFORE ``session_date``, joined with
the front-month close at each of those dates (via ``v_contract_data_chained``),
so the LLM can reconcile against "you called X and price has since done Y".
Oldest-first (matches the ``history`` list ordering in ``judge.runner.decide``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime

from judge.schema import Decision, Direction, PriorJudgeRecord  # type: ignore
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DBJudgeHistoryStore:
    """PROD impl of ``JudgeHistoryStore`` — reads pl_judge_shadow + chained OHLCV.

    Frozen dataclass with a single ``session`` field so the wire is explicit
    and easily mockable in tests (no hidden state, no globals).
    """

    session: Session

    def load_recent_decisions(
        self, session_date: str, n: int
    ) -> list[PriorJudgeRecord]:
        """Return up to ``n`` prior judge decisions, oldest-first.

        The chained-OHLCV LEFT JOIN can return NULL closes on non-trading
        gaps (shouldn't happen since judge only writes on trading days, but
        defensive). ``PriorJudgeRecord.close`` is ``float | None`` so the
        renderer skips the "price since" line gracefully.
        """
        d = _parse_iso(session_date)
        rows = self.session.execute(
            text(
                """
                SELECT j.date,
                       j.final_decision,
                       j.judge_direction,
                       j.judge_confidence,
                       c.close
                FROM pl_judge_shadow j
                LEFT JOIN v_contract_data_chained c ON c.date = j.date
                WHERE j.date < :d
                ORDER BY j.date DESC
                LIMIT :n
                """
            ),
            {"d": d, "n": int(n)},
        ).fetchall()
        # Reverse so the list is oldest-first (matches the pack's contract).
        rows = list(reversed(rows))
        out: list[PriorJudgeRecord] = []
        for r in rows:
            out.append(
                PriorJudgeRecord(
                    session_date=r.date.isoformat(),
                    final_decision=_decision(r.final_decision),
                    suggested_direction=_direction(r.judge_direction),
                    confidence=int(r.judge_confidence),
                    close=float(r.close) if r.close is not None else None,
                )
            )
        if out:
            logger.info(
                "judge history: %d prior decision(s) before %s [%s..%s]",
                len(out),
                session_date,
                out[0].session_date,
                out[-1].session_date,
            )
        return out


def _parse_iso(s: str) -> date_cls:
    """Accept 'YYYY-MM-DD' string OR a datetime/date passed as string(...)."""
    return datetime.strptime(s, "%Y-%m-%d").date()


def _decision(raw: str | None) -> Decision:
    try:
        return Decision((raw or "MONITOR").upper())
    except ValueError:
        return Decision.MONITOR


def _direction(raw: str | None) -> Direction:
    try:
        return Direction((raw or "NONE").upper())
    except ValueError:
        return Direction.NONE

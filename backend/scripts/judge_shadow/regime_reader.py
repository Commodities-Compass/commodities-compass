"""Read the regime shadow decision for a target session — feed judge's base call.

Judge's ``base_override`` expects a ``RegimeDecisionLike`` (Protocol: ``decision,
prob_up, regime, specialist``). We surface a small frozen dataclass that
satisfies it, sourced from ``pl_regime_shadow`` by ``data_date``.

Handles the Phase-B weekend gap: regime runs Sun-Thu eve for Mon-Fri targets
under Option 1 (bundled with judge in the same job). If judge is manually
back-run for a target where regime never wrote (e.g. a historical backfill
predating regime's launch on 2026-07-29), we return the most recent regime row
whose ``date <= data_date`` and let the writer log the source date so eval
knows the freshness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

_REGIME_VERSION_NAME = "regime"
_REGIME_VERSION = "1.0.0"


@dataclass(frozen=True)
class RegimeShadowRow:
    """Duck-typed shape of ``judge.integration.RegimeDecisionLike``."""

    decision: str
    prob_up: float
    regime: str
    specialist: str
    source_date: date_cls  # which pl_regime_shadow row was read


class RegimeShadowMissingError(RuntimeError):
    """No pl_regime_shadow row is available up to the target data_date."""


def load_regime_for(
    session: Session, data_date: date_cls, *, allow_stale: bool = True
) -> RegimeShadowRow:
    """Return the regime shadow row for ``data_date``, or the latest prior one.

    ``allow_stale=True`` (default) accepts a prior date and logs it via
    ``source_date``. ``allow_stale=False`` requires an exact date match.
    """
    if allow_stale:
        row = session.execute(
            text(
                """
                SELECT s.decision, s.prob_up, s.regime, s.specialist, s.date
                FROM pl_regime_shadow s
                JOIN pl_algorithm_version v ON v.id = s.algorithm_version_id
                WHERE v.name = :n AND v.version = :ver AND s.date <= :d
                ORDER BY s.date DESC
                LIMIT 1
                """
            ),
            {"n": _REGIME_VERSION_NAME, "ver": _REGIME_VERSION, "d": data_date},
        ).fetchone()
    else:
        row = session.execute(
            text(
                """
                SELECT s.decision, s.prob_up, s.regime, s.specialist, s.date
                FROM pl_regime_shadow s
                JOIN pl_algorithm_version v ON v.id = s.algorithm_version_id
                WHERE v.name = :n AND v.version = :ver AND s.date = :d
                """
            ),
            {"n": _REGIME_VERSION_NAME, "ver": _REGIME_VERSION, "d": data_date},
        ).fetchone()

    if row is None:
        raise RegimeShadowMissingError(
            f"no pl_regime_shadow row for {_REGIME_VERSION_NAME}@{_REGIME_VERSION} "
            f"<= {data_date}"
        )
    return RegimeShadowRow(
        decision=str(row.decision),
        prob_up=float(row.prob_up),
        regime=str(row.regime),
        specialist=str(row.specialist),
        source_date=row.date,
    )


def resolve_algorithm_version_id(session: Session) -> str:
    """The algorithm the judge overlays — ``regime`` v1.0.0.

    The judge writes `pl_judge_shadow` under this SAME id. It used to carry a
    `judge` version of its own, which existed only to be a foreign key: the
    table already stores `prompt_version` and `model_id`, which are what actually
    identifies a judge run and what a replay targets.

    That second id bought no information and cost a class of bug — two uuids of
    the same type, both plausibly "the judge's", one correct per query. Reading
    `pl_indicator_daily` under the judge id could only ever find nothing (the
    judge writes no row there); reading `pl_judge_shadow` under the regime id
    could only ever find nothing either. Both shipped.

    One id now. The confusion is not documented away, it is gone.
    """
    row = session.execute(
        text(
            "SELECT id FROM pl_algorithm_version WHERE name = 'regime' AND version = '1.0.0'"
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError(
            "pl_algorithm_version 'regime'@'1.0.0' not found — apply migration "
            "k6f7g8h9i0j1_seed_regime_algorithm_version first."
        )
    return str(row[0])


def resolve_front_month_contract_id(
    session: Session, data_date: date_cls
) -> Optional[str]:
    """Front-month contract for the given session (mirrors regime's convention).

    Uses ``v_contract_data_chained`` — the canonical roll-safe chain — so that
    a roll boundary can't split the read. Falls back to ``ref_contract.is_active``
    only if the view returns nothing (shouldn't happen once chained coverage is
    green, kept as a defensive fallback).
    """
    row = session.execute(
        text(
            """
            SELECT contract_id
            FROM v_contract_data_chained
            WHERE date = :d
            LIMIT 1
            """
        ),
        {"d": data_date},
    ).fetchone()
    if row is not None:
        return str(row[0])
    row = session.execute(
        text("SELECT id FROM ref_contract WHERE is_active = TRUE LIMIT 1")
    ).fetchone()
    return str(row[0]) if row else None

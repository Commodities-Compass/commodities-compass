"""The judge reads the calls of the algorithm it overlays — not its own.

Two algorithm_version ids are in play on every judge run and they are easy to
confuse because both are "the judge's":

  * ``judge`` v0.1  — provenance. What ``pl_judge_shadow`` rows are tagged with.
  * ``regime`` v1.0.0 — the algorithm being overlaid. The only one that carries
    ``pl_indicator_daily`` decisions, because the judge writes none.

Scoping the prior-brief window to the first can only ever find nothing, and
since that lookup is deliberately fail-loud (no fabricated neutral call), the
nightly job dies on `PriorBaseCallMissingError`. This was live in the branch
until a full v0.2 replay hit it on the first session — CI could not have caught
it, because no test seeded two algorithm versions AND adapter rows.
"""

from __future__ import annotations

import uuid
from datetime import date as date_cls

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.judge_shadow.regime_reader import (
    resolve_algorithm_version_id,
    resolve_base_algorithm_version_id,
)

SESSION = date_cls(2026, 8, 17)


def _seed_versions(session: Session) -> tuple[str, str]:
    """Insert the judge and regime versions, returning (judge_id, regime_id)."""
    judge_id, regime_id = str(uuid.uuid4()), str(uuid.uuid4())
    for vid, name, ver, kind in (
        (judge_id, "judge", "0.1", "llm_overlay"),
        (regime_id, "regime", "1.0.0", "ml_regime"),
    ):
        session.execute(
            text(
                "INSERT INTO pl_algorithm_version "
                "(id, name, version, horizon, is_active, compute_enabled, algorithm_kind) "
                "VALUES (:i, :n, :v, 'short_term', false, false, :k)"
            ),
            {"i": vid, "n": name, "v": ver, "k": kind},
        )
    session.flush()
    return judge_id, regime_id


@pytest.mark.integration
def test_the_two_resolvers_return_different_versions(sync_db_session: Session) -> None:
    judge_id, regime_id = _seed_versions(sync_db_session)

    assert resolve_algorithm_version_id(sync_db_session) == judge_id
    assert resolve_base_algorithm_version_id(sync_db_session) == regime_id
    # The whole point: they must not be interchangeable.
    assert resolve_algorithm_version_id(
        sync_db_session
    ) != resolve_base_algorithm_version_id(sync_db_session)


@pytest.mark.integration
def test_the_base_resolver_names_regime_when_it_is_missing(
    sync_db_session: Session,
) -> None:
    """Fail-loud with the migration to run, not a NoneType further down."""
    with pytest.raises(RuntimeError, match="regime"):
        resolve_base_algorithm_version_id(sync_db_session)


@pytest.mark.integration
def test_the_window_reads_regime_rows_not_judge_rows(sync_db_session: Session) -> None:
    """End-to-end on the lookup that broke: a decision exists under regime only.

    Scoped to ``_fetch_algo_base_call`` rather than the whole runner so the test
    states one thing — which version id the window is allowed to read.
    """
    from scripts.judge_shadow.brief_builder import (
        PriorBaseCallMissingError,
        _fetch_algo_base_call,
    )

    judge_id, regime_id = _seed_versions(sync_db_session)
    contract_id = str(uuid.uuid4())
    sync_db_session.execute(
        text(
            "INSERT INTO ref_exchange (id, code, name, timezone) "
            "VALUES (:i, 'ICE-T', 'ICE', 'UTC')"
        ),
        {"i": contract_id},
    )
    commodity_id = str(uuid.uuid4())
    sync_db_session.execute(
        text(
            "INSERT INTO ref_commodity (id, code, name, exchange_id) "
            "VALUES (:i, 'CC-T', 'Cocoa', :e)"
        ),
        {"i": commodity_id, "e": contract_id},
    )
    real_contract = str(uuid.uuid4())
    sync_db_session.execute(
        text(
            "INSERT INTO ref_contract (id, commodity_id, code, contract_month, is_active) "
            "VALUES (:i, :c, 'CAU26', 'U26', false)"
        ),
        {"i": real_contract, "c": commodity_id},
    )
    sync_db_session.execute(
        text(
            "INSERT INTO pl_indicator_daily "
            "(id, date, contract_id, algorithm_version_id, language, decision, confidence) "
            "VALUES (:i, :d, :c, :a, 'fr', 'HEDGE', 3)"
        ),
        {
            "i": str(uuid.uuid4()),
            "d": SESSION,
            "c": real_contract,
            "a": regime_id,
        },
    )
    sync_db_session.flush()

    decision, _, _ = _fetch_algo_base_call(sync_db_session, SESSION, regime_id)
    assert decision == "HEDGE"

    # The judge's own version carries no decision — and must fail loud rather
    # than pad the window with an invented neutral call.
    with pytest.raises(PriorBaseCallMissingError):
        _fetch_algo_base_call(sync_db_session, SESSION, judge_id)

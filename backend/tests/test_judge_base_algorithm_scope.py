"""One algorithm id, and every judge query goes through it.

Two uuids of the same type once coexisted here — the judge's own version, and
the algorithm it overlays. Exactly one was correct per query, and picking the
wrong one never returned a partial result: it returned nothing at all. That
shipped twice, on the write side (fail-loud, killed the nightly job) and on the
read side (silently absorbed by a legitimate "no overlay tonight" degradation,
visible only on a screenshot).

Migration ``u3j4u5d6g7e8`` collapsed them: ``pl_judge_shadow`` is tagged with the
overlaid algorithm, and the judge's identity stays where it already was —
``prompt_version`` and ``model_id`` on the row itself.

These tests hold the collapse. If a second resolver reappears, or the window
starts reading under something other than the served algorithm, they fail.
"""

from __future__ import annotations

import uuid
from datetime import date as date_cls

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.judge_shadow import regime_reader
from scripts.judge_shadow.regime_reader import resolve_algorithm_version_id

SESSION = date_cls(2026, 8, 17)


def _seed_versions(session: Session) -> tuple[str, str]:
    """Insert the judge and regime versions, returning (judge_id, regime_id).

    The judge row is seeded on purpose: it still exists in production (inert,
    referenced by nothing) and the resolver must not drift back onto it.
    """
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
def test_the_resolver_returns_the_overlaid_algorithm(sync_db_session: Session) -> None:
    """Not the judge's own version, even though its row is right there."""
    judge_id, regime_id = _seed_versions(sync_db_session)

    resolved = resolve_algorithm_version_id(sync_db_session)
    assert resolved == regime_id
    assert resolved != judge_id


@pytest.mark.integration
def test_there_is_only_one_resolver_left(sync_db_session: Session) -> None:
    """The second one was the bug's habitat.

    Asserted on the module rather than by reading code: a helper reintroduced
    "just for this one call site" is exactly how the confusion came back the
    second time.
    """
    assert not hasattr(regime_reader, "resolve_base_algorithm_version_id"), (
        "a second algorithm-id resolver is back — that is the shape the bug took "
        "twice; the judge and the algorithm it overlays share one id now"
    )


@pytest.mark.integration
def test_the_resolver_names_regime_when_it_is_missing(sync_db_session: Session) -> None:
    """Fail-loud with the migration to run, not a NoneType further down."""
    with pytest.raises(RuntimeError, match="regime"):
        resolve_algorithm_version_id(sync_db_session)


@pytest.mark.integration
def test_the_prior_brief_window_reads_the_served_algorithm(
    sync_db_session: Session,
) -> None:
    """End-to-end on the lookup that broke first.

    A decision exists under regime; the window must find it. And the judge
    version — which carries no pl_indicator_daily row and never will — must still
    fail loud rather than pad the window with an invented neutral call.
    """
    from scripts.judge_shadow.brief_builder import (
        PriorBaseCallMissingError,
        _fetch_algo_base_call,
    )

    judge_id, regime_id = _seed_versions(sync_db_session)
    exchange_id = str(uuid.uuid4())
    sync_db_session.execute(
        text(
            "INSERT INTO ref_exchange (id, code, name, timezone) "
            "VALUES (:i, 'ICE-T', 'ICE', 'UTC')"
        ),
        {"i": exchange_id},
    )
    commodity_id = str(uuid.uuid4())
    sync_db_session.execute(
        text(
            "INSERT INTO ref_commodity (id, code, name, exchange_id) "
            "VALUES (:i, 'CC-T', 'Cocoa', :e)"
        ),
        {"i": commodity_id, "e": exchange_id},
    )
    contract_id = str(uuid.uuid4())
    sync_db_session.execute(
        text(
            "INSERT INTO ref_contract (id, commodity_id, code, contract_month, is_active) "
            "VALUES (:i, :c, 'CAU26', 'U26', false)"
        ),
        {"i": contract_id, "c": commodity_id},
    )
    sync_db_session.execute(
        text(
            "INSERT INTO pl_indicator_daily "
            "(id, date, contract_id, algorithm_version_id, language, decision, confidence) "
            "VALUES (:i, :d, :c, :a, 'fr', 'HEDGE', 3)"
        ),
        {"i": str(uuid.uuid4()), "d": SESSION, "c": contract_id, "a": regime_id},
    )
    sync_db_session.flush()

    decision, _, _ = _fetch_algo_base_call(sync_db_session, SESSION, regime_id)
    assert decision == "HEDGE"

    with pytest.raises(PriorBaseCallMissingError):
        _fetch_algo_base_call(sync_db_session, SESSION, judge_id)

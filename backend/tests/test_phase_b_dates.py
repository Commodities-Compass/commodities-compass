"""Unit tests for the centralized Phase-B date helper (scripts/db.py).

The helper is the single source of truth for the ``(target_date, data_date)``
split that every Phase-B job shares. These tests lock the two invariants that
the pre-refactor inline duplication kept getting wrong:

  * Backfill: the operator types the ROW date (``--session-date``) → that value
    IS ``data_date``; ``target_date`` is derived, never operator-facing.
  * Cron: derive the pair from today via next/previous session.

See docs/architecture/flows/date-semantics.md.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

import scripts.db as db
from scripts.db import PhaseBDates, phase_b_should_skip, resolve_phase_b_dates


@pytest.mark.unit
def test_backfill_explicit_is_the_data_date(monkeypatch):
    """`--session-date X` → data_date == X (the row that lands), target derived."""
    seen = {}

    def fake_next(d, exchange_code="IFEU"):
        seen["next_arg"] = d
        return date(2026, 7, 6)  # next_session(Fri 3 Jul) = Mon 6 Jul

    def fail_prev(*a, **k):  # must NOT be reached on the backfill path
        raise AssertionError("get_previous_session_date called on backfill path")

    monkeypatch.setattr(db, "is_trading_day", lambda *a, **k: True)
    monkeypatch.setattr(db, "get_next_session_date", fake_next)
    monkeypatch.setattr(db, "get_previous_session_date", fail_prev)

    result = resolve_phase_b_dates(date(2026, 7, 3))

    assert result == PhaseBDates(
        target_date=date(2026, 7, 6), data_date=date(2026, 7, 3)
    )
    # What you type IS the row date — impossible to invert.
    assert result.data_date == date(2026, 7, 3)
    # target_date is derived from the session date, not the other way around.
    assert seen["next_arg"] == date(2026, 7, 3)


@pytest.mark.unit
def test_backfill_rejects_non_trading_day(monkeypatch):
    """Fail-loud: an explicit --session-date on a weekend/holiday raises."""
    monkeypatch.setattr(db, "is_trading_day", lambda *a, **k: False)
    monkeypatch.setattr(
        db,
        "get_next_session_date",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("must reject before deriving target_date")
        ),
    )
    with pytest.raises(ValueError, match="not a IFEU trading day"):
        resolve_phase_b_dates(date(2026, 7, 4))  # Saturday


@pytest.mark.unit
def test_cron_derives_pair_from_today(monkeypatch):
    """No explicit date → target = next_session(today), data = previous(target)."""

    def fake_next(d, exchange_code="IFEU"):
        return date(2026, 7, 7)  # next_session(today) = T+1

    def fake_prev(d, exchange_code="IFEU"):
        assert d == date(2026, 7, 7), "data_date must derive from target_date"
        return date(2026, 7, 6)  # previous_session(T+1) = T

    monkeypatch.setattr(db, "get_next_session_date", fake_next)
    monkeypatch.setattr(db, "get_previous_session_date", fake_prev)

    result = resolve_phase_b_dates(None)

    assert result.target_date == date(2026, 7, 7)
    assert result.data_date == date(2026, 7, 6)


@pytest.mark.unit
def test_phase_b_dates_is_immutable():
    pair = PhaseBDates(target_date=date(2026, 7, 7), data_date=date(2026, 7, 6))
    with pytest.raises(dataclasses.FrozenInstanceError):
        pair.data_date = date(2026, 1, 1)  # type: ignore[misc]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("session_date", "force", "is_eve", "expected"),
    [
        (None, False, True, False),  # cron, eve of a trading day → run
        (None, False, False, True),  # cron, tomorrow not trading → skip cleanly
        (date(2026, 7, 3), False, False, False),  # backfill → run even if not eve
        (None, True, False, False),  # --force → run even if not eve
    ],
)
def test_phase_b_should_skip(monkeypatch, session_date, force, is_eve, expected):
    monkeypatch.setattr(db, "is_eve_of_trading_day", lambda **k: is_eve)
    assert phase_b_should_skip(session_date, force) is expected

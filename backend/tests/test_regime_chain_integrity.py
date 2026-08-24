"""Regime chain integrity — the roll-hole and stale-tail guards.

Origin: 2026-08-24 pre-roll audit (CAU26→CAZ26, first roll under the canonical
calendar). ``v_contract_data_chained`` is a calendar INNER JOIN since migration
d5e6f7a8b9c0, so a session whose calendar front-month has no OHLCV row does not
error — it **disappears from the series**. Combined with
``_resolve_target_dates`` taking ``all_dates[-1:]`` off that series and never
comparing it to the session it is supposed to compute, ``cc-regime-shadow``
would silently recompute and re-upsert YESTERDAY every night, exit 0, with every
Sentry cron monitor green (and ``cc-regime-brief`` re-uploading under the stale
date stem).

Two independent guards, both fail-loud:
  * gap    — the chain must cover every scraped session inside its own span.
  * stale  — on the cron path the chain tail must BE the session we are about to
             publish, never an older one.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.pipeline import PlContractDataDaily
from app.models.reference import RefCommodity, RefContract, RefExchange

# Calendar VIEW — must stay in sync with migration d5e6f7a8b9c0 (_NEW_VIEW).
# Same hand-copied convention as tests/test_front_month_calendar.py.
_CALENDAR_VIEW_DDL = """
CREATE OR REPLACE VIEW v_contract_data_chained AS
WITH front AS (
    SELECT dd.date,
           (SELECT c.id FROM ref_contract c
             WHERE c.active_from IS NOT NULL
               AND c.active_from <= dd.date
             ORDER BY c.active_from DESC LIMIT 1) AS front_id
    FROM (SELECT DISTINCT date FROM pl_contract_data_daily
           WHERE close IS NOT NULL) dd
)
SELECT d.date, d.display_date, d.contract_id,
       d.open, d.high, d.low, d.close,
       d.volume, d.oi, d.implied_volatility
FROM pl_contract_data_daily d
JOIN front f ON f.date = d.date AND f.front_id = d.contract_id
WHERE d.close IS NOT NULL;
"""


@pytest.fixture()
def calendar_view(sync_db_session: Session):
    sync_db_session.execute(text(_CALENDAR_VIEW_DDL))
    sync_db_session.flush()
    yield
    sync_db_session.execute(text("DROP VIEW IF EXISTS v_contract_data_chained"))


def _commodity(session: Session) -> uuid.UUID:
    ex = RefExchange(code="IFEU-CHAIN", name="ICE", timezone="Europe/London")
    session.add(ex)
    session.flush()
    com = RefCommodity(code="COCOA-CHAIN", name="Cocoa", exchange_id=ex.id)
    session.add(com)
    session.flush()
    return com.id


def _contract(
    session: Session,
    commodity_id: uuid.UUID,
    *,
    code: str,
    month: str,
    active_from: date | None,
) -> uuid.UUID:
    c = RefContract(
        commodity_id=commodity_id,
        code=code,
        contract_month=month,
        active_from=active_from,
    )
    session.add(c)
    session.flush()
    return c.id


def _bar(session: Session, contract_id: uuid.UUID, d: date, close: float = 100.0):
    session.add(
        PlContractDataDaily(
            date=d,
            display_date=d,
            contract_id=contract_id,
            close=Decimal(str(close)),
            volume=1000,
            oi=1000,
        )
    )
    session.flush()


class TestChainGapGuard:
    """A scraped session missing from the chain must fail loud, not vanish."""

    def test_raises_when_calendar_front_month_has_no_row(
        self, sync_db_session, calendar_view
    ):
        from scripts.regime_shadow.feature_engine import (
            RegimeChainGapError,
            assert_chain_has_no_gaps,
        )

        com = _commodity(sync_db_session)
        old = _contract(
            sync_db_session,
            com,
            code="CAU26",
            month="2026-09",
            active_from=date(2026, 6, 17),
        )
        new = _contract(
            sync_db_session, com, code="CAZ26", month="2026-12", active_from=None
        )

        _bar(sync_db_session, old, date(2026, 8, 20))
        _bar(sync_db_session, new, date(2026, 8, 20))
        # The roll hole: 08-21 scraped ONLY under the un-rolled contract, so the
        # calendar front-month (CAU26) has no row and the INNER JOIN drops it.
        _bar(sync_db_session, new, date(2026, 8, 21))

        with pytest.raises(RegimeChainGapError) as exc:
            assert_chain_has_no_gaps(sync_db_session, date(2026, 8, 20))
        assert "2026-08-21" in str(exc.value)

    def test_passes_when_chain_covers_every_scraped_session(
        self, sync_db_session, calendar_view
    ):
        from scripts.regime_shadow.feature_engine import assert_chain_has_no_gaps

        com = _commodity(sync_db_session)
        old = _contract(
            sync_db_session,
            com,
            code="CAU26",
            month="2026-09",
            active_from=date(2026, 6, 17),
        )
        new = _contract(
            sync_db_session,
            com,
            code="CAZ26",
            month="2026-12",
            active_from=date(2026, 8, 21),
        )
        _bar(sync_db_session, old, date(2026, 8, 20))
        _bar(sync_db_session, new, date(2026, 8, 20))
        _bar(sync_db_session, new, date(2026, 8, 21))

        assert_chain_has_no_gaps(sync_db_session, date(2026, 8, 20))  # no raise

    def test_ignores_sessions_before_the_chain_start(
        self, sync_db_session, calendar_view
    ):
        """Pre-calendar prehistory is legitimately absent — never a gap."""
        from scripts.regime_shadow.feature_engine import assert_chain_has_no_gaps

        com = _commodity(sync_db_session)
        old = _contract(
            sync_db_session,
            com,
            code="CAU26",
            month="2026-09",
            active_from=date(2026, 6, 17),
        )
        orphan = _contract(
            sync_db_session, com, code="CAK20", month="2020-05", active_from=None
        )
        _bar(sync_db_session, orphan, date(2020, 4, 1))
        _bar(sync_db_session, old, date(2026, 8, 20))

        assert_chain_has_no_gaps(sync_db_session, date(2026, 8, 20))  # no raise


class TestStaleTailGuard:
    """On the cron path the chain tail must be the session we are publishing."""

    def test_raises_when_chain_tail_is_older_than_expected_session(self):
        import pandas as pd

        from scripts.regime_shadow.main import (
            RegimeChainStaleError,
            _resolve_target_dates,
        )

        features = pd.DataFrame({"date": pd.to_datetime(["2026-08-20", "2026-08-21"])})

        class _Args:
            session_date = None
            backfill_days = None

        with pytest.raises(RegimeChainStaleError) as exc:
            _resolve_target_dates(features, _Args(), expected=date(2026, 8, 24))
        assert "2026-08-24" in str(exc.value)
        assert "2026-08-21" in str(exc.value)

    def test_passes_when_chain_tail_is_the_expected_session(self):
        import pandas as pd

        from scripts.regime_shadow.main import _resolve_target_dates

        features = pd.DataFrame({"date": pd.to_datetime(["2026-08-20", "2026-08-21"])})

        class _Args:
            session_date = None
            backfill_days = None

        assert _resolve_target_dates(features, _Args(), expected=date(2026, 8, 21)) == [
            date(2026, 8, 21)
        ]

    def test_explicit_session_date_bypasses_the_guard(self):
        import pandas as pd

        from scripts.regime_shadow.main import _resolve_target_dates

        features = pd.DataFrame({"date": pd.to_datetime(["2026-08-20", "2026-08-21"])})

        class _Args:
            session_date = date(2026, 8, 20)
            backfill_days = None

        assert _resolve_target_dates(features, _Args(), expected=date(2026, 8, 24)) == [
            date(2026, 8, 20)
        ]

    def test_backfill_bypasses_the_guard(self):
        """A backfill deliberately targets old sessions — never stale."""
        import pandas as pd

        from scripts.regime_shadow.main import _resolve_target_dates

        features = pd.DataFrame({"date": pd.to_datetime(["2026-08-20", "2026-08-21"])})

        class _Args:
            session_date = None
            backfill_days = 2

        assert _resolve_target_dates(features, _Args(), expected=date(2026, 8, 24)) == [
            date(2026, 8, 20),
            date(2026, 8, 21),
        ]

"""Regression: STOCK_EU in the ensemble brief must be tonnes, not native bags.

Origin: 2026-06-18 — section V printed ``STOCK_EU=284,709`` (60 kg bags) next to
``STOCK_US=204,311`` (tonnes). The EU query read ``value_native`` while the US
query read ``value_tonnes``, mixing units in one line: 284,709 bags = 17,082.54
tonnes, so the brief overstated EU stock ~16.7x and read as "EU > US" when in
tonnes EU is an order of magnitude below US. Both must be tonnes to compare.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from scripts.compass_brief_ensemble import db_reader


def _session_capturing_sql() -> tuple[MagicMock, list[str]]:
    captured: list[str] = []

    def _execute(stmt, params=None):
        sql = str(stmt)
        captured.append(sql)
        result = MagicMock()
        if "pl_contract_data_daily" in sql:
            result.fetchone.return_value = (
                date(2026, 6, 17),
                Decimal("3161"),
                Decimal("3257"),
                Decimal("3140"),
                8927,
                53159,
                Decimal("0.57"),
            )
            return result
        # stock_us / stock_eu / com_net scalar lookups
        result.scalar_one_or_none.return_value = Decimal("17082.54")
        return result

    session = MagicMock()
    session.execute.side_effect = _execute
    return session, captured


@pytest.mark.unit
def test_eu_stock_query_selects_tonnes_not_native_bags() -> None:
    session, captured = _session_capturing_sql()

    db_reader._read_technicals(session, date(2026, 6, 17), "c-uuid")

    eu_queries = [s for s in captured if "region = 'eu'" in s]
    assert eu_queries, "EU stock query not observed — fixture drifted."
    eu_sql = eu_queries[0]
    assert "value_tonnes" in eu_sql, (
        "STOCK_EU must select value_tonnes (comparable to STOCK_US tonnes), "
        "not value_native (60 kg bags)."
    )
    assert "value_native" not in eu_sql


@pytest.mark.unit
def test_us_stock_query_still_tonnes() -> None:
    """Guard the US side stays tonnes (it was already correct)."""
    session, captured = _session_capturing_sql()

    db_reader._read_technicals(session, date(2026, 6, 17), "c-uuid")

    us_queries = [s for s in captured if "region = 'us'" in s]
    assert us_queries, "US stock query not observed — fixture drifted."
    assert "value_tonnes" in us_queries[0]

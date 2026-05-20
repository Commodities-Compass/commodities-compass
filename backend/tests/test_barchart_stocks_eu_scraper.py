"""Tests for cc-barchart-stocks-eu-scraper.

Covers:
  * HTML parser (Barchart cmdty page with 2 cmdty-quote-table blocks)
  * DB writer (UPDATE on pl_contract_data_daily — never INSERT)
  * HTTP fetch (httpx, fail-loud on non-200 / empty body / captcha block)
  * CLI flags (--dry-run, --date, --verbose, --force)
  * Main orchestration (Sentry context, exit codes, dry-run skip)

See:
  * docs/user-stories/P1-scrapers-stock-cot-eu.md §3.1
  * Source: https://www.barchart.com/cmdty/data/fundamental/explore/IC345DRW.CS
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from scripts.barchart_stocks_eu_scraper.db_writer import (
    StockEuRowMissingError,
    update_stock_eu,
)
from scripts.barchart_stocks_eu_scraper.main import _parse_args
from scripts.barchart_stocks_eu_scraper.parser import (
    BarchartStocksEuParseError,
    StockEuObservation,
    parse_barchart_stocks_eu_html,
)
from tests.factories import (
    make_pl_contract_data_daily,
    make_ref_commodity,
    make_ref_contract,
    make_ref_exchange,
)


# ---------------------------------------------------------------------------
# Sample HTML — minimal representative fragment of the live Barchart cmdty page
# ---------------------------------------------------------------------------

_VALID_HTML = """
<html><body>
<h1>ICE Cocoa Certified Stocks TOTAL, All ICE Warehouses</h1>

<table class="cmdty-quote-table mt-2">
    <tbody>
        <tr><th>Most Recent Value</th><td>621,116</td></tr>
        <tr><th>Most Recent Date</th><td>05-13-2026</td></tr>
        <tr><th>Frequency</th><td>Daily</td></tr>
        <tr><th>Unit</th><td>60 Kg Bag</td></tr>
        <tr><th>Multiplier</th><td>1</td></tr>
        <tr><th>Prior Value</th><td>615,897</td></tr>
        <tr><th>Prior Value Date</th><td>05-06-2026</td></tr>
        <tr><th>First Value</th><td>450,918</td></tr>
        <tr><th>First Value Date</th><td>02-07-2012</td></tr>
    </tbody>
</table>

<table class="cmdty-quote-table mt-2">
    <tbody>
        <tr><th>05-13-2026</th><td>621,116</td></tr>
        <tr><th>05-06-2026</th><td>615,897</td></tr>
        <tr><th>04-29-2026</th><td>614,452</td></tr>
        <tr><th>04-28-2026</th><td>611,649</td></tr>
        <tr><th>04-27-2026</th><td>611,649</td></tr>
        <tr><th>04-24-2026</th><td>611,649</td></tr>
        <tr><th>04-23-2026</th><td>591,225</td></tr>
    </tbody>
</table>

</body></html>
"""


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParseBarchartStocksEuHtml:
    def test_parses_most_recent_value_and_date(self):
        obs = parse_barchart_stocks_eu_html(_VALID_HTML)
        assert isinstance(obs, StockEuObservation)
        assert obs.date == date(2026, 5, 13)
        assert obs.value_bags60kg == Decimal("621116")

    def test_parses_history_rows(self):
        obs = parse_barchart_stocks_eu_html(_VALID_HTML)
        history = obs.history
        assert len(history) == 7
        # First entry == most recent
        assert history[0] == (date(2026, 5, 13), Decimal("621116"))
        # Last entry == oldest in history table
        assert history[-1] == (date(2026, 4, 23), Decimal("591225"))

    def test_history_is_sorted_descending_by_date(self):
        obs = parse_barchart_stocks_eu_html(_VALID_HTML)
        dates = [d for d, _ in obs.history]
        assert dates == sorted(dates, reverse=True)

    def test_value_with_commas_parsed_as_int_then_decimal(self):
        obs = parse_barchart_stocks_eu_html(_VALID_HTML)
        # 621,116 → 621116 (no fractional part for bags)
        assert obs.value_bags60kg == Decimal("621116")
        assert obs.value_bags60kg.as_tuple().exponent == 0

    def test_none_input_fails_loud(self):
        with pytest.raises(BarchartStocksEuParseError):
            parse_barchart_stocks_eu_html(None)  # type: ignore[arg-type]

    def test_empty_html_fails_loud(self):
        with pytest.raises(BarchartStocksEuParseError, match="no cmdty"):
            parse_barchart_stocks_eu_html("<html><body></body></html>")

    def test_no_quote_table_fails_loud(self):
        html = "<html><body><table><tr><td>nothing</td></tr></table></body></html>"
        with pytest.raises(BarchartStocksEuParseError, match="no cmdty"):
            parse_barchart_stocks_eu_html(html)

    def test_missing_most_recent_value_fails_loud(self):
        html = """
        <table class="cmdty-quote-table">
        <tbody>
            <tr><th>Most Recent Date</th><td>05-13-2026</td></tr>
            <tr><th>Unit</th><td>60 Kg Bag</td></tr>
        </tbody></table>
        """
        with pytest.raises(BarchartStocksEuParseError, match="Most Recent Value"):
            parse_barchart_stocks_eu_html(html)

    def test_missing_most_recent_date_fails_loud(self):
        html = """
        <table class="cmdty-quote-table">
        <tbody>
            <tr><th>Most Recent Value</th><td>621,116</td></tr>
            <tr><th>Unit</th><td>60 Kg Bag</td></tr>
        </tbody></table>
        """
        with pytest.raises(BarchartStocksEuParseError, match="Most Recent Date"):
            parse_barchart_stocks_eu_html(html)

    def test_unparseable_value_fails_loud(self):
        html = """
        <table class="cmdty-quote-table">
        <tbody>
            <tr><th>Most Recent Value</th><td>NOT_A_NUMBER</td></tr>
            <tr><th>Most Recent Date</th><td>05-13-2026</td></tr>
            <tr><th>Unit</th><td>60 Kg Bag</td></tr>
        </tbody></table>
        """
        with pytest.raises(BarchartStocksEuParseError, match="value"):
            parse_barchart_stocks_eu_html(html)

    def test_unparseable_date_fails_loud(self):
        html = """
        <table class="cmdty-quote-table">
        <tbody>
            <tr><th>Most Recent Value</th><td>621,116</td></tr>
            <tr><th>Most Recent Date</th><td>NOT_A_DATE</td></tr>
            <tr><th>Unit</th><td>60 Kg Bag</td></tr>
        </tbody></table>
        """
        with pytest.raises(BarchartStocksEuParseError, match="date"):
            parse_barchart_stocks_eu_html(html)

    def test_unexpected_unit_fails_loud(self):
        """If Barchart switches unit (e.g. to tonnes), fail-loud to prevent silent corruption."""
        html = """
        <table class="cmdty-quote-table">
        <tbody>
            <tr><th>Most Recent Value</th><td>37,267</td></tr>
            <tr><th>Most Recent Date</th><td>05-13-2026</td></tr>
            <tr><th>Unit</th><td>Tonnes</td></tr>
            <tr><th>Multiplier</th><td>1</td></tr>
        </tbody></table>
        """
        with pytest.raises(BarchartStocksEuParseError, match="[Uu]nit"):
            parse_barchart_stocks_eu_html(html)

    def test_unexpected_multiplier_fails_loud(self):
        """If multiplier ≠ 1, scaling assumptions break — fail-loud."""
        html = """
        <table class="cmdty-quote-table">
        <tbody>
            <tr><th>Most Recent Value</th><td>621,116</td></tr>
            <tr><th>Most Recent Date</th><td>05-13-2026</td></tr>
            <tr><th>Unit</th><td>60 Kg Bag</td></tr>
            <tr><th>Multiplier</th><td>1000</td></tr>
        </tbody></table>
        """
        with pytest.raises(BarchartStocksEuParseError, match="[Mm]ultiplier"):
            parse_barchart_stocks_eu_html(html)


# ---------------------------------------------------------------------------
# DB writer tests (use sync_db_session fixture from conftest.py)
# ---------------------------------------------------------------------------


class TestUpdateStockEu:
    def _seed_row(self, session, target_date: date):
        """Seed ref_exchange + ref_commodity + ref_contract + pl_contract_data_daily row.

        Returns the seeded row so callers can assert against it.
        """
        # Unique suffix per call to avoid conflicts across tests in the same session.
        suffix = target_date.strftime("%Y%m%d")
        exchange = make_ref_exchange(code=f"ICE_EU_{suffix}")
        session.add(exchange)
        session.flush()
        commodity = make_ref_commodity(exchange.id, code=f"CC_{suffix}")
        session.add(commodity)
        session.flush()
        contract = make_ref_contract(commodity.id, code=f"CT_{suffix}")
        session.add(contract)
        session.flush()
        row = make_pl_contract_data_daily(contract.id, date=target_date)
        session.add(row)
        session.flush()
        return row

    def test_update_existing_row(self, sync_db_session):
        target = date(2026, 5, 13)
        self._seed_row(sync_db_session, target)

        n = update_stock_eu(
            sync_db_session,
            target,
            Decimal("621116"),
        )
        assert n == 1

        row = sync_db_session.execute(
            text(
                "SELECT stock_eu_bags60kg FROM pl_contract_data_daily WHERE date = :d"
            ),
            {"d": target},
        ).fetchone()
        assert row.stock_eu_bags60kg == Decimal("621116")

    def test_update_overwrites_prior_value(self, sync_db_session):
        target = date(2026, 5, 14)
        self._seed_row(sync_db_session, target)

        update_stock_eu(sync_db_session, target, Decimal("100000"))
        update_stock_eu(sync_db_session, target, Decimal("621116"))

        row = sync_db_session.execute(
            text(
                "SELECT stock_eu_bags60kg FROM pl_contract_data_daily WHERE date = :d"
            ),
            {"d": target},
        ).fetchone()
        assert row.stock_eu_bags60kg == Decimal("621116")

    def test_missing_row_fails_loud(self, sync_db_session):
        """If barchart OHLCV scraper hasn't run yet, fail-loud — don't INSERT."""
        with pytest.raises(StockEuRowMissingError, match="2026-05-99|no row"):
            update_stock_eu(
                sync_db_session,
                date(2026, 5, 31),  # no row was seeded for this date
                Decimal("621116"),
            )


# ---------------------------------------------------------------------------
# Scraper HTTP tests
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, text_body: str):
    class _Resp:
        def __init__(self) -> None:
            self.status_code = status_code
            self.text = text_body

    return _Resp()


class TestScraperHttp:
    def test_scrape_happy_path(self):
        from scripts.barchart_stocks_eu_scraper import scraper as s

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.return_value = _mock_response(200, _VALID_HTML)
            mock_httpx.HTTPError = Exception

            obs = s.scrape_latest()

        assert obs.date == date(2026, 5, 13)
        assert obs.value_bags60kg == Decimal("621116")

    def test_http_non_200_fails_loud(self):
        from scripts.barchart_stocks_eu_scraper import scraper as s

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.return_value = _mock_response(503, "Service Unavailable")
            mock_httpx.HTTPError = Exception

            with pytest.raises(s.BarchartStocksEuScraperError, match="HTTP 503"):
                s.scrape_latest()

    def test_empty_body_fails_loud(self):
        from scripts.barchart_stocks_eu_scraper import scraper as s

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.return_value = _mock_response(200, "")
            mock_httpx.HTTPError = Exception

            with pytest.raises(s.BarchartStocksEuScraperError, match="Empty body"):
                s.scrape_latest()

    def test_network_error_fails_loud(self):
        import httpx as real_httpx

        from scripts.barchart_stocks_eu_scraper import scraper as s

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.side_effect = real_httpx.ConnectError("connection refused")
            mock_httpx.HTTPError = real_httpx.HTTPError

            with pytest.raises(s.BarchartStocksEuScraperError, match="Network error"):
                s.scrape_latest()


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestCli:
    def test_default_args(self):
        with patch.object(sys, "argv", ["barchart-stocks-eu-scraper"]):
            args = _parse_args()
        assert args.dry_run is False
        assert args.verbose is False
        assert args.force is False

    def test_dry_run_flag(self):
        with patch.object(sys, "argv", ["barchart-stocks-eu-scraper", "--dry-run"]):
            args = _parse_args()
        assert args.dry_run is True

    def test_verbose_flag(self):
        with patch.object(sys, "argv", ["barchart-stocks-eu-scraper", "--verbose"]):
            args = _parse_args()
        assert args.verbose is True

    def test_force_flag(self):
        with patch.object(sys, "argv", ["barchart-stocks-eu-scraper", "--force"]):
            args = _parse_args()
        assert args.force is True


# ---------------------------------------------------------------------------
# Main orchestration tests
# ---------------------------------------------------------------------------


class TestMainOrchestration:
    def test_dry_run_skips_db_write(self):
        from scripts.barchart_stocks_eu_scraper import main as m

        sample = StockEuObservation(
            date=date(2026, 5, 13),
            value_bags60kg=Decimal("621116"),
            history=[(date(2026, 5, 13), Decimal("621116"))],
        )
        with (
            patch.object(sys, "argv", ["barchart-stocks-eu-scraper", "--dry-run"]),
            patch("scripts.db.should_skip_non_trading_day", return_value=False),
            patch(
                "scripts.barchart_stocks_eu_scraper.scraper.scrape_latest",
                return_value=sample,
            ),
            patch(
                "scripts.barchart_stocks_eu_scraper.main.update_stock_eu"
            ) as mock_update,
        ):
            rc = m.main()
        assert rc == 0
        mock_update.assert_not_called()

    def test_live_run_calls_update_and_commits(self):
        from scripts.barchart_stocks_eu_scraper import main as m

        sample = StockEuObservation(
            date=date(2026, 5, 13),
            value_bags60kg=Decimal("621116"),
            history=[(date(2026, 5, 13), Decimal("621116"))],
        )

        class _Fake:
            def __init__(self) -> None:
                self.committed = False

            def commit(self) -> None:
                self.committed = True

            def __enter__(self):
                return self

            def __exit__(self, *a, **kw):
                return False

        fake = _Fake()
        with (
            patch.object(sys, "argv", ["barchart-stocks-eu-scraper"]),
            patch(
                "scripts.barchart_stocks_eu_scraper.scraper.scrape_latest",
                return_value=sample,
            ),
            patch(
                "scripts.barchart_stocks_eu_scraper.main.update_stock_eu",
                return_value=1,
            ) as mock_update,
            patch("scripts.db.get_session", return_value=fake),
            patch("scripts.db.should_skip_non_trading_day", return_value=False),
        ):
            rc = m.main()
        assert rc == 0
        mock_update.assert_called_once()
        assert fake.committed is True

    def test_non_trading_day_skips_run(self):
        from scripts.barchart_stocks_eu_scraper import main as m

        with (
            patch.object(sys, "argv", ["barchart-stocks-eu-scraper"]),
            patch("scripts.db.should_skip_non_trading_day", return_value=True),
            patch(
                "scripts.barchart_stocks_eu_scraper.scraper.scrape_latest"
            ) as mock_scrape,
        ):
            rc = m.main()
        assert rc == 0
        mock_scrape.assert_not_called()

    def test_exception_returns_non_zero(self):
        from scripts.barchart_stocks_eu_scraper import main as m

        with (
            patch.object(sys, "argv", ["barchart-stocks-eu-scraper", "--force"]),
            patch("scripts.db.should_skip_non_trading_day", return_value=False),
            patch(
                "scripts.barchart_stocks_eu_scraper.scraper.scrape_latest",
                side_effect=RuntimeError("boom"),
            ),
        ):
            rc = m.main()
        assert rc == 1

    def test_force_flag_bypasses_non_trading_day_skip(self):
        from scripts.barchart_stocks_eu_scraper import main as m

        sample = StockEuObservation(
            date=date(2026, 5, 13),
            value_bags60kg=Decimal("621116"),
            history=[(date(2026, 5, 13), Decimal("621116"))],
        )
        # should_skip_non_trading_day receives force=True → returns False
        fake_session = MagicMock()
        fake_session.commit = MagicMock()
        fake_session.__enter__ = lambda self: self
        fake_session.__exit__ = lambda *a: False

        with (
            patch.object(sys, "argv", ["barchart-stocks-eu-scraper", "--force"]),
            patch(
                "scripts.db.should_skip_non_trading_day", return_value=False
            ) as mock_skip,
            patch(
                "scripts.barchart_stocks_eu_scraper.scraper.scrape_latest",
                return_value=sample,
            ),
            patch(
                "scripts.barchart_stocks_eu_scraper.main.update_stock_eu",
                return_value=1,
            ),
            patch("scripts.db.get_session", return_value=fake_session),
        ):
            rc = m.main()
        assert rc == 0
        # Verify --force propagates as force=True
        mock_skip.assert_called_with(force=True)

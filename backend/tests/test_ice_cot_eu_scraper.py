"""Tests for cc-ice-cot-eu-scraper (ICE Europe COT positioning).

Covers:
  * ICE COT CSV parser (175 cols, filters cocoa EU FutOnly rows)
  * Computed columns (prod_merc_net, m_money_net auto-computed by Postgres)
  * DB writer (UPSERT idempotency, partial-column update)
  * Fail-loud on bad input / network / parse errors
  * CLI flags (--dry-run, --year, --force)

See:
  * docs/user-stories/P1-scrapers-stock-cot-eu.md
  * Source: https://www.theice.com/publicdocs/futures/COTHistYYYY.csv
"""

from __future__ import annotations

import sys
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.models.pipeline import PlCotEuWeekly
from scripts.ice_cot_eu_scraper.db_writer import upsert_cot_eu_rows
from scripts.ice_cot_eu_scraper.main import _parse_args
from scripts.ice_cot_eu_scraper.parser import (
    CotEuCsvParseError,
    CotEuObservation,
    parse_ice_cot_csv,
)


# ---------------------------------------------------------------------------
# Sample ICE COT CSV — minimal valid input
# ---------------------------------------------------------------------------

# Just the columns we care about, plus the filter columns. The real CSV has
# 175 columns; our parser must tolerate that.
_HEADER = (
    "Market_and_Exchange_Names,"
    "As_of_Date_In_Form_YYMMDD,"
    "As_of_Date_Form_MM/DD/YYYY,"
    "Open_Interest_All,"
    "Prod_Merc_Positions_Long_All,Prod_Merc_Positions_Short_All,"
    "M_Money_Positions_Long_All,M_Money_Positions_Short_All,"
    "Other_Rept_Positions_Long_All,Other_Rept_Positions_Short_All,"
    "NonRept_Positions_Long_All,NonRept_Positions_Short_All,"
    "FutOnly_or_Combined\n"
)

_VALID_COCOA_FUTONLY = (
    "ICE Cocoa Futures - ICE Futures Europe,260106,01/06/2026,"
    "161423,80824,81660,6674,24066,15000,12000,8000,9000,"
    "FutOnly\n"
)
_VALID_COCOA_COMBINED = (
    "ICE Cocoa Futures and Options - ICE Futures Europe,260106,01/06/2026,"
    "200000,90000,85000,7000,25000,16000,13000,8500,9500,"
    "Combined\n"
)
_OTHER_MARKET = (
    "ICE Brent Crude Futures - ICE Futures Europe,260106,01/06/2026,"
    "3221926,1119423,1390736,309492,188806,415732,451855,90435,77902,"
    "FutOnly\n"
)


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParseIceCotCsv:
    def test_parses_single_cocoa_futonly_row(self):
        csv = _HEADER + _VALID_COCOA_FUTONLY
        obs = parse_ice_cot_csv(csv)
        assert len(obs) == 1
        o = obs[0]
        assert o.report_date == date(2026, 1, 6)
        assert o.open_interest == 161423
        assert o.prod_merc_long == 80824
        assert o.prod_merc_short == 81660
        assert o.m_money_long == 6674
        assert o.m_money_short == 24066
        assert o.other_rept_long == 15000
        assert o.other_rept_short == 12000
        assert o.non_rept_long == 8000
        assert o.non_rept_short == 9000

    def test_filters_out_combined_rows(self):
        """The 'Combined' (FutOnly+Options) variant must be skipped — we only
        want FutOnly per standard CFTC convention."""
        csv = _HEADER + _VALID_COCOA_FUTONLY + _VALID_COCOA_COMBINED
        obs = parse_ice_cot_csv(csv)
        assert len(obs) == 1
        assert obs[0].open_interest == 161423  # FutOnly value, not Combined

    def test_filters_out_other_markets(self):
        """Only cocoa rows are kept; Brent / Gasoil / etc. are skipped."""
        csv = _HEADER + _OTHER_MARKET + _VALID_COCOA_FUTONLY
        obs = parse_ice_cot_csv(csv)
        assert len(obs) == 1
        assert obs[0].open_interest == 161423

    def test_handles_utf8_bom(self):
        """ICE CSV is served with a UTF-8 BOM (\\ufeff at the start)."""
        csv = "﻿" + _HEADER + _VALID_COCOA_FUTONLY
        obs = parse_ice_cot_csv(csv)
        assert len(obs) == 1

    def test_drops_rows_with_unparseable_date(self):
        bad_date = (
            "ICE Cocoa Futures - ICE Futures Europe,260106,not-a-date,"
            "161423,80824,81660,6674,24066,15000,12000,8000,9000,"
            "FutOnly\n"
        )
        csv = _HEADER + bad_date + _VALID_COCOA_FUTONLY
        obs = parse_ice_cot_csv(csv)
        assert len(obs) == 1
        assert obs[0].report_date == date(2026, 1, 6)

    def test_drops_rows_with_missing_open_interest(self):
        missing_oi = (
            "ICE Cocoa Futures - ICE Futures Europe,260106,01/06/2026,"
            ",80824,81660,6674,24066,15000,12000,8000,9000,"
            "FutOnly\n"
        )
        csv = _HEADER + missing_oi + _VALID_COCOA_FUTONLY
        obs = parse_ice_cot_csv(csv)
        # The first row is dropped (no OI), the second kept.
        assert len(obs) == 1
        assert obs[0].open_interest == 161423

    def test_empty_body_returns_empty(self):
        assert parse_ice_cot_csv("") == []

    def test_header_only_returns_empty(self):
        assert parse_ice_cot_csv(_HEADER) == []

    def test_missing_required_column_fails_loud(self):
        """If the header lacks a required column, fail-loud."""
        bad_header = "FOO,BAR,BAZ\n1,2,3\n"
        with pytest.raises(CotEuCsvParseError, match="Market_and_Exchange_Names"):
            parse_ice_cot_csv(bad_header)

    def test_non_string_input_fails_loud(self):
        with pytest.raises(CotEuCsvParseError):
            parse_ice_cot_csv(None)  # type: ignore[arg-type]

    def test_records_returned_sorted_by_report_date(self):
        row1 = (
            "ICE Cocoa Futures - ICE Futures Europe,260120,01/20/2026,"
            "163806,79680,80769,6882,28153,15000,12000,8000,9000,"
            "FutOnly\n"
        )
        row2 = (
            "ICE Cocoa Futures - ICE Futures Europe,260106,01/06/2026,"
            "161423,80824,81660,6674,24066,15000,12000,8000,9000,"
            "FutOnly\n"
        )
        csv = _HEADER + row1 + row2
        obs = parse_ice_cot_csv(csv)
        assert [o.report_date for o in obs] == [
            date(2026, 1, 6),
            date(2026, 1, 20),
        ]


# ---------------------------------------------------------------------------
# release_date derivation
# ---------------------------------------------------------------------------


class TestReleaseDateDerivation:
    """ICE publishes Friday for the Tuesday snapshot → release_date = report_date + 3 days."""

    def test_tuesday_report_yields_friday_release(self):
        csv = _HEADER + _VALID_COCOA_FUTONLY  # 01/06/2026 = Tuesday
        obs = parse_ice_cot_csv(csv)
        # 2026-01-06 = Tuesday → +3 days = 2026-01-09 = Friday
        assert obs[0].release_date == date(2026, 1, 9)
        # Sanity: Friday weekday = 4
        assert obs[0].release_date.weekday() == 4


# ---------------------------------------------------------------------------
# DB writer tests
# ---------------------------------------------------------------------------


class TestUpsertCotEuRows:
    def test_inserts_new_row_with_generated_net(self, sync_db_session):
        obs = [
            CotEuObservation(
                report_date=date(2026, 1, 6),
                release_date=date(2026, 1, 9),
                open_interest=161423,
                prod_merc_long=80824,
                prod_merc_short=81660,
                m_money_long=6674,
                m_money_short=24066,
                other_rept_long=15000,
                other_rept_short=12000,
                non_rept_long=8000,
                non_rept_short=9000,
            ),
        ]
        n = upsert_cot_eu_rows(sync_db_session, obs)
        assert n == 1

        row = sync_db_session.execute(
            text(
                "SELECT prod_merc_long, prod_merc_short, prod_merc_net, "
                "m_money_long, m_money_short, m_money_net, open_interest "
                "FROM pl_cot_eu_weekly WHERE release_date = :d"
            ),
            {"d": date(2026, 1, 9)},
        ).fetchone()
        # Stored values
        assert row.prod_merc_long == 80824
        assert row.prod_merc_short == 81660
        # GENERATED columns auto-computed by Postgres
        assert row.prod_merc_net == 80824 - 81660
        assert row.m_money_long == 6674
        assert row.m_money_short == 24066
        assert row.m_money_net == 6674 - 24066
        assert row.open_interest == 161423

    def test_upsert_idempotent(self, sync_db_session):
        obs = [
            CotEuObservation(
                report_date=date(2026, 1, 13),
                release_date=date(2026, 1, 16),
                open_interest=162896,
                prod_merc_long=83874,
                prod_merc_short=83516,
                m_money_long=7260,
                m_money_short=25079,
                other_rept_long=15500,
                other_rept_short=12300,
                non_rept_long=8200,
                non_rept_short=9100,
            ),
        ]
        upsert_cot_eu_rows(sync_db_session, obs)
        upsert_cot_eu_rows(sync_db_session, obs)  # 2nd run

        count = sync_db_session.execute(
            text("SELECT count(*) FROM pl_cot_eu_weekly WHERE release_date = :d"),
            {"d": date(2026, 1, 16)},
        ).scalar()
        assert count == 1

    def test_upsert_updates_existing_row(self, sync_db_session):
        # First insert with one set of values
        obs_old = [
            CotEuObservation(
                report_date=date(2026, 1, 20),
                release_date=date(2026, 1, 23),
                open_interest=100000,
                prod_merc_long=50000,
                prod_merc_short=50000,
                m_money_long=5000,
                m_money_short=5000,
                other_rept_long=10000,
                other_rept_short=10000,
                non_rept_long=5000,
                non_rept_short=5000,
            ),
        ]
        upsert_cot_eu_rows(sync_db_session, obs_old)

        # Then update with corrected values (e.g. ICE re-published)
        obs_new = [
            CotEuObservation(
                report_date=date(2026, 1, 20),
                release_date=date(2026, 1, 23),
                open_interest=163806,
                prod_merc_long=79680,
                prod_merc_short=80769,
                m_money_long=6882,
                m_money_short=28153,
                other_rept_long=15600,
                other_rept_short=12400,
                non_rept_long=8300,
                non_rept_short=9200,
            ),
        ]
        upsert_cot_eu_rows(sync_db_session, obs_new)

        row = sync_db_session.execute(
            text(
                "SELECT open_interest, prod_merc_net, m_money_net "
                "FROM pl_cot_eu_weekly WHERE release_date = :d"
            ),
            {"d": date(2026, 1, 23)},
        ).fetchone()
        assert row.open_interest == 163806
        # GENERATED net recomputed on update
        assert row.prod_merc_net == 79680 - 80769
        assert row.m_money_net == 6882 - 28153

    def test_empty_records_is_noop(self, sync_db_session):
        n = upsert_cot_eu_rows(sync_db_session, [])
        assert n == 0
        count = sync_db_session.execute(
            text("SELECT count(*) FROM pl_cot_eu_weekly")
        ).scalar()
        assert count == 0


# ---------------------------------------------------------------------------
# Scraper HTTP tests
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, text_body: str):
    class _Resp:
        def __init__(self) -> None:
            self.status_code = status_code
            self.text = text_body

    return _Resp()


_LIVE_CSV = _HEADER + _VALID_COCOA_FUTONLY + _OTHER_MARKET


class TestScraperHttp:
    def test_scrape_happy_path(self):
        from scripts.ice_cot_eu_scraper import scraper as s

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.return_value = _mock_response(200, _LIVE_CSV)
            mock_httpx.HTTPError = Exception

            obs = s.scrape_year(2026)

        assert len(obs) == 1
        assert obs[0].report_date == date(2026, 1, 6)

    def test_http_non_200_fails_loud(self):
        from scripts.ice_cot_eu_scraper import scraper as s

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.return_value = _mock_response(503, "Service Unavailable")
            mock_httpx.HTTPError = Exception

            with pytest.raises(s.IceCotEuScraperError, match="HTTP 503"):
                s.scrape_year(2026)

    def test_empty_body_fails_loud(self):
        from scripts.ice_cot_eu_scraper import scraper as s

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.return_value = _mock_response(200, "")
            mock_httpx.HTTPError = Exception

            with pytest.raises(s.IceCotEuScraperError, match="Empty body"):
                s.scrape_year(2026)

    def test_no_cocoa_rows_fails_loud(self):
        """If the CSV has no cocoa EU rows, fail-loud — masks format change."""
        from scripts.ice_cot_eu_scraper import scraper as s

        only_brent = _HEADER + _OTHER_MARKET
        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.return_value = _mock_response(200, only_brent)
            mock_httpx.HTTPError = Exception

            with pytest.raises(s.IceCotEuScraperError, match="no cocoa"):
                s.scrape_year(2026)

    def test_network_error_fails_loud(self):
        import httpx as real_httpx

        from scripts.ice_cot_eu_scraper import scraper as s

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.side_effect = real_httpx.ConnectError("connection refused")
            mock_httpx.HTTPError = real_httpx.HTTPError

            with pytest.raises(s.IceCotEuScraperError, match="Network error"):
                s.scrape_year(2026)


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestCli:
    def test_default_args(self):
        with patch.object(sys, "argv", ["ice-cot-eu-scraper"]):
            args = _parse_args()
        assert args.dry_run is False
        assert args.year is None
        assert args.verbose is False

    def test_dry_run_flag(self):
        with patch.object(sys, "argv", ["ice-cot-eu-scraper", "--dry-run"]):
            args = _parse_args()
        assert args.dry_run is True

    def test_year_flag(self):
        with patch.object(sys, "argv", ["ice-cot-eu-scraper", "--year", "2024"]):
            args = _parse_args()
        assert args.year == 2024

    def test_combine_flags(self):
        with patch.object(
            sys,
            "argv",
            ["ice-cot-eu-scraper", "--year", "2025", "--dry-run", "--verbose"],
        ):
            args = _parse_args()
        assert args.year == 2025
        assert args.dry_run is True
        assert args.verbose is True


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


class TestMainOrchestration:
    def test_dry_run_skips_db_write(self):
        from scripts.ice_cot_eu_scraper import main as m

        sample = [
            CotEuObservation(
                report_date=date(2026, 1, 6),
                release_date=date(2026, 1, 9),
                open_interest=161423,
                prod_merc_long=80824,
                prod_merc_short=81660,
                m_money_long=6674,
                m_money_short=24066,
                other_rept_long=15000,
                other_rept_short=12000,
                non_rept_long=8000,
                non_rept_short=9000,
            ),
        ]
        with (
            patch.object(sys, "argv", ["ice-cot-eu-scraper", "--dry-run"]),
            patch("scripts.db.should_skip_non_trading_day", return_value=False),
            patch(
                "scripts.ice_cot_eu_scraper.scraper.scrape_year", return_value=sample
            ),
            patch("scripts.ice_cot_eu_scraper.main.upsert_cot_eu_rows") as mock_upsert,
        ):
            rc = m.main()
        assert rc == 0
        mock_upsert.assert_not_called()

    def test_live_run_calls_upsert_and_commits(self):
        from scripts.ice_cot_eu_scraper import main as m

        sample = [
            CotEuObservation(
                report_date=date(2026, 1, 6),
                release_date=date(2026, 1, 9),
                open_interest=161423,
                prod_merc_long=80824,
                prod_merc_short=81660,
                m_money_long=6674,
                m_money_short=24066,
                other_rept_long=15000,
                other_rept_short=12000,
                non_rept_long=8000,
                non_rept_short=9000,
            ),
        ]

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
            patch.object(sys, "argv", ["ice-cot-eu-scraper"]),
            patch(
                "scripts.ice_cot_eu_scraper.scraper.scrape_year", return_value=sample
            ),
            patch(
                "scripts.ice_cot_eu_scraper.main.upsert_cot_eu_rows",
                return_value=1,
            ) as mock_upsert,
            patch("scripts.db.get_session", return_value=fake),
            patch("scripts.db.should_skip_non_trading_day", return_value=False),
        ):
            rc = m.main()
        assert rc == 0
        mock_upsert.assert_called_once()
        assert fake.committed is True

    def test_exception_returns_non_zero(self):
        from scripts.ice_cot_eu_scraper import main as m

        with (
            patch.object(sys, "argv", ["ice-cot-eu-scraper", "--force"]),
            patch(
                "scripts.ice_cot_eu_scraper.scraper.scrape_year",
                side_effect=RuntimeError("boom"),
            ),
        ):
            rc = m.main()
        assert rc == 1


# ---------------------------------------------------------------------------
# Model sanity
# ---------------------------------------------------------------------------


class TestPlCotEuWeeklyModel:
    def test_row_round_trips_via_orm(self, sync_db_session):
        row = PlCotEuWeekly(
            report_date=date(2026, 2, 3),
            release_date=date(2026, 2, 6),
            contract_market="cocoa",
            open_interest=182109,
            prod_merc_long=87645,
            prod_merc_short=87501,
            m_money_long=9069,
            m_money_short=30457,
        )
        sync_db_session.add(row)
        sync_db_session.flush()

        fetched = sync_db_session.execute(
            text(
                "SELECT prod_merc_net, m_money_net, open_interest, contract_market "
                "FROM pl_cot_eu_weekly WHERE release_date = :d"
            ),
            {"d": date(2026, 2, 6)},
        ).fetchone()
        assert fetched.contract_market == "cocoa"
        assert fetched.open_interest == 182109
        assert fetched.prod_merc_net == 87645 - 87501
        assert fetched.m_money_net == 9069 - 30457

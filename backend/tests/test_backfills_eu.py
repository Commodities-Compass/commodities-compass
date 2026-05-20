"""Tests for the EU scrapers' one-shot backfills (ICE COT EU + Stock EU).

ICE COT EU backfill iterates over calendar years (newest first) and stops
when ICE returns 404. Stock EU backfill uses the Barchart cmdty history
endpoint (or Wayback Machine fallback).
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from scripts.ice_cot_eu_scraper.backfill import (
    IceCotEuBackfillError,
    backfill_all_years,
)
from scripts.ice_cot_eu_scraper.backfill import _parse_args as _ice_parse_args
from scripts.ice_cot_eu_scraper.parser import CotEuObservation
from scripts.ice_cot_eu_scraper.scraper import IceCotEuScraperError


# ---------------------------------------------------------------------------
# ICE COT EU backfill — iterate years, stop on 404
# ---------------------------------------------------------------------------


def _obs(report: date, release: date | None = None) -> CotEuObservation:
    return CotEuObservation(
        report_date=report,
        release_date=release or report,
        open_interest=100000,
        prod_merc_long=50000,
        prod_merc_short=50000,
        m_money_long=5000,
        m_money_short=5000,
        other_rept_long=10000,
        other_rept_short=10000,
        non_rept_long=5000,
        non_rept_short=5000,
    )


class TestBackfillAllYears:
    def test_iterates_from_start_year_downward(self):
        """Walks newest → oldest year so partial runs prefer fresh data."""
        with (
            patch("scripts.ice_cot_eu_scraper.backfill.scrape_year") as mock_scrape,
            patch(
                "scripts.ice_cot_eu_scraper.backfill.upsert_cot_eu_rows"
            ) as mock_upsert,
        ):
            mock_scrape.return_value = [_obs(date(2024, 1, 7))]
            mock_upsert.return_value = 1

            n = backfill_all_years(
                session=MagicMock(), start_year=2024, floor_year=2024
            )

        assert mock_scrape.call_args_list[0].args == (2024,)
        assert n == 1

    def test_stops_when_year_returns_404(self):
        """ICE returns 404 below the history floor — backfill stops cleanly."""
        with (
            patch("scripts.ice_cot_eu_scraper.backfill.scrape_year") as mock_scrape,
            patch(
                "scripts.ice_cot_eu_scraper.backfill.upsert_cot_eu_rows",
                return_value=1,
            ),
        ):

            def side_effect(year: int):
                if year >= 2023:
                    return [_obs(date(year, 1, 7))]
                raise IceCotEuScraperError(f"HTTP 404 fetching COTHist{year}.csv: ...")

            mock_scrape.side_effect = side_effect
            n = backfill_all_years(
                session=MagicMock(), start_year=2025, floor_year=2020
            )

        # Successfully scraped 2025, 2024, 2023 → 3 years × 1 row each
        assert n == 3

    def test_floor_year_is_inclusive_lower_bound(self):
        """``floor_year=2021`` means we try 2021 but never 2020."""
        called_years = []
        with (
            patch("scripts.ice_cot_eu_scraper.backfill.scrape_year") as mock_scrape,
            patch(
                "scripts.ice_cot_eu_scraper.backfill.upsert_cot_eu_rows",
                return_value=1,
            ),
        ):

            def side_effect(year: int):
                called_years.append(year)
                return [_obs(date(year, 1, 7))]

            mock_scrape.side_effect = side_effect
            backfill_all_years(session=MagicMock(), start_year=2023, floor_year=2021)

        assert called_years == [2023, 2022, 2021]

    def test_stops_on_no_cocoa_rows_pre_launch(self):
        """Files for 2011-2013 exist but list no cocoa EU market (launched Sept 2014).
        The scraper fails-loud with 'no cocoa' — backfill treats this like 404."""
        with (
            patch("scripts.ice_cot_eu_scraper.backfill.scrape_year") as mock_scrape,
            patch(
                "scripts.ice_cot_eu_scraper.backfill.upsert_cot_eu_rows",
                return_value=1,
            ),
        ):

            def side_effect(year: int):
                if year >= 2014:
                    return [_obs(date(year, 1, 7))]
                raise IceCotEuScraperError(
                    f"ICE COT CSV for {year} contained no cocoa EU FutOnly rows (...). "
                    "Check the CSV format or the cocoa market name string."
                )

            mock_scrape.side_effect = side_effect
            n = backfill_all_years(
                session=MagicMock(), start_year=2015, floor_year=2010
            )

        # 2015 + 2014 successful, 2013 stops → 2 years × 1 row
        assert n == 2

    def test_non_404_error_propagates(self):
        """A 503 or parser error must NOT be silenced — fail-loud rule."""
        with (
            patch("scripts.ice_cot_eu_scraper.backfill.scrape_year") as mock_scrape,
            patch(
                "scripts.ice_cot_eu_scraper.backfill.upsert_cot_eu_rows",
                return_value=1,
            ),
        ):
            mock_scrape.side_effect = IceCotEuScraperError(
                "HTTP 503 fetching COTHist2024.csv: ..."
            )
            with pytest.raises(IceCotEuBackfillError, match="503"):
                backfill_all_years(
                    session=MagicMock(), start_year=2024, floor_year=2020
                )

    def test_empty_year_skipped_without_error(self):
        """Some years may legitimately have 0 cocoa rows (data drift); log + continue."""
        with (
            patch("scripts.ice_cot_eu_scraper.backfill.scrape_year") as mock_scrape,
            patch(
                "scripts.ice_cot_eu_scraper.backfill.upsert_cot_eu_rows"
            ) as mock_upsert,
        ):
            # Scraper's contract: empty list never happens (it fails-loud).
            # But if scraper changes, backfill must handle gracefully.
            mock_scrape.side_effect = lambda y: (
                [_obs(date(y, 1, 7))] if y == 2024 else []
            )
            # Upsert returns count of rows it received.
            mock_upsert.side_effect = lambda session, obs: len(list(obs))
            n = backfill_all_years(
                session=MagicMock(), start_year=2024, floor_year=2023
            )

        # 2024 yielded 1 row, 2023 yielded 0 rows → total 1.
        assert n == 1


class TestIceBackfillCli:
    def test_default_floor_year(self):
        with patch.object(sys, "argv", ["ice-cot-eu-scraper-backfill"]):
            args = _ice_parse_args()
        # Default floor reflects ICE Cocoa Europe launch (Sept 2014, probed 2026-05-20).
        assert args.floor_year == 2014
        assert args.start_year is None
        assert args.dry_run is False
        assert args.verify is False

    def test_start_year_override(self):
        with patch.object(
            sys, "argv", ["ice-cot-eu-scraper-backfill", "--start-year", "2020"]
        ):
            args = _ice_parse_args()
        assert args.start_year == 2020

    def test_dry_run_flag(self):
        with patch.object(sys, "argv", ["ice-cot-eu-scraper-backfill", "--dry-run"]):
            args = _ice_parse_args()
        assert args.dry_run is True

    def test_verify_flag(self):
        with patch.object(sys, "argv", ["ice-cot-eu-scraper-backfill", "--verify"]):
            args = _ice_parse_args()
        assert args.verify is True


# ---------------------------------------------------------------------------
# Stock EU backfill — Barchart history range
# ---------------------------------------------------------------------------


class TestStockEuBackfillCli:
    def test_default_args(self):
        from scripts.barchart_stocks_eu_scraper.backfill import (
            _parse_args as _stock_parse_args,
        )

        with patch.object(sys, "argv", ["barchart-stocks-eu-scraper-backfill"]):
            args = _stock_parse_args()
        # Default floor is Barchart's First Value Date observed in spike.
        assert args.floor_date == date(2012, 2, 7)
        assert args.dry_run is False

    def test_floor_date_override(self):
        from scripts.barchart_stocks_eu_scraper.backfill import (
            _parse_args as _stock_parse_args,
        )

        with patch.object(
            sys,
            "argv",
            ["barchart-stocks-eu-scraper-backfill", "--floor-date", "2020-01-01"],
        ):
            args = _stock_parse_args()
        assert args.floor_date == date(2020, 1, 1)


class TestStockEuBackfillWalker:
    """The Stock EU backfill is constrained by the daily-only HTML format:
    Barchart's `cmdty/data/fundamental/explore` only shows 7-day history per
    request. The backfill walks Wayback Machine snapshots paginating by date.
    """

    def test_walks_dates_in_descending_order(self):
        """Walk newest → oldest so partial runs preserve most-recent data."""
        from scripts.barchart_stocks_eu_scraper.backfill import (
            backfill_via_wayback,
        )
        from scripts.barchart_stocks_eu_scraper.parser import StockEuObservation

        called_dates: list[date] = []

        def fake_fetch_snapshot(d: date) -> StockEuObservation:
            called_dates.append(d)
            return StockEuObservation(
                date=d, value_bags60kg=Decimal("100000"), history=[]
            )

        with (
            patch(
                "scripts.barchart_stocks_eu_scraper.backfill.fetch_wayback_snapshot",
                side_effect=fake_fetch_snapshot,
            ),
            patch(
                "scripts.barchart_stocks_eu_scraper.backfill.update_stock_eu",
                return_value=1,
            ),
        ):
            backfill_via_wayback(
                session=MagicMock(),
                start_date=date(2026, 5, 13),
                floor_date=date(2026, 5, 11),
                step_days=1,
                throttle_seconds=0.0,
            )

        # 2026-05-13 → 2026-05-12 → 2026-05-11
        assert called_dates == [
            date(2026, 5, 13),
            date(2026, 5, 12),
            date(2026, 5, 11),
        ]

    def test_missing_ohlcv_row_skips_but_continues(self):
        """If pl_contract_data_daily has no row for a date, log + continue.

        Backfill MUST be tolerant of OHLCV gaps — historical EU stocks data
        is denser than US OHLCV in some periods. Skipping is correct.
        """
        from scripts.barchart_stocks_eu_scraper.backfill import (
            backfill_via_wayback,
        )
        from scripts.barchart_stocks_eu_scraper.db_writer import (
            StockEuRowMissingError,
        )
        from scripts.barchart_stocks_eu_scraper.parser import StockEuObservation

        with (
            patch(
                "scripts.barchart_stocks_eu_scraper.backfill.fetch_wayback_snapshot",
                return_value=StockEuObservation(
                    date=date(2026, 5, 13),
                    value_bags60kg=Decimal("100000"),
                    history=[],
                ),
            ),
            patch(
                "scripts.barchart_stocks_eu_scraper.backfill.update_stock_eu",
                side_effect=StockEuRowMissingError("no row for date=2026-05-13"),
            ),
        ):
            result = backfill_via_wayback(
                session=MagicMock(),
                start_date=date(2026, 5, 13),
                floor_date=date(2026, 5, 13),
                step_days=1,
                throttle_seconds=0.0,
            )

        # 0 updates because no OHLCV row existed
        assert result.updated == 0
        assert result.skipped_missing_ohlcv == 1

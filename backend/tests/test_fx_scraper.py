"""Tests for cc-fx-scraper (ECB SDMX FX ingestion).

Covers:
  * ECB SDMX CSV parser (header, NaT/NaN dropped, malformed rows)
  * Formula correctness (DXY proxy = 1/usd_per_eur, GBPUSD = usd_per_eur/gbp_per_eur)
  * combine_to_fx_records (aligns USD/EUR + GBP/EUR by date)
  * DB writer (UPSERT preserves ENSO columns, idempotent)
  * Fail-loud on network/HTTP/parse errors
  * CLI flags (--dry-run, --force)

See:
  * docs/user-stories/P1-scraper-fx.md
  * docs/onboarding/ingest_fx.py (R&D source code being ported)
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.models.pipeline import PlExternalIndicator
from scripts.fx_scraper.db_writer import upsert_fx_rows
from scripts.fx_scraper.main import _parse_args
from scripts.fx_scraper.parser import (
    EcbCsvParseError,
    EcbObservation,
    parse_ecb_csv,
)
from scripts.fx_scraper.scraper import FxRecord, combine_to_fx_records


# ---------------------------------------------------------------------------
# ECB CSV parser tests
# ---------------------------------------------------------------------------


class TestParseEcbCsv:
    """ECB SDMX CSV format: header + data rows with TIME_PERIOD + OBS_VALUE."""

    NOMINAL_CSV = (
        "KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
        "D.USD.EUR.SP00.A,2024-01-02,1.1042,A\n"
        "D.USD.EUR.SP00.A,2024-01-03,1.0925,A\n"
        "D.USD.EUR.SP00.A,2024-01-04,1.0944,A\n"
    )

    def test_parses_nominal_rows(self):
        obs = parse_ecb_csv(self.NOMINAL_CSV)
        assert len(obs) == 3
        assert obs[0].date == date(2024, 1, 2)
        assert obs[0].value == 1.1042
        assert obs[-1].date == date(2024, 1, 4)
        # Sorted ascending
        for i in range(1, len(obs)):
            assert obs[i].date > obs[i - 1].date

    def test_drops_rows_with_missing_value(self):
        csv = (
            "KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
            "D.USD.EUR.SP00.A,2024-01-02,1.10,A\n"
            "D.USD.EUR.SP00.A,2024-01-03,,M\n"  # OBS_VALUE empty
            "D.USD.EUR.SP00.A,2024-01-04,NaN,A\n"  # literal NaN
            "D.USD.EUR.SP00.A,2024-01-05,1.11,A\n"
        )
        obs = parse_ecb_csv(csv)
        # Only the 2 valid rows remain
        dates = [o.date for o in obs]
        assert dates == [date(2024, 1, 2), date(2024, 1, 5)]

    def test_drops_rows_with_malformed_date(self):
        csv = (
            "KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
            "D.USD.EUR.SP00.A,not-a-date,1.10,A\n"
            "D.USD.EUR.SP00.A,2024-01-03,1.11,A\n"
        )
        obs = parse_ecb_csv(csv)
        assert len(obs) == 1
        assert obs[0].date == date(2024, 1, 3)

    def test_empty_body_returns_empty(self):
        assert parse_ecb_csv("") == []

    def test_header_only_returns_empty(self):
        assert parse_ecb_csv("KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n") == []

    def test_missing_required_columns_fails_loud(self):
        """Header without TIME_PERIOD or OBS_VALUE → raise (no silent drop)."""
        csv = "KEY,FOO,BAR\nx,1,2\n"
        with pytest.raises(EcbCsvParseError, match="TIME_PERIOD"):
            parse_ecb_csv(csv)

    def test_raises_on_non_string(self):
        with pytest.raises(EcbCsvParseError):
            parse_ecb_csv(None)  # type: ignore[arg-type]

    def test_handles_extra_unrelated_columns(self):
        """ECB sometimes adds OBS_CONF, OBS_PRE_BREAK, etc. — parser must ignore."""
        csv = (
            "KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS,OBS_CONF,OBS_PRE_BREAK\n"
            "D.USD.EUR.SP00.A,2024-06-01,1.0850,A,F,\n"
        )
        obs = parse_ecb_csv(csv)
        assert len(obs) == 1
        assert obs[0].value == 1.0850


# ---------------------------------------------------------------------------
# Formula / combine tests
# ---------------------------------------------------------------------------


class TestCombineToFxRecords:
    """Verify the derived-value math + alignment between USD/EUR and GBP/EUR."""

    def test_dxy_proxy_formula(self):
        """DXY proxy = 1 / usd_per_eur (rises when USD strengthens)."""
        usd = [EcbObservation(date=date(2024, 1, 2), value=1.10)]
        gbp = []
        records = combine_to_fx_records(usd, gbp)
        assert len(records) == 1
        # DXY = 1 / 1.10 ≈ 0.9091
        assert records[0].fx_dxy_proxy == pytest.approx(1.0 / 1.10, rel=1e-6)
        # eurusd = 1/usd_per_eur (alias)
        assert records[0].fx_eurusd == pytest.approx(1.0 / 1.10, rel=1e-6)
        # No GBP data → gbpusd and gbpeur are None
        assert records[0].fx_gbpusd is None
        assert records[0].fx_gbpeur is None

    def test_gbpusd_formula_inner_join(self):
        """GBPUSD = usd_per_eur / gbp_per_eur. Both series must have value."""
        target = date(2024, 1, 3)
        usd = [EcbObservation(date=target, value=1.10)]
        gbp = [EcbObservation(date=target, value=0.86)]
        records = combine_to_fx_records(usd, gbp)
        assert len(records) == 1
        # GBPUSD = 1.10 / 0.86 ≈ 1.279
        assert records[0].fx_gbpusd == pytest.approx(1.10 / 0.86, rel=1e-6)
        assert records[0].fx_gbpeur == pytest.approx(0.86, rel=1e-6)
        assert records[0].fx_dxy_proxy == pytest.approx(1.0 / 1.10, rel=1e-6)
        assert records[0].fx_eurusd == pytest.approx(1.0 / 1.10, rel=1e-6)

    def test_date_only_in_one_series_keeps_partial_record(self):
        """A date present only in USD/EUR yields a row with gbp_* = None."""
        usd = [
            EcbObservation(date=date(2024, 1, 2), value=1.10),
            EcbObservation(date=date(2024, 1, 3), value=1.11),
        ]
        gbp = [
            EcbObservation(date=date(2024, 1, 3), value=0.86),
        ]
        records = combine_to_fx_records(usd, gbp)
        # Both dates emit records (union by date, not inner join)
        records_by_date = {r.date: r for r in records}
        assert set(records_by_date) == {date(2024, 1, 2), date(2024, 1, 3)}
        # 2024-01-02: only USD → gbpusd None
        assert records_by_date[date(2024, 1, 2)].fx_gbpusd is None
        # 2024-01-03: both → gbpusd populated
        assert records_by_date[date(2024, 1, 3)].fx_gbpusd is not None

    def test_zero_usd_per_eur_is_safe(self):
        """Defensive: a usd_per_eur of 0 (impossible in practice) must NOT
        crash with ZeroDivisionError. Treat as missing.

        Contract: the row is emitted for auditability (so we don't silently
        drop a date), but the divide-by-zero columns are None.
        """
        usd = [EcbObservation(date=date(2024, 1, 2), value=0.0)]
        gbp = []
        records = combine_to_fx_records(usd, gbp)
        assert len(records) == 1
        assert records[0].fx_dxy_proxy is None
        assert records[0].fx_eurusd is None
        assert records[0].fx_gbpusd is None
        assert records[0].fx_gbpeur is None

    def test_empty_inputs_return_empty(self):
        assert combine_to_fx_records([], []) == []

    def test_dates_returned_sorted(self):
        usd = [
            EcbObservation(date=date(2024, 1, 5), value=1.10),
            EcbObservation(date=date(2024, 1, 2), value=1.11),
        ]
        records = combine_to_fx_records(usd, [])
        assert [r.date for r in records] == [
            date(2024, 1, 2),
            date(2024, 1, 5),
        ]


# ---------------------------------------------------------------------------
# DB writer tests — partial UPSERT preserves ENSO columns
# ---------------------------------------------------------------------------


class TestUpsertFxRows:
    """Verify UPSERT writes FX columns + leaves ENSO columns untouched.

    The hard rule (P1-scraper-fx.md §4): writing FX must NOT touch
    enso_oni_month / enso_nino34_anomaly. The ENSO scraper writes those
    independently via partial UPSERT.
    """

    def test_inserts_new_rows(self, sync_db_session):
        records = [
            FxRecord(
                date=date(2024, 1, 2),
                fx_dxy_proxy=0.9091,
                fx_gbpusd=1.2791,
                fx_eurusd=0.9091,
                fx_gbpeur=0.8600,
            ),
        ]
        n = upsert_fx_rows(sync_db_session, records)
        assert n == 1

        row = sync_db_session.execute(
            text(
                "SELECT enso_oni_month, fx_dxy_proxy, fx_gbpusd, "
                "fx_eurusd, fx_gbpeur FROM pl_external_indicator "
                "WHERE date = :d"
            ),
            {"d": date(2024, 1, 2)},
        ).fetchone()
        assert row.enso_oni_month is None
        assert row.fx_dxy_proxy == Decimal("0.909100")
        assert row.fx_gbpusd == Decimal("1.279100")
        assert row.fx_eurusd == Decimal("0.909100")
        assert row.fx_gbpeur == Decimal("0.860000")

    def test_upsert_is_idempotent(self, sync_db_session):
        records = [
            FxRecord(
                date=date(2024, 2, 1),
                fx_dxy_proxy=0.91,
                fx_gbpusd=1.27,
                fx_eurusd=0.91,
                fx_gbpeur=0.86,
            )
        ]
        upsert_fx_rows(sync_db_session, records)
        upsert_fx_rows(sync_db_session, records)
        count = sync_db_session.execute(
            text("SELECT count(*) FROM pl_external_indicator WHERE date = :d"),
            {"d": date(2024, 2, 1)},
        ).scalar()
        assert count == 1

    def test_upsert_preserves_enso_columns(self, sync_db_session):
        """Critical: FX scraper writes must NOT clobber ENSO values written by
        the ENSO scraper. Pre-seed an ENSO row, then write FX on same date,
        verify ENSO columns survive.
        """
        target = date(2024, 3, 1)
        # Pre-seed an ENSO-only row (simulates enso_scraper writing first)
        sync_db_session.execute(
            text(
                "INSERT INTO pl_external_indicator "
                "(date, enso_oni_month, enso_nino34_anomaly) "
                "VALUES (:d, :oni, :nin)"
            ),
            {"d": target, "oni": Decimal("0.5"), "nin": Decimal("0.6")},
        )
        sync_db_session.flush()

        # Now FX scraper writes on the same date
        upsert_fx_rows(
            sync_db_session,
            [
                FxRecord(
                    date=target,
                    fx_dxy_proxy=0.91,
                    fx_gbpusd=1.27,
                    fx_eurusd=0.91,
                    fx_gbpeur=0.86,
                )
            ],
        )

        row = sync_db_session.execute(
            text(
                "SELECT enso_oni_month, enso_nino34_anomaly, "
                "fx_dxy_proxy, fx_gbpusd "
                "FROM pl_external_indicator WHERE date = :d"
            ),
            {"d": target},
        ).fetchone()
        # ENSO preserved (THE rule)
        assert row.enso_oni_month == Decimal("0.5000")
        assert row.enso_nino34_anomaly == Decimal("0.6000")
        # FX written
        assert row.fx_dxy_proxy == Decimal("0.910000")
        assert row.fx_gbpusd == Decimal("1.270000")

    def test_partial_record_leaves_null_columns(self, sync_db_session):
        """A FxRecord with only some fx_* populated → DB row has nulls where
        the record had None. Other columns (ENSO + other FX scrapers) stay
        untouched if pre-existing.
        """
        target = date(2024, 4, 1)
        records = [
            FxRecord(
                date=target,
                fx_dxy_proxy=0.91,
                fx_gbpusd=None,
                fx_eurusd=0.91,
                fx_gbpeur=None,
            ),
        ]
        upsert_fx_rows(sync_db_session, records)

        row = sync_db_session.execute(
            text(
                "SELECT fx_dxy_proxy, fx_gbpusd, fx_eurusd, fx_gbpeur "
                "FROM pl_external_indicator WHERE date = :d"
            ),
            {"d": target},
        ).fetchone()
        assert row.fx_dxy_proxy == Decimal("0.910000")
        assert row.fx_gbpusd is None
        assert row.fx_eurusd == Decimal("0.910000")
        assert row.fx_gbpeur is None

    def test_empty_records_is_noop(self, sync_db_session):
        n = upsert_fx_rows(sync_db_session, [])
        assert n == 0
        count = sync_db_session.execute(
            text("SELECT count(*) FROM pl_external_indicator")
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


_SAMPLE_USD_EUR_CSV = (
    "KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
    "D.USD.EUR.SP00.A,2024-01-02,1.10,A\n"
    "D.USD.EUR.SP00.A,2024-01-03,1.11,A\n"
)
_SAMPLE_GBP_EUR_CSV = (
    "KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
    "D.GBP.EUR.SP00.A,2024-01-02,0.86,A\n"
    "D.GBP.EUR.SP00.A,2024-01-03,0.87,A\n"
)


class TestScraperHttp:
    def test_scrape_all_combines_two_series(self):
        from scripts.fx_scraper import scraper as s

        # Mock httpx.get to return USD/EUR then GBP/EUR depending on URL.
        def fake_get(url, **_kwargs):
            if "USD.EUR" in url:
                return _mock_response(200, _SAMPLE_USD_EUR_CSV)
            if "GBP.EUR" in url:
                return _mock_response(200, _SAMPLE_GBP_EUR_CSV)
            return _mock_response(404, "unknown series")

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.side_effect = fake_get
            mock_httpx.HTTPError = Exception

            records = s.scrape_all()

        # 2 dates × 4 fx columns each
        assert len(records) == 2
        records_by_date = {r.date: r for r in records}
        r1 = records_by_date[date(2024, 1, 2)]
        # DXY = 1/1.10
        assert r1.fx_dxy_proxy == pytest.approx(1.0 / 1.10, rel=1e-6)
        # GBPUSD = 1.10/0.86
        assert r1.fx_gbpusd == pytest.approx(1.10 / 0.86, rel=1e-6)

    def test_http_non_200_fails_loud(self):
        from scripts.fx_scraper import scraper as s

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.return_value = _mock_response(503, "Service Unavailable")
            mock_httpx.HTTPError = Exception

            with pytest.raises(s.FxScraperError, match="HTTP 503"):
                s.scrape_all()

    def test_empty_body_fails_loud(self):
        from scripts.fx_scraper import scraper as s

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.return_value = _mock_response(200, "")
            mock_httpx.HTTPError = Exception

            with pytest.raises(s.FxScraperError, match="Empty body"):
                s.scrape_all()

    def test_network_error_fails_loud(self):
        import httpx as real_httpx

        from scripts.fx_scraper import scraper as s

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.side_effect = real_httpx.ConnectError("connection refused")
            mock_httpx.HTTPError = real_httpx.HTTPError

            with pytest.raises(s.FxScraperError, match="Network error"):
                s.scrape_all()

    def test_empty_parse_result_fails_loud(self):
        from scripts.fx_scraper import scraper as s

        only_header = "KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.return_value = _mock_response(200, only_header)
            mock_httpx.HTTPError = Exception

            with pytest.raises(s.FxScraperError, match="no parseable rows"):
                s.scrape_all()


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestCli:
    def test_default_args(self):
        with patch.object(sys, "argv", ["fx-scraper"]):
            args = _parse_args()
        assert args.dry_run is False
        assert args.force is False
        assert args.verbose is False

    def test_dry_run_flag(self):
        with patch.object(sys, "argv", ["fx-scraper", "--dry-run"]):
            args = _parse_args()
        assert args.dry_run is True

    def test_force_flag(self):
        with patch.object(sys, "argv", ["fx-scraper", "--force"]):
            args = _parse_args()
        assert args.force is True


# ---------------------------------------------------------------------------
# Main orchestration tests
# ---------------------------------------------------------------------------


class TestMainOrchestration:
    def test_dry_run_skips_db_write(self):
        from scripts.fx_scraper import main as m

        sample = [
            FxRecord(
                date=date(2024, 1, 2),
                fx_dxy_proxy=0.91,
                fx_gbpusd=1.27,
                fx_eurusd=0.91,
                fx_gbpeur=0.86,
            ),
        ]
        with (
            patch.object(sys, "argv", ["fx-scraper", "--dry-run"]),
            patch(
                "scripts.db.should_skip_non_trading_day",
                return_value=False,
            ),
            patch("scripts.fx_scraper.scraper.scrape_all", return_value=sample),
            patch("scripts.fx_scraper.db_writer.upsert_fx_rows") as mock_upsert,
        ):
            rc = m.main()
        assert rc == 0
        mock_upsert.assert_not_called()

    def test_live_run_calls_upsert_and_commits(self):
        from scripts.fx_scraper import main as m

        sample = [
            FxRecord(
                date=date(2024, 1, 2),
                fx_dxy_proxy=0.91,
                fx_gbpusd=1.27,
                fx_eurusd=0.91,
                fx_gbpeur=0.86,
            ),
        ]

        class _FakeSession:
            def __init__(self) -> None:
                self.committed = False

            def commit(self) -> None:
                self.committed = True

            def __enter__(self):
                return self

            def __exit__(self, *a, **kw):
                return False

        fake_session = _FakeSession()
        with (
            patch.object(sys, "argv", ["fx-scraper"]),
            patch("scripts.fx_scraper.scraper.scrape_all", return_value=sample),
            patch(
                "scripts.fx_scraper.db_writer.upsert_fx_rows", return_value=1
            ) as mock_upsert,
            patch("scripts.db.get_session", return_value=fake_session),
            patch(
                "scripts.db.should_skip_non_trading_day",
                return_value=False,
            ),
        ):
            rc = m.main()

        assert rc == 0
        mock_upsert.assert_called_once()
        assert fake_session.committed is True

    def test_exception_returns_non_zero(self):
        from scripts.fx_scraper import main as m

        with (
            patch.object(sys, "argv", ["fx-scraper", "--force"]),
            patch(
                "scripts.fx_scraper.scraper.scrape_all",
                side_effect=RuntimeError("boom"),
            ),
        ):
            rc = m.main()

        assert rc == 1


# ---------------------------------------------------------------------------
# Model sanity (table accepts an FX-only row via ORM)
# ---------------------------------------------------------------------------


class TestPlExternalIndicatorFxColumns:
    def test_fx_only_row_round_trips(self, sync_db_session):
        row = PlExternalIndicator(
            date=date(2024, 5, 2),
            fx_dxy_proxy=Decimal("0.91"),
            fx_gbpusd=Decimal("1.27"),
            fx_eurusd=Decimal("0.91"),
            fx_gbpeur=Decimal("0.86"),
        )
        sync_db_session.add(row)
        sync_db_session.flush()

        fetched = sync_db_session.execute(
            text(
                "SELECT fx_dxy_proxy, fx_gbpusd, fx_eurusd, fx_gbpeur "
                "FROM pl_external_indicator WHERE date = :d"
            ),
            {"d": date(2024, 5, 2)},
        ).fetchone()
        assert fetched.fx_dxy_proxy == Decimal("0.910000")
        assert fetched.fx_gbpusd == Decimal("1.270000")

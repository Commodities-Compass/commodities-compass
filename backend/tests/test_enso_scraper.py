"""Tests for cc-enso-scraper (NOAA PSL ENSO ingestion).

Covers:
  * PSL ASCII parser (header skip, missing-value flag detection, edge cases)
  * DB writer (UPSERT idempotency, partial column update doesn't touch FX)
  * Fail-loud on missing/malformed source
  * CLI flags (--dry-run, --force, --start-month)

See:
  * docs/user-stories/P1-scraper-enso.md
  * docs/onboarding/ingest_enso.py (R&D source code being ported)
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.models.pipeline import PlExternalIndicator
from scripts.enso_scraper.db_writer import upsert_enso_rows
from scripts.enso_scraper.main import _parse_args
from scripts.enso_scraper.parser import (
    EnsoParseError,
    EnsoRecord,
    parse_psl_text,
)


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParsePslText:
    """PSL ASCII text format (https://psl.noaa.gov/data/correlation/oni.data).

    Format:
        Header line with year range (skipped).
        Then rows: year jan feb mar ... dec (13 tokens, floats).
        Then trailing rows: missing-value flag(s) + metadata (parser stops on
        first non-numeric year token).
    """

    NOMINAL_PSL = "\n".join(
        [
            "   1950 2024",
            "1950   1.0   1.1   1.2  -0.5  -0.6  -0.7  -0.8  -0.9  -1.0  -1.1  -1.2  -1.3",
            "1951   2.0   2.1   2.2   2.3   2.4   2.5   2.6   2.7   2.8   2.9   3.0   3.1",
            "  -99.9",
            "Source: NOAA PSL",
        ]
    )

    def test_parses_nominal_two_years(self):
        records = parse_psl_text(self.NOMINAL_PSL, value_name="oni")
        # 2 years × 12 months = 24 records expected
        assert len(records) == 24
        # First record = 1950-01
        assert records[0].date == date(1950, 1, 1)
        assert records[0].value == 1.0
        # Last record = 1951-12
        assert records[-1].date == date(1951, 12, 1)
        assert records[-1].value == 3.1
        # Date monotonic ascending
        for i in range(1, len(records)):
            assert records[i].date > records[i - 1].date

    def test_missing_value_flag_dropped(self):
        """Rows where value == missing flag (-99.9) are filtered out."""
        psl_with_missing = "\n".join(
            [
                "   2024 2024",
                "2024   1.0   1.1   1.2 -99.9 -99.9 -99.9 -99.9 -99.9 -99.9 -99.9 -99.9 -99.9",
                "  -99.9",
            ]
        )
        records = parse_psl_text(psl_with_missing, value_name="oni")
        # Only the 3 non-missing months remain
        assert len(records) == 3
        assert records[0].date == date(2024, 1, 1)
        assert records[2].date == date(2024, 3, 1)

    def test_trailing_metadata_ignored(self):
        """Parser stops at the first non-numeric year token (metadata)."""
        psl = "\n".join(
            [
                "   1950 1950",
                "1950   1.0   1.0   1.0   1.0   1.0   1.0   1.0   1.0   1.0   1.0   1.0   1.0",
                "  -99.9",
                "Climate Prediction Center: oni",
                "https://psl.noaa.gov",
            ]
        )
        records = parse_psl_text(psl, value_name="oni")
        assert len(records) == 12

    def test_empty_input_returns_empty(self):
        records = parse_psl_text("", value_name="oni")
        assert records == []

    def test_value_name_is_carried_to_record(self):
        records = parse_psl_text(self.NOMINAL_PSL, value_name="nino34_anomaly")
        assert all(r.value_name == "nino34_anomaly" for r in records)

    def test_invalid_year_bounds_stop_parsing(self):
        """Years outside [1900, 2100] are treated as non-data → parser stops."""
        psl = "\n".join(
            [
                "   1950 1950",
                "1950   1.0   1.0   1.0   1.0   1.0   1.0   1.0   1.0   1.0   1.0   1.0   1.0",
                "9999   2.0   2.0   2.0   2.0   2.0   2.0   2.0   2.0   2.0   2.0   2.0   2.0",
            ]
        )
        records = parse_psl_text(psl, value_name="oni")
        # Only 1950 rows kept (12 months)
        assert len(records) == 12

    def test_malformed_row_raises_when_strict(self):
        """A row with fewer than 13 tokens (year + 12 months) but a valid year
        is considered malformed and skipped silently (matches R&D behavior).
        """
        psl = "\n".join(
            [
                "   1950 1950",
                "1950   1.0   1.1",  # only 3 tokens
                "1951   2.0   2.1   2.2   2.3   2.4   2.5   2.6   2.7   2.8   2.9   3.0   3.1",
            ]
        )
        records = parse_psl_text(psl, value_name="oni")
        # 1950 row skipped, 1951 row kept (12 months)
        assert len(records) == 12
        assert records[0].date == date(1951, 1, 1)

    def test_raises_on_non_text(self):
        """Defensive: non-string input fails loud (no silent str cast)."""
        with pytest.raises(EnsoParseError):
            parse_psl_text(None, value_name="oni")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# DB writer tests
# ---------------------------------------------------------------------------


class TestUpsertEnsoRows:
    """Verify UPSERT writes ENSO columns + leaves FX columns untouched.

    The hard rule (P1-scraper-enso.md §4.3): writing ENSO must NOT touch
    fx_dxy_proxy / fx_gbpusd / fx_eurusd / fx_gbpeur. The FX scraper writes
    those independently via partial UPSERT.
    """

    def test_inserts_new_rows(self, sync_db_session):
        records = [
            EnsoRecord(date=date(2024, 1, 1), value=0.5, value_name="oni"),
            EnsoRecord(date=date(2024, 2, 1), value=0.4, value_name="oni"),
        ]
        n = upsert_enso_rows(sync_db_session, records)
        assert n == 2

        row = sync_db_session.execute(
            text(
                "SELECT date, enso_oni_month, enso_nino34_anomaly, "
                "fx_dxy_proxy, fx_gbpusd FROM pl_external_indicator "
                "WHERE date = :d"
            ),
            {"d": date(2024, 1, 1)},
        ).fetchone()
        assert row.enso_oni_month == Decimal("0.5000")
        assert row.enso_nino34_anomaly is None
        # FX columns must remain untouched
        assert row.fx_dxy_proxy is None
        assert row.fx_gbpusd is None

    def test_upsert_is_idempotent(self, sync_db_session):
        records = [EnsoRecord(date=date(2024, 3, 1), value=0.3, value_name="oni")]
        upsert_enso_rows(sync_db_session, records)
        upsert_enso_rows(sync_db_session, records)  # second run

        count = sync_db_session.execute(
            text("SELECT count(*) FROM pl_external_indicator WHERE date = :d"),
            {"d": date(2024, 3, 1)},
        ).scalar()
        assert count == 1

    def test_upsert_updates_existing_enso(self, sync_db_session):
        """Re-running with a corrected value updates the row."""
        old = [EnsoRecord(date=date(2024, 4, 1), value=0.1, value_name="oni")]
        new = [EnsoRecord(date=date(2024, 4, 1), value=0.7, value_name="oni")]
        upsert_enso_rows(sync_db_session, old)
        upsert_enso_rows(sync_db_session, new)

        val = sync_db_session.execute(
            text("SELECT enso_oni_month FROM pl_external_indicator WHERE date = :d"),
            {"d": date(2024, 4, 1)},
        ).scalar()
        assert val == Decimal("0.7000")

    def test_upsert_preserves_fx_columns(self, sync_db_session):
        """Critical: ENSO scraper writes must NOT clobber FX values written by
        the FX scraper. Pre-seed an FX row, then write ENSO on same date,
        verify FX columns survive.
        """
        target = date(2024, 5, 1)
        # Pre-seed an FX-only row (simulates fx_scraper writing first)
        sync_db_session.execute(
            text(
                "INSERT INTO pl_external_indicator (date, fx_dxy_proxy, fx_gbpusd) "
                "VALUES (:d, :dxy, :gbp)"
            ),
            {"d": target, "dxy": Decimal("0.95"), "gbp": Decimal("1.27")},
        )
        sync_db_session.flush()

        # Now ENSO scraper writes for the same date
        upsert_enso_rows(
            sync_db_session,
            [EnsoRecord(date=target, value=0.42, value_name="oni")],
        )

        row = sync_db_session.execute(
            text(
                "SELECT enso_oni_month, fx_dxy_proxy, fx_gbpusd "
                "FROM pl_external_indicator WHERE date = :d"
            ),
            {"d": target},
        ).fetchone()
        # ENSO written
        assert row.enso_oni_month == Decimal("0.4200")
        # FX preserved (THE rule)
        assert row.fx_dxy_proxy == Decimal("0.950000")
        assert row.fx_gbpusd == Decimal("1.270000")

    def test_upsert_handles_both_value_names(self, sync_db_session):
        """Mixing ONI + Niño 3.4 records writes both columns on the same row."""
        target = date(2024, 6, 1)
        records = [
            EnsoRecord(date=target, value=0.8, value_name="oni"),
            EnsoRecord(date=target, value=0.9, value_name="nino34_anomaly"),
        ]
        upsert_enso_rows(sync_db_session, records)

        row = sync_db_session.execute(
            text(
                "SELECT enso_oni_month, enso_nino34_anomaly "
                "FROM pl_external_indicator WHERE date = :d"
            ),
            {"d": target},
        ).fetchone()
        assert row.enso_oni_month == Decimal("0.8000")
        assert row.enso_nino34_anomaly == Decimal("0.9000")

    def test_empty_records_is_noop(self, sync_db_session):
        n = upsert_enso_rows(sync_db_session, [])
        assert n == 0
        count = sync_db_session.execute(
            text("SELECT count(*) FROM pl_external_indicator")
        ).scalar()
        assert count == 0

    def test_unknown_value_name_fails_loud(self, sync_db_session):
        """A record with value_name not in {oni, nino34_anomaly} → raise.

        Aligned with .claude/rules/pipeline-error-handling.md.
        """
        with pytest.raises(ValueError, match="value_name"):
            upsert_enso_rows(
                sync_db_session,
                [EnsoRecord(date=date(2024, 7, 1), value=0.5, value_name="bogus")],
            )


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestCli:
    def test_default_args(self):
        with patch.object(sys, "argv", ["enso-scraper"]):
            args = _parse_args()
        assert args.dry_run is False
        assert args.verbose is False

    def test_dry_run_flag(self):
        with patch.object(sys, "argv", ["enso-scraper", "--dry-run"]):
            args = _parse_args()
        assert args.dry_run is True

    def test_force_flag_rejected(self):
        """--force was removed (LOW-2 fix): ENSO is monthly, no trading-day skip."""
        with (
            patch.object(sys, "argv", ["enso-scraper", "--force"]),
            pytest.raises(SystemExit),
        ):
            _parse_args()

    def test_combine_flags(self):
        with patch.object(sys, "argv", ["enso-scraper", "--dry-run", "--verbose"]):
            args = _parse_args()
        assert args.dry_run is True
        assert args.verbose is True


# ---------------------------------------------------------------------------
# Model sanity (no scraper code, just to confirm the migration + model match)
# ---------------------------------------------------------------------------


class TestPlExternalIndicatorModel:
    def test_model_columns_match_schema(self, sync_db_session):
        """Smoke: inserting a row via ORM persists and round-trips."""
        row = PlExternalIndicator(
            date=date(2024, 8, 1),
            enso_oni_month=Decimal("0.2"),
            enso_nino34_anomaly=Decimal("0.3"),
            fx_dxy_proxy=Decimal("0.91"),
            fx_gbpusd=Decimal("1.26"),
        )
        sync_db_session.add(row)
        sync_db_session.flush()

        fetched = sync_db_session.execute(
            text(
                "SELECT enso_oni_month, enso_nino34_anomaly, fx_dxy_proxy, fx_gbpusd "
                "FROM pl_external_indicator WHERE date = :d"
            ),
            {"d": date(2024, 8, 1)},
        ).fetchone()
        assert fetched.enso_oni_month == Decimal("0.2000")
        assert fetched.enso_nino34_anomaly == Decimal("0.3000")
        assert fetched.fx_dxy_proxy == Decimal("0.910000")
        assert fetched.fx_gbpusd == Decimal("1.260000")


# ---------------------------------------------------------------------------
# Scraper tests (HTTP mocks)
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, text_body: str):
    """Build a minimal httpx.Response-like object for mocking."""

    class _Resp:
        def __init__(self) -> None:
            self.status_code = status_code
            self.text = text_body

    return _Resp()


# Sample PSL ASCII matching NOAA's real format (one year only, enough to test
# the full path).
_SAMPLE_PSL = "\n".join(
    [
        "   2024 2024",
        "2024   1.0   1.1   1.2   1.3   1.4   1.5   1.6   1.7   1.8   1.9   2.0   2.1",
        "  -99.9",
        "Source: NOAA PSL",
    ]
)


class TestScraperHttp:
    """Verify HTTP fetch + parse pipeline with httpx mocks."""

    def test_scrape_oni_happy_path(self):
        from scripts.enso_scraper import scraper as s

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.return_value = _mock_response(200, _SAMPLE_PSL)
            # Re-export HTTPError so the except clause finds it on the mock.
            mock_httpx.HTTPError = Exception

            records = s.scrape_oni()

        assert len(records) == 12
        assert records[0].date == date(2024, 1, 1)
        assert records[0].value_name == "oni"

    def test_scrape_nino34_happy_path(self):
        from scripts.enso_scraper import scraper as s

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.return_value = _mock_response(200, _SAMPLE_PSL)
            mock_httpx.HTTPError = Exception

            records = s.scrape_nino34()

        assert len(records) == 12
        assert records[0].value_name == "nino34_anomaly"

    def test_scrape_all_combines_oni_and_nino34(self):
        from scripts.enso_scraper import scraper as s

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.return_value = _mock_response(200, _SAMPLE_PSL)
            mock_httpx.HTTPError = Exception

            records = s.scrape_all()

        assert len(records) == 24  # 12 ONI + 12 Niño 3.4
        names = {r.value_name for r in records}
        assert names == {"oni", "nino34_anomaly"}

    def test_http_non_200_fails_loud(self):
        from scripts.enso_scraper import scraper as s

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.return_value = _mock_response(503, "Service Unavailable")
            mock_httpx.HTTPError = Exception

            with pytest.raises(s.EnsoScraperError, match="HTTP 503"):
                s.scrape_oni()

    def test_empty_body_fails_loud(self):
        from scripts.enso_scraper import scraper as s

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.return_value = _mock_response(200, "")
            mock_httpx.HTTPError = Exception

            with pytest.raises(s.EnsoScraperError, match="Empty body"):
                s.scrape_oni()

    def test_network_error_fails_loud(self):
        import httpx as real_httpx

        from scripts.enso_scraper import scraper as s

        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.side_effect = real_httpx.ConnectError("connection refused")
            mock_httpx.HTTPError = real_httpx.HTTPError

            with pytest.raises(s.EnsoScraperError, match="Network error"):
                s.scrape_oni()

    def test_parseable_but_empty_result_fails_loud(self):
        """A 200 response with text that yields zero records → fail-loud.

        Aligned with the rule that the scraper should never silently produce
        an empty write (it'd mask a NOAA format change).
        """
        from scripts.enso_scraper import scraper as s

        only_header = "   1950 1950\n  -99.9\nMetadata only\n"
        with patch.object(s, "httpx") as mock_httpx:
            mock_httpx.get.return_value = _mock_response(200, only_header)
            mock_httpx.HTTPError = Exception

            with pytest.raises(s.EnsoScraperError, match="no parseable rows"):
                s.scrape_oni()


# ---------------------------------------------------------------------------
# Main orchestration tests
# ---------------------------------------------------------------------------


class TestMainOrchestration:
    """Smoke-test main() with all I/O mocked.

    Verifies:
      * Dry-run skips the DB write entirely.
      * Live mode wires fetch → upsert → commit.
      * Any uncaught exception in the pipeline returns 1 (fail-loud).
    """

    def test_dry_run_skips_db_write(self):
        from scripts.enso_scraper import main as m

        sample_records = [
            EnsoRecord(date=date(2024, 1, 1), value=0.5, value_name="oni"),
        ]
        with (
            patch.object(sys, "argv", ["enso-scraper", "--dry-run"]),
            patch(
                "scripts.enso_scraper.scraper.scrape_all", return_value=sample_records
            ),
            patch("scripts.enso_scraper.db_writer.upsert_enso_rows") as mock_upsert,
        ):
            rc = m.main()
        assert rc == 0
        mock_upsert.assert_not_called()

    def test_live_run_calls_upsert_and_commits(self):
        from scripts.enso_scraper import main as m

        sample_records = [
            EnsoRecord(date=date(2024, 1, 1), value=0.5, value_name="oni"),
            EnsoRecord(date=date(2024, 1, 1), value=0.6, value_name="nino34_anomaly"),
        ]

        # Fake session that records commit() calls
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
            patch.object(sys, "argv", ["enso-scraper"]),
            patch(
                "scripts.enso_scraper.scraper.scrape_all", return_value=sample_records
            ),
            patch(
                "scripts.enso_scraper.db_writer.upsert_enso_rows", return_value=2
            ) as mock_upsert,
            patch("scripts.db.get_session", return_value=fake_session),
        ):
            rc = m.main()

        assert rc == 0
        mock_upsert.assert_called_once()
        # commit() was called inside the with-block
        assert fake_session.committed is True

    def test_exception_returns_non_zero(self):
        from scripts.enso_scraper import main as m

        with (
            patch.object(sys, "argv", ["enso-scraper"]),
            patch(
                "scripts.enso_scraper.scraper.scrape_all",
                side_effect=RuntimeError("boom"),
            ),
        ):
            rc = m.main()

        assert rc == 1

"""Tests for one-shot backfill scripts (ENSO + FX from R&D CSV snapshots).

Both scripts:
  * Load CSV from docs/onboarding/{ENSO,FX}/*.csv
  * Filter rows in [start, end] + drop -99.99 sentinels (ENSO)
  * UPSERT via existing db_writers (upsert_enso_rows / upsert_fx_rows)
  * Optional --verify: re-query DB and assert value-by-value match

See:
  * docs/user-stories/P1-scraper-enso.md §6.3 (backfill au launch)
  * docs/user-stories/P1-scraper-fx.md §6.3 (backfill au launch)
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import text

from scripts.enso_scraper.backfill import (
    BackfillVerificationError as EnsoBackfillVerificationError,
)
from scripts.enso_scraper.backfill import (
    _parse_args as _enso_parse_args,
)
from scripts.enso_scraper.backfill import (
    load_enso_csv,
    verify_enso_against_csv,
)
from scripts.enso_scraper.backfill import main as enso_backfill_main
from scripts.fx_scraper.backfill import (
    BackfillVerificationError as FxBackfillVerificationError,
)
from scripts.fx_scraper.backfill import (
    _parse_args as _fx_parse_args,
)
from scripts.fx_scraper.backfill import (
    load_fx_csvs,
    verify_fx_against_csvs,
)
from scripts.fx_scraper.backfill import main as fx_backfill_main


# ---------------------------------------------------------------------------
# ENSO backfill
# ---------------------------------------------------------------------------


@pytest.fixture()
def enso_oni_csv(tmp_path: Path) -> Path:
    p = tmp_path / "oni_monthly.csv"
    p.write_text(
        "date,oni\n1950-01-01,-1.53\n1950-02-01,-1.34\n2024-01-01,0.5\n2024-02-01,0.4\n"
    )
    return p


@pytest.fixture()
def enso_nino34_csv(tmp_path: Path) -> Path:
    p = tmp_path / "nino34_monthly.csv"
    p.write_text(
        "date,nino34_anomaly\n"
        "1948-01-01,-99.99\n"  # PSL missing-value sentinel — must be skipped
        "1950-01-01,-1.2\n"
        "2024-01-01,0.6\n"
        "2024-02-01,0.7\n"
    )
    return p


class TestLoadEnsoCsv:
    def test_loads_oni(self, enso_oni_csv: Path):
        records = load_enso_csv(enso_oni_csv, value_name="oni")
        assert len(records) == 4
        assert records[0].date == date(1950, 1, 1)
        assert records[0].value_name == "oni"
        assert records[-1].date == date(2024, 2, 1)

    def test_loads_nino34_and_filters_sentinel(self, enso_nino34_csv: Path):
        records = load_enso_csv(enso_nino34_csv, value_name="nino34_anomaly")
        # -99.99 row dropped
        assert len(records) == 3
        dates = [r.date for r in records]
        assert date(1948, 1, 1) not in dates

    def test_date_range_filter(self, enso_oni_csv: Path):
        records = load_enso_csv(
            enso_oni_csv,
            value_name="oni",
            start=date(2024, 1, 1),
            end=date(2024, 12, 31),
        )
        assert len(records) == 2
        assert all(r.date.year == 2024 for r in records)

    def test_missing_file_fails_loud(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_enso_csv(tmp_path / "does-not-exist.csv", value_name="oni")

    def test_invalid_value_name_fails_loud(self, enso_oni_csv: Path):
        with pytest.raises(ValueError, match="value_name"):
            load_enso_csv(enso_oni_csv, value_name="bogus")

    def test_skips_invalid_rows(self, tmp_path: Path):
        p = tmp_path / "noisy.csv"
        p.write_text(
            "date,oni\n"
            "1950-01-01,-1.53\n"
            "not-a-date,1.0\n"  # bad date
            "1950-02-01,not-a-number\n"  # bad value
            "1950-03-01,0.0\n"
        )
        records = load_enso_csv(p, value_name="oni")
        assert len(records) == 2  # 2 valid rows


class TestVerifyEnsoAgainstCsv:
    def test_match_passes(
        self, sync_db_session, enso_oni_csv: Path, enso_nino34_csv: Path
    ):
        from scripts.enso_scraper.db_writer import upsert_enso_rows

        records = load_enso_csv(enso_oni_csv, value_name="oni") + load_enso_csv(
            enso_nino34_csv, value_name="nino34_anomaly"
        )
        upsert_enso_rows(sync_db_session, records)

        # Should pass — values match exactly
        verify_enso_against_csv(sync_db_session, enso_oni_csv, enso_nino34_csv)

    def test_mismatch_raises(
        self, sync_db_session, enso_oni_csv: Path, enso_nino34_csv: Path
    ):
        from scripts.enso_scraper.db_writer import upsert_enso_rows

        records = load_enso_csv(enso_oni_csv, value_name="oni")
        upsert_enso_rows(sync_db_session, records)

        # Corrupt one row in DB
        sync_db_session.execute(
            text(
                "UPDATE pl_external_indicator SET enso_oni_month = :v WHERE date = :d"
            ),
            {"v": Decimal("99.99"), "d": date(2024, 1, 1)},
        )
        sync_db_session.flush()

        with pytest.raises(EnsoBackfillVerificationError, match="mismatch"):
            verify_enso_against_csv(sync_db_session, enso_oni_csv, enso_nino34_csv)


class TestEnsoBackfillCli:
    def test_parse_defaults(self):
        with patch.object(sys, "argv", ["enso-scraper-backfill"]):
            args = _enso_parse_args()
        assert args.dry_run is False
        assert args.verify is False
        # Defaults point at the snapshot dir
        assert "docs/onboarding/ENSO" in str(args.source_csv_oni)

    def test_parse_dry_run_and_verify(self):
        with patch.object(
            sys,
            "argv",
            ["enso-scraper-backfill", "--dry-run", "--verify"],
        ):
            args = _enso_parse_args()
        assert args.dry_run is True
        assert args.verify is True


class TestEnsoBackfillMain:
    def test_dry_run_skips_upsert(
        self, sync_db_session, enso_oni_csv: Path, enso_nino34_csv: Path
    ):
        with (
            patch.object(
                sys,
                "argv",
                [
                    "enso-scraper-backfill",
                    "--source-csv-oni",
                    str(enso_oni_csv),
                    "--source-csv-nin34",
                    str(enso_nino34_csv),
                    "--dry-run",
                ],
            ),
            patch("scripts.enso_scraper.backfill.upsert_enso_rows") as mock_upsert,
            patch("scripts.db.get_session", return_value=_fake_session()),
        ):
            rc = enso_backfill_main()
        assert rc == 0
        mock_upsert.assert_not_called()

    def test_live_run_calls_upsert(self, enso_oni_csv: Path, enso_nino34_csv: Path):
        fake = _fake_session()
        with (
            patch.object(
                sys,
                "argv",
                [
                    "enso-scraper-backfill",
                    "--source-csv-oni",
                    str(enso_oni_csv),
                    "--source-csv-nin34",
                    str(enso_nino34_csv),
                ],
            ),
            patch(
                "scripts.enso_scraper.backfill.upsert_enso_rows",
                return_value=7,
            ) as mock_upsert,
            patch("scripts.db.get_session", return_value=fake),
        ):
            rc = enso_backfill_main()
        assert rc == 0
        mock_upsert.assert_called_once()
        assert fake.committed is True


# ---------------------------------------------------------------------------
# FX backfill
# ---------------------------------------------------------------------------


@pytest.fixture()
def fx_dxy_csv(tmp_path: Path) -> Path:
    p = tmp_path / "dxy_proxy_daily.csv"
    p.write_text("date,close\n2014-01-02,0.7321\n2014-01-03,0.7334\n2024-05-15,0.92\n")
    return p


@pytest.fixture()
def fx_gbpusd_csv(tmp_path: Path) -> Path:
    p = tmp_path / "gbpusd_daily.csv"
    p.write_text("date,close\n2014-01-02,1.6491\n2014-01-03,1.6417\n2024-05-15,1.27\n")
    return p


class TestLoadFxCsvs:
    def test_joins_on_date(self, fx_dxy_csv: Path, fx_gbpusd_csv: Path):
        records = load_fx_csvs(fx_dxy_csv, fx_gbpusd_csv)
        assert len(records) == 3
        # First record has both dxy and gbpusd
        first = records[0]
        assert first.date == date(2014, 1, 2)
        assert first.fx_dxy_proxy == 0.7321
        assert first.fx_gbpusd == 1.6491
        # fx_eurusd is the dxy_proxy alias
        assert first.fx_eurusd == 0.7321
        # fx_gbpeur not stored in the CSV pair — left None on backfill
        assert first.fx_gbpeur is None

    def test_date_only_in_dxy_keeps_partial(self, tmp_path: Path):
        dxy = tmp_path / "dxy.csv"
        dxy.write_text("date,close\n2024-01-02,0.91\n2024-01-03,0.92\n")
        gbpusd = tmp_path / "gbpusd.csv"
        gbpusd.write_text("date,close\n2024-01-03,1.27\n")
        records = load_fx_csvs(dxy, gbpusd)
        by_date = {r.date: r for r in records}
        assert by_date[date(2024, 1, 2)].fx_gbpusd is None
        assert by_date[date(2024, 1, 3)].fx_gbpusd == 1.27

    def test_date_range_filter(self, fx_dxy_csv: Path, fx_gbpusd_csv: Path):
        records = load_fx_csvs(
            fx_dxy_csv,
            fx_gbpusd_csv,
            start=date(2024, 1, 1),
            end=date(2024, 12, 31),
        )
        assert len(records) == 1
        assert records[0].date == date(2024, 5, 15)

    def test_missing_file_fails_loud(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_fx_csvs(tmp_path / "nope_dxy.csv", tmp_path / "nope_gbp.csv")


class TestVerifyFxAgainstCsvs:
    def test_match_passes(self, sync_db_session, fx_dxy_csv: Path, fx_gbpusd_csv: Path):
        from scripts.fx_scraper.db_writer import upsert_fx_rows

        records = load_fx_csvs(fx_dxy_csv, fx_gbpusd_csv)
        upsert_fx_rows(sync_db_session, records)

        verify_fx_against_csvs(sync_db_session, fx_dxy_csv, fx_gbpusd_csv)

    def test_mismatch_raises(
        self, sync_db_session, fx_dxy_csv: Path, fx_gbpusd_csv: Path
    ):
        from scripts.fx_scraper.db_writer import upsert_fx_rows

        records = load_fx_csvs(fx_dxy_csv, fx_gbpusd_csv)
        upsert_fx_rows(sync_db_session, records)

        sync_db_session.execute(
            text("UPDATE pl_external_indicator SET fx_dxy_proxy = :v WHERE date = :d"),
            {"v": Decimal("0.0"), "d": date(2014, 1, 2)},
        )
        sync_db_session.flush()

        with pytest.raises(FxBackfillVerificationError, match="mismatch"):
            verify_fx_against_csvs(sync_db_session, fx_dxy_csv, fx_gbpusd_csv)


class TestFxBackfillCli:
    def test_parse_defaults(self):
        with patch.object(sys, "argv", ["fx-scraper-backfill"]):
            args = _fx_parse_args()
        assert args.dry_run is False
        assert args.verify is False
        assert "docs/onboarding/FX" in str(args.source_csv_dxy)

    def test_parse_flags(self):
        with patch.object(
            sys, "argv", ["fx-scraper-backfill", "--dry-run", "--verify"]
        ):
            args = _fx_parse_args()
        assert args.dry_run is True
        assert args.verify is True


class TestFxBackfillMain:
    def test_dry_run_skips_upsert(self, fx_dxy_csv: Path, fx_gbpusd_csv: Path):
        with (
            patch.object(
                sys,
                "argv",
                [
                    "fx-scraper-backfill",
                    "--source-csv-dxy",
                    str(fx_dxy_csv),
                    "--source-csv-gbpusd",
                    str(fx_gbpusd_csv),
                    "--dry-run",
                ],
            ),
            patch("scripts.fx_scraper.backfill.upsert_fx_rows") as mock_upsert,
            patch("scripts.db.get_session", return_value=_fake_session()),
        ):
            rc = fx_backfill_main()
        assert rc == 0
        mock_upsert.assert_not_called()

    def test_live_run_calls_upsert(self, fx_dxy_csv: Path, fx_gbpusd_csv: Path):
        fake = _fake_session()
        with (
            patch.object(
                sys,
                "argv",
                [
                    "fx-scraper-backfill",
                    "--source-csv-dxy",
                    str(fx_dxy_csv),
                    "--source-csv-gbpusd",
                    str(fx_gbpusd_csv),
                ],
            ),
            patch(
                "scripts.fx_scraper.backfill.upsert_fx_rows",
                return_value=3,
            ) as mock_upsert,
            patch("scripts.db.get_session", return_value=fake),
        ):
            rc = fx_backfill_main()
        assert rc == 0
        mock_upsert.assert_called_once()
        assert fake.committed is True


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _fake_session():
    class _S:
        def __init__(self) -> None:
            self.committed = False

        def commit(self) -> None:
            self.committed = True

        def __enter__(self):
            return self

        def __exit__(self, *a, **kw):
            return False

    return _S()

"""Unit tests for the seasonal backtest module.

Pure unit tests — no DB, no network. The Open-Meteo fetchers are monkey-patched
in `test_run_backtest_orchestration`. Real HTTP calls live in the production
meteo_agent code path and are already covered there.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from scripts.meteo_agent.config import LOCATIONS, SEASONAL_PROFILES
from scripts.meteo_agent.seasonal_memory import LocationSeasonStats, SeasonDateRange
from scripts.seasonal_backtest.exporter import (
    DAILY_CSV_COLUMNS,
    SUMMARY_CSV_COLUMNS,
    export_all,
)
from scripts.seasonal_backtest.report import build_report, classify_diagnostic
from scripts.seasonal_backtest.types import (
    CampaignBacktest,
    LocationBacktest,
    LocationDailyRow,
    SeasonBacktest,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_SAISON_SECHE = next(p for p in SEASONAL_PROFILES if p.name == "saison_seche")
_GRANDE_PLUIES = next(p for p in SEASONAL_PROFILES if p.name == "grande_saison_pluies")


def _make_daily_rows(
    n: int, with_harmattan: bool = False
) -> tuple[LocationDailyRow, ...]:
    rows = []
    for i in range(n):
        rows.append(
            LocationDailyRow(
                date=f"2024-12-{i + 1:02d}",
                precip_mm=1.0 + i,
                et0_mm=4.0,
                tmax_c=33.0 + (i % 3),
                tmin_c=22.0,
                sunshine_s=28800.0,
                wind_dir_dominant_deg=350.0,
                min_rh_pct=40.0 if with_harmattan else None,
                harmattan_flag=True if with_harmattan else None,
            )
        )
    return tuple(rows)


def _make_location(
    name: str,
    country: str,
    score: float,
    *,
    with_harmattan: bool = False,
    n_days: int = 5,
) -> LocationBacktest:
    stats = LocationSeasonStats(
        location_name=name,
        country=country,
        total_precip_mm=20.0,
        total_et0_mm=20.0,
        cumulative_balance_mm=0.0,
        days_rain=3,
        days_stress_temp=2,
        avg_tmax=33.5,
        total_days=n_days,
    )
    diagnostic = "normal" if score >= 3.5 else "degraded" if score >= 2.5 else "stress"
    return LocationBacktest(
        location_name=name,
        country=country,
        stats=stats,
        score=score,
        harmattan_days=12 if with_harmattan else None,
        daily_rows=_make_daily_rows(n_days, with_harmattan=with_harmattan),
        expected_days=n_days,
        diagnostic=diagnostic,
    )


def _make_season_backtest(
    profile, start: date, end: date, scores: tuple[float, ...]
) -> SeasonBacktest:
    is_dry = profile.name == "saison_seche"
    season_range = SeasonDateRange(
        season=profile,
        campaign="2024-2025",
        start_date=start,
        end_date=end,
        months_covered=f"{start.strftime('%b')}-{end.strftime('%b')} {start.year}",
    )
    locs = tuple(
        _make_location(loc.name, loc.country, scores[i], with_harmattan=is_dry)
        for i, loc in enumerate(LOCATIONS[: len(scores)])
    )
    return SeasonBacktest(season_range=season_range, locations=locs)


def _make_campaign_backtest() -> CampaignBacktest:
    seasons = (
        _make_season_backtest(
            _SAISON_SECHE,
            date(2024, 12, 1),
            date(2025, 3, 31),
            (1.5, 2.0, 2.5, 1.0, 1.5, 2.0),
        ),
        _make_season_backtest(
            _GRANDE_PLUIES,
            date(2025, 5, 1),
            date(2025, 7, 31),
            (3.0, 3.5, 4.0, 2.5, 3.0, 3.5),
        ),
    )
    return CampaignBacktest(
        campaign="2024-2025",
        target_date="2025-09-30",
        seasons=seasons,
    )


# ---------------------------------------------------------------------------
# report.classify_diagnostic — threshold boundaries
# ---------------------------------------------------------------------------


def test_classify_diagnostic_thresholds():
    assert classify_diagnostic(4.5) == "normal"
    assert classify_diagnostic(3.5) == "normal"
    assert classify_diagnostic(3.0) == "degraded"
    assert classify_diagnostic(2.5) == "degraded"
    assert classify_diagnostic(2.4) == "stress"
    assert classify_diagnostic(1.0) == "stress"


# ---------------------------------------------------------------------------
# exporter — CSV shapes
# ---------------------------------------------------------------------------


def test_export_summary_csv_shape(tmp_path: Path):
    backtest = _make_campaign_backtest()
    summary_path, raw_paths = export_all(backtest, tmp_path)

    # Summary: 1 header + 2 seasons × 6 locations = 13 lines
    lines = summary_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1 + 2 * 6
    assert lines[0] == ",".join(SUMMARY_CSV_COLUMNS)
    # First data row points at campaign "2024-2025"
    assert lines[1].startswith("2024-2025,saison_seche,Daloa,")

    # Raw: 2 seasons × 6 locations = 12 files
    assert len(raw_paths) == 12
    # Each raw file: header + 5 day rows
    for p in raw_paths:
        rows = p.read_text(encoding="utf-8").strip().splitlines()
        assert rows[0] == ",".join(DAILY_CSV_COLUMNS)
        assert len(rows) == 1 + 5


def test_export_daily_csv_omits_harmattan_for_non_dry_season(tmp_path: Path):
    """Non-dry seasons leave min_rh_pct + harmattan_flag empty."""
    backtest = _make_campaign_backtest()
    export_all(backtest, tmp_path)

    raw_dir = tmp_path / "raw"
    grande_csv = next(raw_dir.glob("grande_saison_pluies_*.csv"))
    rows = grande_csv.read_text(encoding="utf-8").strip().splitlines()
    # Verify the last two columns (min_rh_pct, harmattan_flag) are empty on a data row
    last_data = rows[-1].split(",")
    assert last_data[-2] == ""  # min_rh_pct
    assert last_data[-1] == ""  # harmattan_flag

    saison_csv = next(raw_dir.glob("saison_seche_*.csv"))
    saison_rows = saison_csv.read_text(encoding="utf-8").strip().splitlines()
    last_dry_data = saison_rows[-1].split(",")
    assert last_dry_data[-2] != ""  # min_rh_pct populated
    assert last_dry_data[-1] in {"0", "1"}  # harmattan_flag populated


# ---------------------------------------------------------------------------
# report — Markdown
# ---------------------------------------------------------------------------


def test_build_report_renders_all_sections(tmp_path: Path):
    backtest = _make_campaign_backtest()
    report_path = build_report(backtest, tmp_path)

    text = report_path.read_text(encoding="utf-8")
    # TL;DR present
    assert "## TL;DR" in text
    assert "Health label" in text
    assert "Overall average" in text
    assert "Per-season averages" in text
    # Methodology present
    assert "## Methodology" in text
    assert "Open-Meteo Archive API" in text
    # All 6 locations in methodology block
    for loc in LOCATIONS:
        assert loc.name in text
    # Both seasons rendered
    assert "Saison Seche" in text
    assert "Grande Saison Pluies" in text
    # Cross-check + integrity sections
    assert "## Cross-check guide" in text
    assert "## Pipeline integrity" in text
    # Saison sèche table includes Harmattan column
    assert "Harmattan d" in text


def test_build_report_tldr_picks_worst_and_best(tmp_path: Path):
    backtest = _make_campaign_backtest()
    # Worst = score 1.0 (Kumasi, saison_seche), best = score 4.0 (Soubré, grande_saison_pluies)
    path = build_report(backtest, tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "Worst" in text and "Kumasi" in text and "1.0/5" in text
    assert "Best" in text and "Soubré" in text and "4.0/5" in text


# ---------------------------------------------------------------------------
# main — orchestration with monkey-patched fetchers (no network)
# ---------------------------------------------------------------------------


def _fake_extended_weather(start_date: date, end_date: date) -> list[dict]:
    """Synthesize the Open-Meteo shape: one entry per location with daily arrays."""
    n_days = (end_date - start_date).days + 1
    out = []
    for _ in LOCATIONS:
        out.append(
            {
                "daily": {
                    "time": [
                        (start_date + timedelta(days=i)).isoformat()
                        for i in range(n_days)
                    ],
                    "precipitation_sum": [0.0] * n_days,
                    "et0_fao_evapotranspiration": [4.0] * n_days,
                    "temperature_2m_max": [34.0] * n_days,
                    "temperature_2m_min": [22.0] * n_days,
                    "sunshine_duration": [28800.0] * n_days,
                    "winddirection_10m_dominant": [350.0] * n_days,
                }
            }
        )
    return out


def _fake_harmattan(start_date: date, end_date: date) -> list[dict]:
    """Synthesize harmattan archive shape: daily wind + hourly RH."""
    n_days = (end_date - start_date).days + 1
    out = []
    for _ in LOCATIONS:
        out.append(
            {
                "daily": {
                    "time": [
                        (start_date + timedelta(days=i)).isoformat()
                        for i in range(n_days)
                    ],
                    "winddirection_10m_dominant": [350.0] * n_days,
                },
                "hourly": {
                    # 24 hours per day, RH stays low → harmattan flag should be True
                    "relative_humidity_2m": [40.0] * (n_days * 24),
                },
            }
        )
    return out


def test_run_backtest_end_to_end_with_fake_fetchers(tmp_path: Path, monkeypatch):
    """Smoke-tests the full orchestration without hitting the network."""
    from scripts.seasonal_backtest import main as backtest_main

    monkeypatch.setattr(
        backtest_main, "fetch_extended_season_weather", _fake_extended_weather
    )
    monkeypatch.setattr(backtest_main, "fetch_harmattan_weather", _fake_harmattan)

    args = argparse.Namespace(
        target_date=date(2025, 9, 30),
        output_dir=tmp_path,
        write_db=False,
        db="local",
        verbose=False,
    )
    backtest = backtest_main.run_backtest(args)

    assert backtest.campaign == "2024-2025"
    # All 5 seasons of the 2024-2025 campaign should be completed by 2025-09-30
    assert len(backtest.seasons) == 5
    # Each season produces 6 locations
    for season in backtest.seasons:
        assert len(season.locations) == 6
    # saison_seche backtest must carry harmattan counts
    saison_seche = next(
        s for s in backtest.seasons if s.season_range.season.name == "saison_seche"
    )
    for loc in saison_seche.locations:
        assert loc.harmattan_days is not None and loc.harmattan_days > 0


def test_main_with_fake_fetchers_writes_outputs(tmp_path: Path, monkeypatch):
    """End-to-end via main() — no DB, just confirm files land where expected."""
    from scripts.seasonal_backtest import main as backtest_main

    monkeypatch.setattr(
        backtest_main, "fetch_extended_season_weather", _fake_extended_weather
    )
    monkeypatch.setattr(backtest_main, "fetch_harmattan_weather", _fake_harmattan)

    exit_code = backtest_main.main(
        [
            "--target-date",
            "2025-09-30",
            "--output-dir",
            str(tmp_path),
        ]
    )
    assert exit_code == 0
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "summary_2024-2025.csv").exists()
    assert (tmp_path / "raw").is_dir()
    # 5 seasons × 6 locations = 30 raw CSVs
    raw_files = list((tmp_path / "raw").glob("*.csv"))
    assert len(raw_files) == 30

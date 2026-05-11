"""Markdown report builder for the seasonal backtest."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from scripts.meteo_agent.config import LOCATIONS
from scripts.meteo_agent.seasonal_memory import _PRECIP_30D_NORMS
from scripts.seasonal_backtest.types import CampaignBacktest, SeasonBacktest

logger = logging.getLogger(__name__)


def classify_diagnostic(score: float) -> str:
    """Match dashboard thresholds: >=3.5 normal, 2.5-3.4 degraded, <2.5 stress."""
    if score >= 3.5:
        return "normal"
    if score >= 2.5:
        return "degraded"
    return "stress"


def _format_score(score: float) -> str:
    return f"{score:.1f}/5"


def _format_signed(value: float) -> str:
    return f"{value:+.0f}"


def _campaign_health_line(avg: float) -> str:
    if avg >= 4.0:
        return "Réserves hydriques bien constituées. Stress ponctuel absorbable."
    if avg >= 3.0:
        return "Campagne correcte. Vigilance sur les localités les plus faibles."
    if avg >= 2.0:
        return "Campagne dégradée. Stress cumulé significatif, sensibilité élevée."
    return (
        "Campagne critique. Déficits cumulés importants, "
        "tout stress additionnel est amplifié."
    )


def _build_methodology() -> str:
    locations = "\n".join(
        f"- **{loc.name}** ({loc.country}) — lat {loc.latitude}, lon {loc.longitude}"
        for loc in LOCATIONS
    )
    norms = "\n".join(
        f"- `{name}`: {lo}-{hi} mm / 30 days"
        for name, (lo, hi) in _PRECIP_30D_NORMS.items()
    )
    return f"""## Methodology

**Source**: Open-Meteo Archive API (ERA5 reanalysis under the hood).
Endpoint: `https://archive-api.open-meteo.com/v1/archive`
Daily fields fetched: `precipitation_sum`, `et0_fao_evapotranspiration`,
`temperature_2m_max`, `temperature_2m_min`, `sunshine_duration`,
`winddirection_10m_dominant`. For `saison_seche` a second call adds hourly
`relative_humidity_2m` for Harmattan detection.

**Locations** (6 — West Africa cocoa belt):
{locations}

**Scoring** (deterministic, code: `scripts.meteo_agent.seasonal_memory.compute_score`):
- Starts at 5.0, applies penalties:
  - **Precipitation deviation** (-2.0 / -1.0) vs season norm scaled to season length
  - **Heat stress ratio** = days above season threshold / total days (-0.5 → -2.0)
  - **Water balance** (precip − ET0) < -5 mm/day average: -0.5
- Clamped to [1.0, 5.0], rounded to 0.5.

**30-day precipitation norms** (currently hardcoded, marked "to be refined"):
{norms}

**Diagnostic thresholds** (match `dashboard_service` LocationDiagnostic):
- `normal`: score ≥ 3.5
- `degraded`: 2.5 ≤ score < 3.5
- `stress`: score < 2.5

**Caveats**:
- `_PRECIP_30D_NORMS` are not calibrated against multi-year climatology.
  A single-campaign backtest can validate **direction** (stress vs normal)
  but not absolute level precision.
- Archive API has a ~5-day publication lag — the fetcher caps `end_date` to
  `today − 5 days`; a single-day gap in the most recent season is expected
  near the publication boundary.
"""


def _build_season_table(season: SeasonBacktest) -> str:
    is_dry = season.season_range.season.name == "saison_seche"
    header = (
        "| Location | Country | Precip (mm) | ET0 (mm) | Balance | Days rain "
        "| Days stress | Avg Tmax | "
    )
    sep = "|---|---|---:|---:|---:|---:|---:|---:|"
    if is_dry:
        header += "Harmattan d | "
        sep += "---:|"
    header += "Score | Diagnostic |"
    sep += "---:|---|"

    rows: list[str] = []
    for loc in season.locations:
        cells = [
            loc.location_name,
            loc.country,
            f"{loc.stats.total_precip_mm:.0f}",
            f"{loc.stats.total_et0_mm:.0f}",
            _format_signed(loc.stats.cumulative_balance_mm),
            str(loc.stats.days_rain),
            str(loc.stats.days_stress_temp),
            f"{loc.stats.avg_tmax:.1f}",
        ]
        if is_dry:
            cells.append("—" if loc.harmattan_days is None else str(loc.harmattan_days))
        cells.append(_format_score(loc.score))
        cells.append(f"`{loc.diagnostic}`")
        rows.append("| " + " | ".join(cells) + " |")

    days_in_range = (
        season.season_range.end_date - season.season_range.start_date
    ).days + 1
    title = season.season_range.season.name.replace("_", " ").title()
    return (
        f"### {title} — {season.season_range.months_covered}\n"
        f"_{season.season_range.start_date} → {season.season_range.end_date} "
        f"({days_in_range} days)_\n\n"
        + header
        + "\n"
        + sep
        + "\n"
        + "\n".join(rows)
        + "\n"
    )


def _build_tldr(backtest: CampaignBacktest) -> str:
    flat = [loc for s in backtest.seasons for loc in s.locations]
    if not flat:
        return "## TL;DR\n\nNo seasons computed — empty backtest.\n"

    campaign_avg = sum(loc.score for loc in flat) / len(flat)

    # Per-season averages — campaign label is driven by the WORST season
    # (Copernicus EDO peak-severity, Climate Central per-season methodology).
    season_avgs = {
        s.season_range.season.name: (
            sum(loc.score for loc in s.locations) / len(s.locations)
            if s.locations
            else 5.0
        )
        for s in backtest.seasons
    }
    worst_season_name = min(season_avgs, key=lambda k: season_avgs[k])
    worst_season_avg = season_avgs[worst_season_name]

    worst = min(flat, key=lambda loc: loc.score)
    best = max(flat, key=lambda loc: loc.score)
    stress_count = sum(1 for loc in flat if loc.diagnostic == "stress")
    degraded_count = sum(1 for loc in flat if loc.diagnostic == "degraded")
    normal_count = sum(1 for loc in flat if loc.diagnostic == "normal")

    harmattan_total = sum(
        loc.harmattan_days
        for s in backtest.seasons
        for loc in s.locations
        if loc.harmattan_days is not None
    )

    # Where each score came from (which season)
    season_of = {
        id(loc): s.season_range.season.name
        for s in backtest.seasons
        for loc in s.locations
    }

    season_breakdown = "\n".join(
        f"  - `{name}`: {avg:.2f}/5"
        for name, avg in sorted(season_avgs.items(), key=lambda kv: kv[1])
    )

    return f"""## TL;DR

- **Campaign**: `{backtest.campaign}` (target date {backtest.target_date})
- **Health label** (worst-season-driven, per Copernicus EDO / Climate Central): **{worst_season_avg:.2f} / 5** \
({worst_season_name}) — {_campaign_health_line(worst_season_avg)}
- **Overall average** (secondary stat — diluted by good seasons): {campaign_avg:.2f} / 5
- **Per-season averages** (worst → best):
{season_breakdown}
- **Diagnostic spread**: `stress`={stress_count}, `degraded`={degraded_count}, `normal`={normal_count} (out of {len(flat)} season-location pairs)
- **Worst pair**: {worst.location_name} / `{season_of[id(worst)]}` → {_format_score(worst.score)}
- **Best pair**: {best.location_name} / `{season_of[id(best)]}` → {_format_score(best.score)}
- **Cumulative Harmattan days** (sum across 6 locations, saison_seche only): **{harmattan_total}** \
(critical threshold = 24 d/location)
"""


def _build_pipeline_integrity(backtest: CampaignBacktest) -> str:
    lines = [
        "## Pipeline integrity",
        "",
        "For each (season × location), `expected_days` is the inclusive span of the "
        "season range; `fetched_days` is what Open-Meteo returned. A gap of 1-5 days "
        "in the most recent season is expected (archive publication lag).",
        "",
        "| Season | Location | Expected | Fetched | Δ |",
        "|---|---|---:|---:|---:|",
    ]
    for season in backtest.seasons:
        for loc in season.locations:
            delta = loc.stats.total_days - loc.expected_days
            lines.append(
                f"| {season.season_range.season.name} | {loc.location_name} | "
                f"{loc.expected_days} | {loc.stats.total_days} | {delta:+d} |"
            )
    return "\n".join(lines) + "\n"


def _build_cross_check_guide(backtest: CampaignBacktest) -> str:
    lines = [
        "## Cross-check guide",
        "",
        "For each location below, the raw daily series is exported to `raw/<season>_<location>.csv`. "
        "Paste your reference figures (other weather provider, national met agency, station data) "
        "next to ours and diff. The fields we trust the most for cross-check are `precip_mm`, "
        "`tmax_c`, and (for saison_seche) `min_rh_pct` + `harmattan_flag`.",
        "",
        "| Location | Country | Total precip (mm) across all seasons | Avg Tmax | Notes |",
        "|---|---|---:|---:|---|",
    ]
    # Aggregate per location across all seasons
    agg: dict[str, dict[str, float | str]] = {}
    for season in backtest.seasons:
        for loc in season.locations:
            slot = agg.setdefault(
                loc.location_name,
                {"country": loc.country, "precip": 0.0, "tmax_sum": 0.0, "tmax_n": 0},
            )
            slot["precip"] = float(slot["precip"]) + loc.stats.total_precip_mm
            if loc.stats.total_days > 0:
                slot["tmax_sum"] = (
                    float(slot["tmax_sum"]) + loc.stats.avg_tmax * loc.stats.total_days
                )
                slot["tmax_n"] = int(slot["tmax_n"]) + loc.stats.total_days
    for name, slot in agg.items():
        n = int(slot["tmax_n"])
        avg_tmax = float(slot["tmax_sum"]) / n if n > 0 else 0.0
        lines.append(
            f"| {name} | {slot['country']} | {float(slot['precip']):.0f} | "
            f"{avg_tmax:.1f} | see `raw/*_{name.replace(' ', '-')}.csv` |"
        )
    return "\n".join(lines) + "\n"


def build_report(backtest: CampaignBacktest, output_dir: Path) -> Path:
    """Write report.md to output_dir. Returns the path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "report.md"

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    sections = [
        f"# Backtest — Seasonal Score / Cocoa Campaign {backtest.campaign}",
        "",
        f"_Generated: {generated_at}_",
        "",
        _build_tldr(backtest),
        _build_methodology(),
    ]
    sections.append("## Per-season scores")
    sections.append("")
    for season in backtest.seasons:
        sections.append(_build_season_table(season))
    sections.append(_build_cross_check_guide(backtest))
    sections.append(_build_pipeline_integrity(backtest))

    path.write_text("\n".join(sections), encoding="utf-8")
    logger.info("Wrote report → %s", path)
    return path

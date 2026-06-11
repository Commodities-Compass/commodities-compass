"""Unit tests for the symmetric excess-water scoring in seasonal_memory.

Pure unit tests — no DB, no network. They pin the asymmetry-by-design:
excess water (chronic surplus balance + acute heavy-rain days) is penalized in
rainy seasons but NOT in the dry season, where a positive balance is drought
relief. Drought scoring must remain unchanged (regression guard).

Some stats are synthetic (precip / et0 / balance not mutually consistent) to
isolate a single scoring branch — compute_score treats them as independent
inputs, so this is a legitimate test of its branching.
"""

from __future__ import annotations

from scripts.meteo_agent.config import SEASONAL_PROFILES
from scripts.meteo_agent.seasonal_memory import (
    LocationSeasonStats,
    compute_score,
    compute_season_stats,
)

GRANDE = next(p for p in SEASONAL_PROFILES if p.name == "grande_saison_pluies")
DRY = next(p for p in SEASONAL_PROFILES if p.name == "saison_seche")
PETITE_SECHE = next(p for p in SEASONAL_PROFILES if p.name == "petite_saison_seche")


def _stats(
    *,
    days: int,
    precip: float,
    et0: float,
    heavy: int,
    stress: int = 0,
    tmax: float = 30.0,
) -> LocationSeasonStats:
    return LocationSeasonStats(
        location_name="Daloa",
        country="Côte d'Ivoire",
        total_precip_mm=precip,
        total_et0_mm=et0,
        cumulative_balance_mm=round(precip - et0, 1),
        days_rain=min(days, 60),
        days_stress_temp=stress,
        avg_tmax=tmax,
        total_days=days,
        days_heavy_rain=heavy,
    )


# ---------------------------------------------------------------------------
# Excess water IS penalized in rainy seasons
# ---------------------------------------------------------------------------


def test_excess_rain_penalized_in_rainy_season():
    # grande norms (150-350)/30d → over 90d (450-1050): precip 900 is neutral.
    # balance avg +9 mm/day → -1.5 (waterlogging); 12 heavy-rain days → -1.5.
    s = _stats(days=90, precip=900, et0=90, heavy=12)
    assert compute_score(s, GRANDE) == 2.0


def test_heavy_rain_alone_penalizes_in_rainy_season():
    # Balance neutral (precip == et0), only the acute heavy-rain counter fires.
    s = _stats(days=90, precip=600, et0=600, heavy=8)
    assert compute_score(s, GRANDE) == 4.0


def test_surplus_balance_alone_penalizes_in_rainy_season():
    # Chronic surplus, no intense days → only the balance-surplus tier fires.
    s = _stats(days=90, precip=900, et0=90, heavy=0)
    assert compute_score(s, GRANDE) == 3.5


# ---------------------------------------------------------------------------
# Excess water is GATED OUT of the dry seasons (drought relief, not stress)
# ---------------------------------------------------------------------------


def test_excess_gated_out_in_dry_season():
    # Same wet numbers as the rainy-season test. The gated tiers (surplus +
    # heavy-rain) do NOT fire; only the season-agnostic precip-excess block does
    # (900 mm is a true anomaly vs the dry-season norm), so the dry score is
    # strictly HIGHER than the rainy score.
    s = _stats(days=90, precip=900, et0=90, heavy=12)
    dry = compute_score(s, DRY)
    rainy = compute_score(s, GRANDE)
    assert dry == 3.0
    assert dry > rainy


def test_moderate_dry_wetness_not_penalized():
    # Moderate, in-norm rain with a small positive balance during the dry season
    # = drought relief → perfect score (no excess penalty of any kind).
    s = _stats(days=90, precip=150, et0=100, heavy=0)
    assert compute_score(s, DRY) == 5.0


def test_petite_saison_seche_treated_as_dry():
    # Month-8 dry pause is not in RAINY_SEASONS: surplus + heavy-rain gated out.
    s = _stats(days=90, precip=200, et0=20, heavy=12)
    assert compute_score(s, PETITE_SECHE) == 5.0


# ---------------------------------------------------------------------------
# Drought scoring is unchanged (regression guard)
# ---------------------------------------------------------------------------


def test_drought_scoring_unchanged():
    # Deficit precip + persistent negative balance + full Harmattan → floors at
    # 1.0, exactly as before the excess tiers were added.
    s = _stats(days=90, precip=20, et0=400, heavy=0)
    assert compute_score(s, DRY, harmattan_days=24) == 1.0


# ---------------------------------------------------------------------------
# compute_season_stats — heavy-rain day counter
# ---------------------------------------------------------------------------


def test_compute_season_stats_counts_heavy_rain_days():
    # HEAVY_RAIN_MM_DAY = 20.0, strictly greater-than. 25/30/21/100 qualify (4);
    # 20.0 is NOT > 20, and 19/5/0 are below.
    data = {
        "daily": {
            "precipitation_sum": [25.0, 5.0, 30.0, 0.0, 21.0, 19.0, 100.0, 20.0],
            "et0_fao_evapotranspiration": [4.0] * 8,
            "temperature_2m_max": [30.0] * 8,
        }
    }
    stats = compute_season_stats(data, "Daloa", "Côte d'Ivoire", 32.0)
    assert stats.days_heavy_rain == 4
    assert stats.total_days == 8


def test_compute_season_stats_empty_heavy_rain_is_zero():
    stats = compute_season_stats({"daily": {}}, "Daloa", "Côte d'Ivoire", 32.0)
    assert stats.days_heavy_rain == 0
    assert stats.total_days == 0

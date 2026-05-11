"""Tests for weather_service aggregation helpers.

Focus: `compute_campaign_health` follows the worst-season methodology
(Copernicus EDO / Climate Central) rather than an overall average.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.weather_service import compute_campaign_health


def _score(season_name: str, score: float) -> SimpleNamespace:
    """Minimal duck-typed stand-in for PlSeasonalScore (only `score` and `season_name` read)."""
    return SimpleNamespace(season_name=season_name, score=score)


def test_compute_campaign_health_returns_none_when_empty():
    assert compute_campaign_health([]) is None


def test_compute_campaign_health_picks_worst_season_average():
    """saison_seche avg = 2.0, all other seasons avg >= 4.5 → worst = 2.0."""
    scores = [
        # saison_seche: 6 locations averaging 2.0 (the disaster window)
        _score("saison_seche", 1.5),
        _score("saison_seche", 5.0),  # one coastal outlier
        _score("saison_seche", 2.0),
        _score("saison_seche", 2.0),
        _score("saison_seche", 1.5),
        _score("saison_seche", 0.0),  # synthetic floor to anchor avg
        # grande_saison_pluies: all healthy
        _score("grande_saison_pluies", 5.0),
        _score("grande_saison_pluies", 4.5),
        _score("grande_saison_pluies", 5.0),
    ]
    # saison_seche avg = (1.5+5+2+2+1.5+0)/6 = 12/6 = 2.0
    # grande_pluies avg = 14.5/3 ≈ 4.83
    # worst = 2.0
    assert compute_campaign_health(scores) == 2.0


def test_compute_campaign_health_single_season_returns_that_average():
    """Early in a campaign only one season has data — that's the campaign health."""
    scores = [
        _score("petite_saison_pluies", 4.0),
        _score("petite_saison_pluies", 4.5),
        _score("petite_saison_pluies", 5.0),
    ]
    # avg = 4.5
    assert compute_campaign_health(scores) == 4.5


def test_compute_campaign_health_ignores_overall_average_dilution():
    """Sanity check: simple average would mask the worst season.

    Overall avg here = (1.0 + 5.0 + 5.0 + 5.0) / 4 = 4.0 → looks healthy.
    Worst season = saison_seche at 1.0 → real picture.
    """
    scores = [
        _score("saison_seche", 1.0),
        _score("transition_pluies", 5.0),
        _score("grande_saison_pluies", 5.0),
        _score("petite_saison_seche", 5.0),
    ]
    assert compute_campaign_health(scores) == 1.0

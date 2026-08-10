"""Deterministic cross-day drift over a window of briefs.

We pre-compute what we *can* measure numerically (weather impact trajectory,
base-confidence trajectory) so the LLM does not have to eyeball it. The prose
drift (press sentiment turning) stays the judge's job — but it is handed the
numeric series as an anchor. Briefs are expected oldest-first.
"""

from __future__ import annotations

from .schema import Brief, Drift


def compute_drift(briefs: list[Brief]) -> Drift:
    """Summarise how the macro picture moved across the window."""
    if not briefs:
        return Drift(n_days=0)

    weather_series = tuple(
        b.weather.impact_10 for b in briefs if b.weather.impact_10 is not None
    )
    weather_delta = (
        weather_series[-1] - weather_series[0] if len(weather_series) >= 2 else None
    )

    notes: list[str] = []
    if weather_delta is not None and abs(weather_delta) >= 2.0:
        arrow = "rising" if weather_delta > 0 else "easing"
        notes.append(f"weather-impact {arrow} {weather_series[0]:.0f}->{weather_series[-1]:.0f}/10")

    confs = [b.base_confidence for b in briefs]
    if len(confs) >= 2 and confs[-1] != confs[0]:
        notes.append(f"base-confidence {confs[0]:.1f}->{confs[-1]:.1f}/5")

    return Drift(
        n_days=len(briefs),
        weather_impact_series=weather_series,
        weather_delta=weather_delta,
        notes=tuple(notes),
    )

"""Deterministic cross-day drift over a window of briefs.

We pre-compute what we *can* measure numerically (weather impact trajectory,
price path, base-confidence trajectory) so the LLM does not have to eyeball it.
The prose drift (press sentiment turning) stays the judge's job — but it is
handed the numeric series as an anchor. Briefs are expected oldest-first.

v0.2 fine-tune: adds the price path (cumulative + step returns). Feeds the
PRICE-VS-THESIS rule in the system prompt so the judge can see whether its
macro thesis is already priced in before committing to yet another flip.
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

    closes = [b.close for b in briefs if b.close is not None]
    price_series = tuple(closes)
    price_cum_move: float | None = None
    price_step_moves: tuple[float, ...] = ()
    if len(closes) >= 2 and closes[0]:
        price_cum_move = (closes[-1] - closes[0]) / closes[0]
        price_step_moves = tuple(
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
            if closes[i - 1]
        )

    notes: list[str] = []
    if weather_delta is not None and abs(weather_delta) >= 2.0:
        arrow = "rising" if weather_delta > 0 else "easing"
        notes.append(f"weather-impact {arrow} {weather_series[0]:.0f}->{weather_series[-1]:.0f}/10")
    if price_cum_move is not None and abs(price_cum_move) >= 0.03:
        arrow = "up" if price_cum_move > 0 else "down"
        notes.append(f"price {arrow} {price_cum_move * 100:+.1f}% over window")

    confs = [b.base_confidence for b in briefs]
    if len(confs) >= 2 and confs[-1] != confs[0]:
        notes.append(f"base-confidence {confs[0]:.1f}->{confs[-1]:.1f}/5")

    return Drift(
        n_days=len(briefs),
        weather_impact_series=weather_series,
        weather_delta=weather_delta,
        price_series=price_series,
        price_cum_move=price_cum_move,
        price_step_moves=price_step_moves,
        notes=tuple(notes),
    )

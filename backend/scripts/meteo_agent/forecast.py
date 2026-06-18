"""Forward-risk synthesis from the forecast portion of the Open-Meteo series.

Pure helper: anchors the LLM's forward-risk step (ÉTAPE 3) with a deterministic
6-zone aggregate so the J+1→J+5 risk isn't hand-waved. No network, no DB.
"""

from __future__ import annotations

import json
import logging

from scripts.meteo_agent.config import HEAVY_RAIN_MM_DAY, PAST_DAYS

logger = logging.getLogger(__name__)


def summarize_forecast(weather_json: str, past_days: int = PAST_DAYS) -> str:
    """Aggregate the strictly-forward (tomorrow → J+5) portion across all zones.

    The Open-Meteo daily arrays are chronological: the first ``past_days`` entries
    are observed, index ``past_days`` is today, and the rest is forecast. We drop
    yesterday + today and aggregate forward precip, heavy-rain day-zones, and the
    forward water balance. Returns "" if the payload can't be parsed (non-blocking).
    """
    try:
        data = json.loads(weather_json)
    except (ValueError, TypeError):
        return ""
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return ""

    offset = past_days + 1  # skip observed past days + today → strictly forward
    n_loc = 0
    fwd_precip_total = 0.0
    heavy_day_zones = 0
    zones_wet = 0
    fwd_len = 0
    for entry in data:
        if not isinstance(entry, dict):
            continue
        daily = entry.get("daily", {})
        precip = [p or 0.0 for p in (daily.get("precipitation_sum") or [])[offset:]]
        et0 = [
            e or 0.0 for e in (daily.get("et0_fao_evapotranspiration") or [])[offset:]
        ]
        if not precip:
            continue
        n_loc += 1
        fwd_len = max(fwd_len, len(precip))
        fwd_precip_total += sum(precip)
        heavy_day_zones += sum(1 for p in precip if p > HEAVY_RAIN_MM_DAY)
        if sum(precip) - sum(et0) > 0:
            zones_wet += 1

    if n_loc == 0:
        return ""

    avg_precip = fwd_precip_total / n_loc
    return (
        f"\n\nPRÉVISION J+1→J+{fwd_len} (synthèse {n_loc} zones) : "
        f"précip. moyenne cumulée {avg_precip:.0f} mm/zone, "
        f"{heavy_day_zones} jour-zones de pluie intense (>{HEAVY_RAIN_MM_DAY:.0f} mm), "
        f"{zones_wet}/{n_loc} zones en bilan prévisionnel positif (humide)."
    )

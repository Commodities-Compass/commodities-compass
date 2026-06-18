"""Unit tests for the forward-aware / regime-aware meteo enrichment.

Pure unit tests — no DB, no network. Cover the dynamic bidirectional ENSO
classifier (El Niño dryness ↔ La Niña excess), the Niño 3.4 momentum hint,
the staleness guard, and the forecast forward-risk synthesis.
"""

from __future__ import annotations

import json
from datetime import date

from scripts.meteo_agent.forecast import summarize_forecast
from scripts.meteo_agent.seasonal_memory import classify_enso_regime

REF = date(2026, 6, 18)


# ---------------------------------------------------------------------------
# ENSO regime classifier — bidirectional + dynamic
# ---------------------------------------------------------------------------


def test_el_nino_leans_dry():
    out = classify_enso_regime(oni=0.7, oni_date=date(2026, 5, 1), reference_date=REF)
    assert "El Niño" in out
    assert "SÈCHE" in out and "Harmattan" in out


def test_la_nina_leans_wet_black_pod():
    out = classify_enso_regime(oni=-0.7, oni_date=date(2026, 5, 1), reference_date=REF)
    assert "La Niña" in out
    assert "HUMIDE" in out and "black pod" in out


def test_neutral_no_strong_bias():
    out = classify_enso_regime(oni=0.1, oni_date=date(2026, 5, 1), reference_date=REF)
    assert "neutre" in out


def test_nino34_momentum_flags_warming_toward_el_nino():
    # Neutral ONI but Niño 3.4 already warm → bascule toward El Niño.
    out = classify_enso_regime(
        oni=0.13,
        oni_date=date(2026, 5, 1),
        reference_date=REF,
        nino34=0.82,
        nino34_date=date(2026, 5, 1),
    )
    assert "neutre" in out
    assert "Niño 3.4 +0.82" in out
    assert "réchauffement" in out and "El Niño" in out


def test_nino34_momentum_flags_cooling_toward_la_nina():
    out = classify_enso_regime(
        oni=0.1,
        oni_date=date(2026, 5, 1),
        reference_date=REF,
        nino34=-0.7,
        nino34_date=date(2026, 5, 1),
    )
    assert "refroidissement" in out and "La Niña" in out


def test_staleness_guard_fires_when_data_old():
    # ONI from March vs June reference → > 75 days → abnormal staleness warning.
    out = classify_enso_regime(oni=0.13, oni_date=date(2026, 3, 1), reference_date=REF)
    assert "⚠" in out and "ancienne" in out


def test_no_staleness_warning_when_recent():
    out = classify_enso_regime(oni=0.13, oni_date=date(2026, 5, 20), reference_date=REF)
    assert "⚠" not in out


def test_real_prod_scenario_neutral_warming_and_stale():
    # The live prod picture (Jun 2026): ONI +0.13 (Mar), Niño 3.4 +0.82 (May).
    out = classify_enso_regime(
        oni=0.13,
        oni_date=date(2026, 3, 1),
        reference_date=REF,
        nino34=0.82,
        nino34_date=date(2026, 5, 1),
    )
    assert "neutre" in out  # official ONI still neutral
    assert "bascule possible vers El Niño" in out  # but momentum warms
    assert "ancienne" in out  # and the ONI row is stale


# ---------------------------------------------------------------------------
# Forecast forward-risk synthesis
# ---------------------------------------------------------------------------


def _zone(name: str, precip: list[float]) -> dict:
    return {
        "location_name": name,
        "country": "Côte d'Ivoire",
        "daily": {
            "precipitation_sum": precip,
            "et0_fao_evapotranspiration": [4.0] * len(precip),
        },
    }


def test_summarize_forecast_aggregates_forward_only():
    # 7-day arrays: [yesterday, today, J+1..J+5]. Only J+1..J+5 (index 2:) count.
    # forward = [25, 30, 10, 22, 5] → heavy(>20mm): 25,30,22 = 3 per zone; wet.
    precip = [2.0, 3.0, 25.0, 30.0, 10.0, 22.0, 5.0]
    payload = json.dumps([_zone("Daloa", precip), _zone("Soubré", precip)])
    out = summarize_forecast(payload, past_days=1)
    assert "PRÉVISION J+1→J+5" in out
    assert "6 jour-zones de pluie intense" in out  # 3 heavy days × 2 zones
    assert "2/2 zones" in out  # both forward-positive balance


def test_summarize_forecast_dry_forecast_not_flagged_wet():
    precip = [1.0, 1.0, 0.0, 1.0, 0.0, 2.0, 0.0]  # forward sum=3mm, balance negative
    payload = json.dumps([_zone("Daloa", precip)])
    out = summarize_forecast(payload, past_days=1)
    assert "0 jour-zones de pluie intense" in out
    assert "0/1 zones" in out


def test_summarize_forecast_handles_malformed():
    assert summarize_forecast("not json") == ""
    assert summarize_forecast(json.dumps({"daily": {}})) == ""
    assert summarize_forecast(json.dumps([])) == ""

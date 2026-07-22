"""Shared farmgate-price helper for the brief generators (legacy + ensemble).

Reads the latest official/guaranteed farmgate price effective on/before a date
(CCC for CIV, COCOBOD for Ghana) and formats it as brief lines, FR or EN. Used
by both ``compass_brief`` and ``compass_brief_ensemble`` so the section stays in
sync across the dual track.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_REGIONS = ("civ", "ghana")

_QUERY = text(
    "SELECT season_label, price_native, currency, unit "
    "FROM pl_official_farmgate_price "
    "WHERE region = :region AND effective_date <= :on_date "
    "ORDER BY effective_date DESC, announced_date DESC NULLS LAST LIMIT 1"
)

_CURRENCY_LABEL = {"XOF": "FCFA", "GHS": "GHS"}
_UNIT_LABEL = {"per_kg": "/kg", "per_bag_64kg": "/sac 64 kg", "per_tonne": "/t"}

_L = {
    "fr": {
        "header": "PRIX GARANTI OFFICIEL (CCC / COCOBOD)",
        "civ": "Côte d'Ivoire",
        "ghana": "Ghana",
        "campaign": "campagne",
        "none": "non annoncé",
        "disclaimer": "Prix officiel garanti, distinct du prix réel terrain.",
    },
    "en": {
        "header": "OFFICIAL GUARANTEED FARMGATE PRICE (CCC / COCOBOD)",
        "civ": "Côte d'Ivoire",
        "ghana": "Ghana",
        "campaign": "campaign",
        "none": "not announced",
        "disclaimer": "Official guaranteed price, distinct from the real terrain price.",
    },
}


def read_farmgate(session: Session, on_date: date) -> dict[str, dict | None]:
    """Latest effective farmgate price per region on/before ``on_date``."""
    out: dict[str, dict | None] = {}
    for region in _REGIONS:
        row = session.execute(_QUERY, {"region": region, "on_date": on_date}).first()
        out[region] = (
            {
                "season_label": row[0],
                "price_native": float(row[1]),
                "currency": row[2],
                "unit": row[3],
            }
            if row is not None
            else None
        )
    return out


def format_farmgate_lines(
    farmgate: Mapping[str, Any] | None, language: str = "fr"
) -> list[str]:
    """Format the farmgate section as brief lines. Empty list when no data."""
    lang = "en" if language == "en" else "fr"
    labels = _L[lang]
    if not farmgate or not any(farmgate.get(r) for r in _REGIONS):
        return []

    lines = [labels["header"]]
    for region in _REGIONS:
        entry = farmgate.get(region)
        region_label = labels[region]
        if entry:
            value = f"{entry['price_native']:,.0f}".replace(",", " ")
            currency = _CURRENCY_LABEL.get(entry["currency"], entry["currency"])
            unit = _UNIT_LABEL.get(entry["unit"], "")
            lines.append(
                f"{region_label} : {value} {currency}{unit} "
                f"({labels['campaign']} {entry['season_label']})"
            )
        else:
            lines.append(f"{region_label} : {labels['none']}")
    lines.append(labels["disclaimer"])
    return lines

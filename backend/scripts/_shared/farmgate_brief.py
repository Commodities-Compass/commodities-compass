"""Shared farmgate-price helper for the brief generators.

Sync mirror of ``app.services.farmgate_service`` — same rule, different session
flavour (the services layer is async, the brief jobs are sync). Both publish the
price **in force for the focus season**, the most recent season either origin
has announced; a region that has not announced anything for that season is
reported as awaiting its announcement rather than as holding last season's
price. Keep the two in step: the brief and the dashboard must never disagree on
the guaranteed price a client reads the same morning.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_REGIONS = ("civ", "ghana")

_FOCUS_SEASON = text("SELECT MAX(season_label) FROM pl_official_farmgate_price")

_IN_FORCE = text(
    "SELECT season_label, price_native, currency, unit "
    "FROM pl_official_farmgate_price "
    "WHERE region = :region AND season_label = :season AND effective_date <= :on_date "
    "ORDER BY effective_date DESC, announced_date DESC NULLS LAST LIMIT 1"
)

# Season announced but not started yet — publish the forthcoming price.
_FORTHCOMING = text(
    "SELECT season_label, price_native, currency, unit "
    "FROM pl_official_farmgate_price "
    "WHERE region = :region AND season_label = :season "
    "ORDER BY effective_date ASC, announced_date ASC NULLS FIRST LIMIT 1"
)

_CURRENCY_LABEL = {"XOF": "FCFA", "GHS": "GHS"}
_UNIT_LABEL = {"per_kg": "/kg", "per_bag_64kg": "/sac 64 kg", "per_tonne": "/t"}

_L = {
    "fr": {
        "header": "PRIX GARANTI OFFICIEL (CCC / COCOBOD)",
        "civ": "Côte d'Ivoire",
        "ghana": "Ghana",
        "campaign": "campagne",
        "pending": "en attente d'annonce",
        "disclaimer": "Prix officiel garanti, distinct du prix réel terrain.",
    },
    "en": {
        "header": "OFFICIAL GUARANTEED FARMGATE PRICE (CCC / COCOBOD)",
        "civ": "Côte d'Ivoire",
        "ghana": "Ghana",
        "campaign": "campaign",
        "pending": "awaiting announcement",
        "disclaimer": "Official guaranteed price, distinct from the real terrain price.",
    },
}


def read_farmgate(session: Session, on_date: date) -> dict[str, Any]:
    """Price in force for the focus season, per region.

    Shape: ``{"season": "2026/27"|None, "civ": {...}|None, "ghana": {...}|None}``.
    """
    season = session.execute(_FOCUS_SEASON).scalar()
    out: dict[str, Any] = {"season": season}
    for region in _REGIONS:
        out[region] = (
            _read_region(session, region, season, on_date)
            if season is not None
            else None
        )
    return out


def _read_region(
    session: Session, region: str, season: str, on_date: date
) -> dict[str, Any] | None:
    params = {"region": region, "season": season, "on_date": on_date}
    row = session.execute(_IN_FORCE, params).first()
    if row is None:
        row = session.execute(_FORTHCOMING, params).first()
    if row is None:
        return None
    return {
        "season_label": row[0],
        "price_native": float(row[1]),
        "currency": row[2],
        "unit": row[3],
    }


def format_farmgate_lines(
    farmgate: Mapping[str, Any] | None, language: str = "fr"
) -> list[str]:
    """Format the farmgate section as brief lines. Empty list when no data."""
    lang = "en" if language == "en" else "fr"
    labels = _L[lang]
    if not farmgate or not any(farmgate.get(r) for r in _REGIONS):
        return []

    season = farmgate.get("season")
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
            suffix = f" ({labels['campaign']} {season})" if season else ""
            lines.append(f"{region_label} : {labels['pending']}{suffix}")
    lines.append(labels["disclaimer"])
    return lines

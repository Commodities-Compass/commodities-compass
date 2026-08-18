"""Brief inputs shared by every track — press, weather, technicals, campaign.

These readers describe the MARKET, not a decision: the press review, the
weather bulletin, the seasonal trajectory and the last session's technicals are
the same whichever algorithm is speaking. Only the editorial section of a brief
is track-specific.

They live here rather than inside one track's module so that retiring a track
is a deletion, not a migration — the next track already imports from this file.

Every reader is language-parametric and reads the row for the REQUESTED
language: the prose is generated natively per language upstream (US-3c), never
translated at render time.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Season labels for the EN edition. FR uses the raw enum with underscores
# stripped, so only the English needs a mapping.
_SEASON_NAME_EN = {
    "saison_seche": "dry season",
    "transition_pluies": "rains transition",
    "grande_saison_pluies": "main rainy season",
    "petite_saison_seche": "short dry season",
    "petite_saison_pluies": "short rainy season",
}


def read_press(
    session: Session, target_date: date, language: str
) -> tuple[str, str, str]:
    # Press prose is generated natively per language (US-3c) — read the row for
    # the requested language, not the FR row translated.
    row = session.execute(
        text(
            """
            SELECT summary, impact_synthesis, COALESCE(sentiment, '')
            FROM pl_fundamental_article
            WHERE is_active = true AND date <= :date AND language = :language
            ORDER BY date DESC LIMIT 1
            """
        ),
        {"date": target_date, "language": language},
    ).fetchone()
    if row is None:
        return "", "", ""
    return (row[0] or "", row[1] or "", row[2] or "")


def read_meteo(session: Session, target_date: date, language: str) -> tuple[str, str]:
    # Weather bulletin is generated natively per language (US-3c) — read the
    # row for the requested language.
    row = session.execute(
        text(
            """
            SELECT summary, impact_assessment
            FROM pl_weather_observation
            WHERE date <= :date AND language = :language
            ORDER BY date DESC LIMIT 1
            """
        ),
        {"date": target_date, "language": language},
    ).fetchone()
    if row is None:
        return "", ""
    return (row[0] or "", row[1] or "")


def read_seasonal_trajectory(
    session: Session, target_date: date, language: str = "fr"
) -> str:
    """Compact campaign-trajectory line (cumulative seasonal health).

    Reads the in-progress season of the current campaign from pl_seasonal_score
    (same data as the dashboard CampaignBlock) — the long-term view the daily
    observation lacks. Returns "" between seasons or before the first backfill.

    ``pl_seasonal_score`` has no language dimension (scores are numeric,
    location-keyed); only the surrounding prose is rendered per language. The
    ``months_covered LIKE '%(en cours)%'`` filter matches a stored FR data
    marker, not display text — it stays FR regardless of output language.
    """
    rows = session.execute(
        text(
            """
            SELECT location_name, score, days_heavy_rain, season_name
            FROM pl_seasonal_score
            WHERE campaign = (SELECT MAX(campaign) FROM pl_seasonal_score)
              AND months_covered LIKE '%(en cours)%'
            ORDER BY location_name
            """
        )
    ).fetchall()
    if not rows:
        return ""
    raw_season = rows[0][3]
    if language == "en":
        season = _SEASON_NAME_EN.get(raw_season, raw_season.replace("_", " "))
    else:
        season = raw_season.replace("_", " ")
    avg = sum(float(r[1]) for r in rows) / len(rows)
    heavy = sum(int(r[2] or 0) for r in rows)
    worst = min(rows, key=lambda r: float(r[1]))
    if language == "en":
        return (
            f"Campaign trajectory — {season}: average health {avg:.1f}/5 "
            f"({len(rows)} zones), {heavy} zone-days of heavy rain cumulated, "
            f"weakest: {worst[0]} ({float(worst[1]):.1f}/5)."
        )
    return (
        f"Trajectoire campagne — {season} : santé moyenne {avg:.1f}/5 "
        f"({len(rows)} zones), {heavy} jour-zones de pluie intense cumulés, "
        f"plus faible : {worst[0]} ({float(worst[1]):.1f}/5)."
    )


def read_technicals(
    session: Session, target_date: date, contract_id: Any, language: str = "fr"
) -> str:
    row = session.execute(
        text(
            """
            SELECT date, close, high, low, volume, oi, implied_volatility
            FROM pl_contract_data_daily
            WHERE contract_id = :contract AND date <= :date
            ORDER BY date DESC LIMIT 1
            """
        ),
        {"date": target_date, "contract": contract_id},
    ).fetchone()
    if row is None:
        return (
            "(no technicals data)"
            if language == "en"
            else "(pas de données technicals)"
        )

    # stocks + CFTC net live in dedicated tables since 2026-05-27;
    # forward-fill the latest weekly observation on/before the row date.
    stock_us = session.execute(
        text(
            """
            SELECT value_tonnes FROM pl_stock_observation
            WHERE region = 'us' AND contract_market = 'cocoa' AND report_date <= :d
            ORDER BY report_date DESC LIMIT 1
            """
        ),
        {"d": row[0]},
    ).scalar_one_or_none()
    # value_tonnes (not value_native): EU native unit is 60 kg bags, so reading
    # value_native printed bags next to STOCK_US tonnes — ~16.7x overstated and
    # non-comparable. Tonnes keeps both sides in the same unit.
    stock_eu = session.execute(
        text(
            """
            SELECT value_tonnes FROM pl_stock_observation
            WHERE region = 'eu' AND contract_market = 'cocoa' AND report_date <= :d
            ORDER BY report_date DESC LIMIT 1
            """
        ),
        {"d": row[0]},
    ).scalar_one_or_none()
    com_net = session.execute(
        text(
            """
            SELECT prod_merc_net FROM pl_cot_us_weekly
            WHERE contract_market = 'cocoa' AND release_date <= :d
            ORDER BY release_date DESC LIMIT 1
            """
        ),
        {"d": row[0]},
    ).scalar_one_or_none()

    def _fmt(value, unit: str = "", precision: int = 2):
        if value is None:
            return "n/a"
        if isinstance(value, Decimal):
            return f"{float(value):,.{precision}f}{unit}"
        return f"{value}{unit}"

    date_label = "Session close" if language == "en" else "Date close"
    return (
        f"{date_label} : {row[0]}\n"
        f"  CLOSE={_fmt(row[1])} | HIGH={_fmt(row[2])} | LOW={_fmt(row[3])}\n"
        f"  VOLUME={_fmt(row[4], '', 0)} | OI={_fmt(row[5], '', 0)} | IV={_fmt(row[6])}\n"
        f"  STOCK_US={_fmt(stock_us)} | STOCK_EU={_fmt(stock_eu)} | COM_NET={_fmt(com_net)}"
    )


def compute_ytd_score(
    session: Session,
    reference_date: date,
    algorithm_version_id: Any,
) -> float | None:
    """Year-to-date score of ONE algorithm's own decisions.

    Sync mirror of ``dashboard_service.calculate_ytd_performance``, reusing its
    scoring function and horizon so the figure read aloud in the podcast is the
    figure on screen — two implementations of a headline number would drift.

    Scoped to a single algorithm. The ensemble-era version COALESCEd across two
    hardcoded algorithm names, which is precisely the cross-algorithm borrowing
    the pipeline no longer tolerates: an algorithm is scored on what it decided,
    never on a predecessor's calls.

    Front-month per date comes from the canonical roll calendar
    (``ref_contract.active_from``), and ``language='fr'`` is pinned because the
    decision is language-agnostic (the EN row copies it) — without the pin each
    date would fan out to two rows and the horizon-indexed walk would pair
    mismatched sessions.

    Returns None when nothing is scorable: 0.0 is a real score and would be
    read aloud as a flat year.
    """
    from app.services.dashboard_service import YTD_EVAL_HORIZON_DAYS, _score_day

    start = date(reference_date.year, 1, 1)
    rows = session.execute(
        text(
            """
            WITH front AS (
                SELECT dd.date,
                       (SELECT c.id FROM ref_contract c
                         WHERE c.active_from IS NOT NULL
                           AND c.active_from <= dd.date
                         ORDER BY c.active_from DESC LIMIT 1) AS contract_id
                FROM (SELECT DISTINCT date FROM pl_contract_data_daily
                       WHERE date >= :start AND date <= :end_date
                         AND close IS NOT NULL) dd
            )
            SELECT f.date, cd.close, i.decision
            FROM front f
            JOIN pl_contract_data_daily cd
                  ON cd.date = f.date AND cd.contract_id = f.contract_id
            LEFT JOIN pl_indicator_daily i
                   ON i.date = f.date AND i.contract_id = f.contract_id
                  AND i.language = 'fr'
                  AND i.algorithm_version_id = :aid
            ORDER BY f.date ASC
            """
        ),
        {"start": start, "end_date": reference_date, "aid": str(algorithm_version_id)},
    ).all()

    horizon = YTD_EVAL_HORIZON_DAYS
    scores: list[float] = []
    for i in range(len(rows) - horizon):
        current, future = rows[i], rows[i + horizon]
        if not current[2] or current[1] is None or future[1] is None:
            continue
        score = _score_day(current[2], float(current[1]), float(future[1]))
        if score is not None:
            scores.append(score)

    if not scores:
        logger.warning("No scorable session for the YTD up to %s", reference_date)
        return None
    return sum(scores) / len(scores) * 100

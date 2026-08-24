"""Self-computed regime features — decoupled from the shared pl_derived_indicators.

Regime was trained (by R&D) on the ROLL-NEUTRALIZED indicators. Rather than read
the stored ``pl_derived_indicators`` — which in prod is NOT neutralized, and
neutralizing it would alter the ensemble/legacy — the regime job recomputes its
OWN features from the raw front-month price chain (``pl_contract_data_daily`` via
``v_contract_data_chained``, identical local↔prod), using the SAME engine indicator
classes R&D trained on, and marking roll boundaries ITSELF.

Why this is safe for everything else: the engine indicator classes are
backward-compatible — without an ``is_roll_boundary`` column they behave exactly as
prod. Regime adds that column here (``mark_roll_boundaries``) so the return-based
indicators (daily_return / RSI / ATR) neutralize the phantom roll jump. The nightly
``cc-compute-indicators`` never marks it, so its output — and therefore the ensemble
and legacy pipeline — stays byte-for-byte unchanged.

Computed ONCE per run over the full chain (recursive RSI/ATR need the full history
to converge to the stored values); ``panel_loader.slice_panel`` cuts the per-date
window from it.
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.engine.indicators import ALL_INDICATORS
from app.engine.registry import IndicatorRegistry
from app.engine.runner import _convert_numeric_columns, mark_roll_boundaries
from regime.config import DERIVED_PASSTHROUGH

logger = logging.getLogger(__name__)


class RegimeFeatureError(RuntimeError):
    """Raised on a missing/duplicated raw chain or a missing engine output column."""


class RegimeChainGapError(RegimeFeatureError):
    """A scraped session is absent from the front-month chain (roll hole)."""


# Every session the scraper wrote must appear in the chain. Since d5e6f7a8b9c0
# the VIEW is a calendar INNER JOIN, so a date whose calendar front-month has no
# OHLCV row is silently DROPPED rather than erroring — the exact shape of a roll
# performed mid-session (is_active repoints the scraper now, active_from only
# takes effect next session). Scoped to the chain's own span: prehistory older
# than the earliest active_from is legitimately absent and is not a gap.
_CHAIN_GAP_SQL = text(
    """
    SELECT DISTINCT d.date
    FROM pl_contract_data_daily d
    WHERE d.close IS NOT NULL
      AND d.date >= :chain_min
      AND NOT EXISTS (
          SELECT 1 FROM v_contract_data_chained v WHERE v.date = d.date
      )
    ORDER BY d.date
    """
)


def assert_chain_has_no_gaps(session: Session, chain_min: date) -> None:
    """Fail loud if a scraped session inside the chain's span is missing from it.

    Silent corruption otherwise: the positional rolling windows (Wilder RSI/ATR,
    EMA, 252d z-scores) would shift by one step, and the job would publish an
    older session's decision as today's. See .claude/rules/timeseries-uniqueness.md.
    """
    missing = [
        r.date
        for r in session.execute(_CHAIN_GAP_SQL, {"chain_min": chain_min}).fetchall()
    ]
    if missing:
        raise RegimeChainGapError(
            f"{len(missing)} scraped session(s) missing from v_contract_data_chained "
            f"(first: {', '.join(str(d) for d in missing[:5])}). The calendar "
            "front-month for those dates has no pl_contract_data_daily row — a roll "
            "was almost certainly executed mid-session (ref_contract.is_active "
            "repointed the scraper before active_from took effect). Fix the roll "
            "calendar, then re-scrape/backfill the missing session(s); do NOT "
            "compute over a holed chain."
        )


# Same front-month chain the engine's load_all_market_data reads (front-month per
# date via the canonical roll calendar), but WITHOUT its mark_roll_boundaries call —
# regime does its own marking below so nothing in the shared compute path changes.
_CHAIN_SQL = """
WITH market AS (
    SELECT v.date, v.close, v.high, v.low, v.volume, v.oi, v.implied_volatility,
           v.contract_id, c.code AS contract_code
    FROM v_contract_data_chained v
    JOIN ref_contract c ON c.id = v.contract_id
)
SELECT m.date, m.close, m.high, m.low, m.volume, m.oi, m.implied_volatility,
       m.contract_id, m.contract_code
FROM market m
ORDER BY m.date ASC
"""

_RAW_COLS = [
    "date",
    "close",
    "high",
    "low",
    "volume",
    "oi",
    "implied_volatility",
    "contract_id",
    "contract_code",
]


def build_selfcomputed_features(session: Session) -> pd.DataFrame:
    """Return the roll-neutralized 9-feature chain over full front-month history.

    Columns: date, contract_id, is_roll_boundary + the 9 DERIVED_PASSTHROUGH.
    One row per session. Never reads pl_derived_indicators.
    """
    rows = session.execute(text(_CHAIN_SQL)).fetchall()
    if not rows:
        raise RegimeFeatureError(
            "v_contract_data_chained empty — no raw front-month price chain"
        )
    df = _convert_numeric_columns(pd.DataFrame(rows, columns=pd.Index(_RAW_COLS)))
    df["date"] = pd.to_datetime(df["date"])

    # One row per time step — a fan-out would silently corrupt the recursive
    # RSI/ATR (.claude/rules/timeseries-uniqueness.md).
    if not df["date"].is_unique:
        dups = list(df.loc[df["date"].duplicated(keep=False), "date"].dt.date.unique())
        raise RegimeFeatureError(
            f"raw chain has duplicate dates {dups[:5]} — v_contract_data_chained "
            "must be DISTINCT ON (date)"
        )

    # The VIEW is a calendar INNER JOIN: a session whose front-month has no row is
    # dropped silently rather than raising. Catch it here, before it shifts every
    # positional window and freezes the published session.
    assert_chain_has_no_gaps(session, df["date"].min().date())

    # Regime marks its OWN roll boundaries (contract_code changes) → the engine
    # indicators neutralize the phantom splice. cc-compute-indicators does not mark,
    # so this never leaks into the shared pl_derived_indicators.
    df = mark_roll_boundaries(df)

    registry = IndicatorRegistry()
    registry.register_all(ALL_INDICATORS)
    derived = registry.compute_all(df)

    missing = [c for c in DERIVED_PASSTHROUGH if c not in derived.columns]
    if missing:
        raise RegimeFeatureError(f"engine did not produce required columns: {missing}")

    keep = ["date", "contract_id", "is_roll_boundary", *DERIVED_PASSTHROUGH]
    out = derived[keep].copy()
    logger.info(
        "Self-computed %d-row neutralized feature chain (%s..%s), %d roll boundaries",
        len(out),
        out["date"].min().date(),
        out["date"].max().date(),
        int(out["is_roll_boundary"].sum()),
    )
    return out

"""Dashboard gauges — raw → 5d SMA → rolling 252d z-score, then persisted.

Lives in the engine because the engine already computes these exact two stages
for its own composite: deriving them in a separate job duplicated the work and,
worse, created a second implementation free to drift. Here the gauge stage
calls the same ``compute_raw_scores`` / ``rolling_zscore`` the composite uses,
so the two cannot diverge.

The displayed gauge is the z-score of the SMOOTHED score, not of the raw
indicator. Getting that wrong is invisible: the numbers stay plausible, they
just stop matching the ``test_range`` calibration and the colours silently
drift.

Despite living in the engine, the gauge stage is deliberately independent of
``pl_algorithm_version``: it reads no algorithm, writes no algorithm-keyed row,
and runs once per session rather than once per version. The gauges describe the
market, not a decision — which is why they survive an algorithm change.
"""

from __future__ import annotations

import logging
import math

import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.engine.normalization import rolling_zscore
from app.engine.smoothing import compute_raw_scores
from app.models.pipeline import PlDashboardGauge

logger = logging.getLogger(__name__)

# Gauge-owned constants. They MUST NOT be read from pl_algorithm_config: the
# whole point of this job is that a gauge no longer depends on an algorithm's
# configuration. They mirror the engine defaults in force when the gauges were
# calibrated (smoothing_window=5, DEFAULT_WINDOW=252, DEFAULT_OUTLIER_CAP=10).
GAUGE_SMOOTHING_WINDOW = 5
GAUGE_NORM_WINDOW = 252
GAUGE_OUTLIER_CAP = 10.0

# The five gauges the dashboard renders, as
#   (test_range.indicator, derived column, score column, norm column).
# Order is the display order in INDICATOR_KEYS. `close_pivot` is intentionally
# absent: the engine computes it but no gauge shows it.
GAUGE_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("MACD", "macd", "macd_score", "macd_norm"),
    ("VOL_OI", "volume_oi_ratio", "volume_oi", "vol_oi_norm"),
    ("RSI", "rsi_14d", "rsi_score", "rsi_norm"),
    ("%K", "stochastic_k_14", "stochastic_score", "stoch_k_norm"),
    ("ATR", "atr_14d", "atr_score", "atr_norm"),
)

# Columns compute_raw_scores() needs. close_pivot_ratio is required by its
# _DIRECT_SCORES mapping even though we never publish that gauge.
_REQUIRED_DERIVED_COLUMNS = (
    "rsi_14d",
    "macd",
    "stochastic_k_14",
    "atr_14d",
    "volume_oi_ratio",
    "close_pivot_ratio",
)

# One row per session on the canonical front-month chain. Reading the chained
# VIEW (not ref_contract.is_active) is what keeps the gauges alive across a
# roll — an is_active-keyed read blanks them on the roll boundary.
_CHAIN_SQL = """
    SELECT v.date, v.contract_id,
           d.rsi_14d, d.macd, d.stochastic_k_14, d.atr_14d,
           d.volume_oi_ratio, d.close_pivot_ratio
    FROM v_contract_data_chained v
    JOIN pl_derived_indicators d
      ON d.date = v.date AND d.contract_id = v.contract_id
    ORDER BY v.date ASC
"""


class GaugeSeriesError(RuntimeError):
    """The derived-indicator series is empty, duplicated, or missing a column."""


def load_derived_chain(session: Session) -> pd.DataFrame:
    """Front-month derived indicators, one row per session, oldest first."""
    rows = session.execute(text(_CHAIN_SQL)).fetchall()
    if not rows:
        raise GaugeSeriesError(
            "No rows joining v_contract_data_chained to pl_derived_indicators — "
            "has cc-compute-indicators run?"
        )
    df = pd.DataFrame(rows, columns=pd.Index(list(rows[0]._mapping.keys())))
    df["date"] = pd.to_datetime(df["date"])

    missing = [c for c in _REQUIRED_DERIVED_COLUMNS if c not in df.columns]
    if missing:
        raise GaugeSeriesError(f"pl_derived_indicators is missing columns {missing}")

    # Rolling/positional computation ahead — a duplicated date would silently
    # corrupt every SMA and z-score downstream.
    # See .claude/rules/timeseries-uniqueness.md.
    if not df["date"].is_unique:
        dups = list(df.loc[df["date"].duplicated(keep=False), "date"].dt.date.unique())
        raise GaugeSeriesError(
            f"Derived chain has duplicate dates {dups[:5]} — "
            "v_contract_data_chained must return one row per session"
        )

    for col in _REQUIRED_DERIVED_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def compute_gauge_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Add the score + norm columns, using the engine's own implementations.

    Stage 2 (``compute_raw_scores``) and stage 3 (``rolling_zscore``) are
    imported, never reimplemented — identical values are the acceptance
    criterion for this job.
    """
    scored = compute_raw_scores(df, smoothing_window=GAUGE_SMOOTHING_WINDOW)
    result = scored.copy()
    for _, _, score_col, norm_col in GAUGE_SPECS:
        result[norm_col] = rolling_zscore(
            pd.Series(result[score_col]),
            window=GAUGE_NORM_WINDOW,
            outlier_cap=GAUGE_OUTLIER_CAP,
        )
    return result


def _as_float(value: object) -> float | None:
    """Coerce a cell to float, mapping NaN/None/non-numeric to None.

    NULL means "not computed" and must stay NULL — never 0.0, which is a valid
    z-score (.claude/rules/pipeline-continuity.md).
    """
    if value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def to_gauge_rows(frame: pd.DataFrame) -> list[dict]:
    """Flatten the wide frame into one row per (date, contract, indicator).

    Rows whose three stages are all NULL are dropped — that is the warm-up
    period before the 252-day window has enough history, not a data gap worth
    storing.
    """
    rows: list[dict] = []
    for record in frame.to_dict("records"):
        for indicator_name, raw_col, score_col, norm_col in GAUGE_SPECS:
            raw = _as_float(record.get(raw_col))
            score = _as_float(record.get(score_col))
            norm = _as_float(record.get(norm_col))
            if raw is None and score is None and norm is None:
                continue
            rows.append(
                {
                    "date": pd.Timestamp(record["date"]).date(),
                    "contract_id": str(record["contract_id"]),
                    "indicator_name": indicator_name,
                    "raw_value": raw,
                    "score_value": score,
                    "norm_value": norm,
                }
            )
    return rows


# Rows per statement. The full backfill is ~5 indicators × ~2700 sessions;
# chunking keeps the parameter count well under the driver limit.
_CHUNK_SIZE = 1000


def upsert_gauges(session: Session, rows: list[dict]) -> int:
    """Write gauge rows, returning how many were sent."""
    if not rows:
        logger.warning("No gauge rows to write")
        return 0

    written = 0
    for start in range(0, len(rows), _CHUNK_SIZE):
        chunk = rows[start : start + _CHUNK_SIZE]
        stmt = pg_insert(PlDashboardGauge).values(chunk)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_dashboard_gauge",
            set_={
                "raw_value": stmt.excluded.raw_value,
                "score_value": stmt.excluded.score_value,
                "norm_value": stmt.excluded.norm_value,
            },
        )
        session.execute(stmt)
        written += len(chunk)
    return written

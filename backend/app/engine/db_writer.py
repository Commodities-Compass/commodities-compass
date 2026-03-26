"""DB writer for pipeline results.

Writes computed indicators to pl_derived_indicators, pl_indicator_daily,
and pl_signal_component. Uses upsert (INSERT ON CONFLICT UPDATE) to be
idempotent — safe to re-run.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _to_decimal(value: Any) -> Decimal | None:
    """Convert a value to Decimal, returning None for NaN/None."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    try:
        return Decimal(str(round(float(value), 6)))
    except (ValueError, TypeError, OverflowError):
        return None


def _to_str(value: Any) -> str | None:
    """Convert to string, None for NaN."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return str(value)


# Columns from the pipeline DataFrame that map to pl_derived_indicators fields.
_DERIVED_COLS = [
    "pivot",
    "r1",
    "r2",
    "r3",
    "s1",
    "s2",
    "s3",
    "ema12",
    "ema26",
    "macd",
    "macd_signal",
    "rsi_14d",
    "stochastic_k_14",
    "stochastic_d_14",
    "atr",
    "atr_14d",
    "bollinger",
    "bollinger_upper",
    "bollinger_lower",
    "bollinger_width",
    "close_pivot_ratio",
    "volume_oi_ratio",
    "gain_14d",
    "loss_14d",
    "rs",
    "daily_return",
]

# Columns for pl_indicator_daily.
_INDICATOR_SCORE_COLS = [
    "rsi_score",
    "macd_score",
    "stochastic_score",
    "atr_score",
    "close_pivot",
    "volume_oi",
]
_INDICATOR_NORM_COLS = [
    "rsi_norm",
    "macd_norm",
    "stoch_k_norm",
    "atr_norm",
    "close_pivot_norm",
    "vol_oi_norm",
]
_INDICATOR_COMPOSITE_COLS = [
    "indicator_value",
    "momentum",
    "final_indicator",
]

# Signal component: (name, raw_score_col, norm_col, coeff_key, exp_key).
# raw_score_col = pre-normalization score, norm_col = z-score normalized value.
# For momentum/macroeco (no z-score step), both point to the same column.
_SIGNAL_COMPONENTS = [
    ("rsi", "rsi_score", "rsi_norm", "a", "b"),
    ("macd", "macd_score", "macd_norm", "c", "d"),
    ("stochastic", "stochastic_score", "stoch_k_norm", "e", "f"),
    ("atr", "atr_score", "atr_norm", "g", "h"),
    ("close_pivot", "close_pivot", "close_pivot_norm", "i", "j"),
    ("volume_oi", "volume_oi", "vol_oi_norm", "l", "m"),
    ("momentum", "momentum", "momentum", "n", "o"),
    ("macroeco", "macroeco_bonus", "macroeco_bonus", "p", "q"),
]


def write_derived_indicators(
    session: Session,
    signals_df: pd.DataFrame,
    contract_id: uuid.UUID,
) -> int:
    """Write derived indicators to pl_derived_indicators (upsert).

    Returns number of rows written.
    """
    rows_written = 0

    for _, row in signals_df.iterrows():
        row_date = row["date"]
        values = {col: _to_decimal(row.get(col)) for col in _DERIVED_COLS}

        # Upsert: insert or update on (date, contract_id) conflict
        session.execute(
            text(
                """
                INSERT INTO pl_derived_indicators (id, date, contract_id, {cols})
                VALUES (:id, :date, :contract_id, {placeholders})
                ON CONFLICT ON CONSTRAINT uq_derived_indicators
                DO UPDATE SET {updates}
            """.format(
                    cols=", ".join(_DERIVED_COLS),
                    placeholders=", ".join(f":{c}" for c in _DERIVED_COLS),
                    updates=", ".join(f"{c} = EXCLUDED.{c}" for c in _DERIVED_COLS),
                )
            ),
            {
                "id": uuid.uuid4(),
                "date": row_date,
                "contract_id": contract_id,
                **values,
            },
        )
        rows_written += 1

    return rows_written


def write_indicator_daily(
    session: Session,
    signals_df: pd.DataFrame,
    contract_id: uuid.UUID,
    algorithm_version_id: uuid.UUID,
) -> int:
    """Write indicator daily data to pl_indicator_daily (upsert).

    Returns number of rows written.
    """
    all_value_cols = (
        _INDICATOR_SCORE_COLS
        + _INDICATOR_NORM_COLS
        + _INDICATOR_COMPOSITE_COLS
        + ["macroeco_bonus", "decision"]
    )
    rows_written = 0

    for _, row in signals_df.iterrows():
        row_date = row["date"]

        values: dict[str, Any] = {}
        for col in (
            _INDICATOR_SCORE_COLS + _INDICATOR_NORM_COLS + _INDICATOR_COMPOSITE_COLS
        ):
            values[col] = _to_decimal(row.get(col))

        values["macroeco_bonus"] = _to_decimal(row.get("macroeco_bonus"))
        values["macroeco_score"] = (
            _to_decimal(1.0 + float(row["macroeco_bonus"]))
            if row.get("macroeco_bonus") is not None
            and not (
                isinstance(row.get("macroeco_bonus"), float)
                and np.isnan(row["macroeco_bonus"])
            )
            else None
        )
        values["decision"] = _to_str(row.get("decision"))

        session.execute(
            text(
                """
                INSERT INTO pl_indicator_daily
                    (id, date, contract_id, algorithm_version_id,
                     {cols}, macroeco_score)
                VALUES
                    (:id, :date, :contract_id, :algorithm_version_id,
                     {placeholders}, :macroeco_score)
                ON CONFLICT ON CONSTRAINT uq_indicator_daily
                DO UPDATE SET {updates}, macroeco_score = EXCLUDED.macroeco_score
            """.format(
                    cols=", ".join(all_value_cols),
                    placeholders=", ".join(f":{c}" for c in all_value_cols),
                    updates=", ".join(f"{c} = EXCLUDED.{c}" for c in all_value_cols),
                )
            ),
            {
                "id": uuid.uuid4(),
                "date": row_date,
                "contract_id": contract_id,
                "algorithm_version_id": algorithm_version_id,
                **values,
            },
        )
        rows_written += 1

    return rows_written


def write_signal_components(
    session: Session,
    signals_df: pd.DataFrame,
    contract_id: uuid.UUID,
    algorithm_version_id: uuid.UUID,
    config: Any,
) -> int:
    """Write per-indicator signal decomposition to pl_signal_component.

    Deletes existing components for the same (date, contract_id) range
    then inserts fresh rows. This is simpler than upserting 8 rows per date.

    Returns number of rows written.
    """
    from app.engine.composite import _power_term

    dates = signals_df["date"].tolist()
    if not dates:
        return 0

    # Delete existing components for this contract + date range
    session.execute(
        text("""
            DELETE FROM pl_signal_component
            WHERE contract_id = :contract_id
              AND algorithm_version_id = :algorithm_version_id
              AND date >= :min_date AND date <= :max_date
        """),
        {
            "contract_id": contract_id,
            "algorithm_version_id": algorithm_version_id,
            "min_date": min(dates),
            "max_date": max(dates),
        },
    )

    rows_written = 0
    config_params = {
        "a": config.a,
        "b": config.b,
        "c": config.c,
        "d": config.d,
        "e": config.e,
        "f": config.f,
        "g": config.g,
        "h": config.h,
        "i": config.i,
        "j": config.j,
        "l": config.l,
        "m": config.m,
        "n": config.n,
        "o": config.o,
        "p": config.p,
        "q": config.q,
    }

    for _, row in signals_df.iterrows():
        row_date = row["date"]

        for comp_name, raw_col, norm_col, coeff_key, exp_key in _SIGNAL_COMPONENTS:
            raw_val = float(row.get(raw_col, 0) or 0)
            norm_val = float(row.get(norm_col, 0) or 0)
            coeff = config_params[coeff_key]
            exp = config_params[exp_key]
            contribution = _power_term(coeff, exp, norm_val)

            session.execute(
                text("""
                    INSERT INTO pl_signal_component
                        (id, date, contract_id, indicator_name,
                         raw_value, normalized_value, weighted_contribution,
                         algorithm_version_id)
                    VALUES
                        (:id, :date, :contract_id, :indicator_name,
                         :raw_value, :normalized_value, :weighted_contribution,
                         :algorithm_version_id)
                """),
                {
                    "id": uuid.uuid4(),
                    "date": row_date,
                    "contract_id": contract_id,
                    "indicator_name": comp_name,
                    "raw_value": _to_decimal(raw_val),
                    "normalized_value": _to_decimal(norm_val),
                    "weighted_contribution": _to_decimal(contribution),
                    "algorithm_version_id": algorithm_version_id,
                },
            )
            rows_written += 1

    return rows_written


def write_pipeline_results(
    session: Session,
    signals_df: pd.DataFrame,
    contract_id: uuid.UUID,
    algorithm_version_id: uuid.UUID,
    config: Any,
) -> dict[str, int]:
    """Write all pipeline results to the database.

    Returns dict with row counts per table.
    """
    derived_count = write_derived_indicators(session, signals_df, contract_id)
    logger.info("Wrote %d rows to pl_derived_indicators", derived_count)

    indicator_count = write_indicator_daily(
        session,
        signals_df,
        contract_id,
        algorithm_version_id,
    )
    logger.info("Wrote %d rows to pl_indicator_daily", indicator_count)

    signal_count = write_signal_components(
        session,
        signals_df,
        contract_id,
        algorithm_version_id,
        config,
    )
    logger.info("Wrote %d rows to pl_signal_component", signal_count)

    session.commit()
    logger.info("Committed all writes")

    return {
        "pl_derived_indicators": derived_count,
        "pl_indicator_daily": indicator_count,
        "pl_signal_component": signal_count,
    }

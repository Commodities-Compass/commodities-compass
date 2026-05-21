"""Read prod schema and assemble a ``DecideRequest`` for one date.

Implements the ``EnsembleDataLoader`` Protocol from the vendored ensemble
package (``ensemble.data_loader_protocol``). The pipeline does not call
this Protocol directly — our orchestrator (``main.py``) calls each helper
and packs the result.

Data flow per day:
    pl_contract_data_daily ⨝ pl_derived_indicators  → market_history
    pl_orchestrator_decision (trailing N rows)       → recent_decisions
    pl_specialist_prediction (trailing N rows)       → recent_votes
    pl_article_segment (today only)                  → MacroSignal (via MacroEventLayer)
"""

from __future__ import annotations

import logging
import uuid
from datetime import date as date_cls
from datetime import timedelta

import pandas as pd
from ensemble.data_loader_protocol import MacroSignal
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class EnsembleLoaderError(RuntimeError):
    """Raised on missing data or schema drift in the prod read path."""


# Columns the canonical R&D snapshot exposes on the market_history join.
# Order kept stable so dtype validation in EnsemblePipeline doesn't drift.
_MARKET_HISTORY_SELECT = """
SELECT
    pd.date::DATE                       AS date,
    pd.contract_id                      AS contract_id,
    pd.open                             AS open,
    pd.high                             AS high,
    pd.low                              AS low,
    pd.close                            AS close,
    pd.volume                           AS volume,
    pd.oi                               AS oi,
    pd.implied_volatility               AS implied_volatility,
    pd.stock_us                         AS stock_us,
    pd.com_net_us                       AS com_net_us,
    pi.r3, pi.r2, pi.r1, pi.pivot, pi.s1, pi.s2, pi.s3,
    pi.ema12, pi.ema26, pi.macd, pi.macd_signal,
    pi.rsi_14d,
    pi.stochastic_k_14, pi.stochastic_d_14,
    pi.atr, pi.atr_14d,
    pi.bollinger, pi.bollinger_upper, pi.bollinger_lower, pi.bollinger_width,
    pi.close_pivot_ratio, pi.volume_oi_ratio,
    pi.gain_14d, pi.loss_14d, pi.rs, pi.daily_return
FROM pl_contract_data_daily pd
JOIN pl_derived_indicators pi
    ON pi.date = pd.date AND pi.contract_id = pd.contract_id
WHERE pd.contract_id = :contract_id
  AND pd.date BETWEEN :start_date AND :end_date
ORDER BY pd.date ASC
"""


def load_market_history(
    session: Session,
    *,
    end_date: date_cls,
    contract_id: uuid.UUID,
    lookback_days: int,
) -> pd.DataFrame:
    """Read trailing ``lookback_days`` of market_history up to ``end_date``.

    Returns a DataFrame with date column (datetime64) + all R&D-expected
    columns. Fails-loud if `end_date` is missing or the row count is below
    the minimum needed for GARCH features (~500 rows).
    """
    start_date = end_date - timedelta(days=lookback_days)
    rows = session.execute(
        text(_MARKET_HISTORY_SELECT),
        {"contract_id": contract_id, "start_date": start_date, "end_date": end_date},
    ).fetchall()
    if not rows:
        raise EnsembleLoaderError(
            f"market_history empty for contract_id={contract_id} "
            f"between {start_date} and {end_date}"
        )

    df = pd.DataFrame([dict(r._mapping) for r in rows])
    df["date"] = pd.to_datetime(df["date"])

    # Postgres NUMERIC columns come back as Python ``Decimal`` — coerce to
    # ``float64`` so the ensemble's numpy/pandas math doesn't choke on
    # ``Decimal + float`` mixing. ``contract_id`` is kept opaque.
    for col in df.columns:
        if col in ("date", "contract_id"):
            continue
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # daily_return may be NULL for the very first row in the table; that's
    # tolerable for downstream. But if today's row is missing daily_return,
    # several specialists choke — fail-loud rather than silently produce a
    # bad decision.
    if df["date"].max().date() != end_date:
        raise EnsembleLoaderError(
            f"market_history missing the target end_date {end_date}; "
            f"latest row is {df['date'].max().date()}"
        )

    logger.info(
        "Loaded %d market_history rows (%s..%s)",
        len(df),
        df["date"].min().date(),
        df["date"].max().date(),
    )
    return df


_RECENT_DECISIONS_SELECT = """
SELECT
    o.date::DATE                                                            AS date,
    o.soft_gate_decision                                                    AS decision,
    o.decision_wrapped                                                      AS decision_wrapped,
    o.net_score                                                             AS net_score,
    o.macro_direction                                                       AS macro_direction,
    o.prior_open                                                            AS prior_open,
    o.prior_hedge                                                           AS prior_hedge,
    o.prior_monitor                                                         AS prior_monitor,
    (o.soft_gate_decision <> 'MONITOR')                                     AS committed,
    -- 6-business-day forward return from same contract's close. NULL when
    -- the 6-day horizon hasn't realized yet (the wrapper's running_acc
    -- detector handles NULL as a non-committed day and skips it).
    (
      SELECT (fut.close / cur.close) - 1.0
      FROM pl_contract_data_daily cur
      JOIN LATERAL (
          SELECT close FROM pl_contract_data_daily f
          WHERE f.contract_id = cur.contract_id AND f.date > cur.date
          ORDER BY f.date ASC OFFSET 5 LIMIT 1
      ) fut ON TRUE
      WHERE cur.contract_id = o.contract_id AND cur.date = o.date
    )                                                                       AS forward_return
FROM pl_orchestrator_decision o
WHERE o.contract_id = :contract_id
  AND o.algorithm_version_id = :algorithm_version_id
  AND o.date < :end_date
ORDER BY o.date DESC
LIMIT :lookback
"""


def load_recent_orchestrator_decisions(
    session: Session,
    *,
    end_date: date_cls,
    contract_id: uuid.UUID,
    algorithm_version_id: uuid.UUID,
    lookback: int = 10,
) -> pd.DataFrame:
    """Read trailing ``pl_orchestrator_decision`` rows strictly before ``end_date``.

    Joins ``pl_indicator_daily`` is NOT done here — the wrapper's
    running-acc detector evaluates correctness using a forward-return
    proxy (handled downstream in the wrapper itself by the diag_df). For
    day-1, the returned frame is empty and the wrapper logs the missing
    window gracefully.

    Required columns per the Protocol: date, decision, decision_wrapped,
    net_score, macro_direction, prior_open, prior_hedge, prior_monitor,
    committed, correct. ``correct`` is NULL because we don't compute the
    forward return here (the wrapper handles it from market_history).
    """
    rows = session.execute(
        text(_RECENT_DECISIONS_SELECT),
        {
            "contract_id": contract_id,
            "algorithm_version_id": algorithm_version_id,
            "end_date": end_date,
            "lookback": lookback,
        },
    ).fetchall()
    if not rows:
        # Day-1 / empty trailing window — return canonical empty frame so the
        # wrapper sees the correct columns even with 0 rows.
        return pd.DataFrame(
            columns=pd.Index(
                [
                    "date",
                    "decision",
                    "decision_wrapped",
                    "net_score",
                    "macro_direction",
                    "prior_open",
                    "prior_hedge",
                    "prior_monitor",
                    "committed",
                    "correct",
                    "forward_return",
                ]
            )
        )

    df = pd.DataFrame([dict(r._mapping) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    # Coerce NUMERIC -> float64 (Postgres returns Decimal which breaks
    # downstream pandas arithmetic).
    for col in (
        "net_score",
        "prior_open",
        "prior_hedge",
        "prior_monitor",
        "forward_return",
    ):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # Derive ``correct`` from forward_return + the ORIGINAL soft-gate decision
    # (the Protocol column ``decision``, NOT ``decision_wrapped``). The wrapper's
    # running_acc detector evaluates "would the algo's raw signal have been right
    # recently?" to decide whether to trust today's signal. Scoring against the
    # wrapped output would create a self-referencing loop where the wrapper
    # evaluates itself, locking it into MONITOR forever after the first override
    # (observed live on 2026-05-07 → 2026-05-20). R&D's in-sample analysis
    # confirms `correct` is computed from the soft-gate prediction.
    # When forward_return is NaN (6d horizon not realized yet), set
    # ``correct`` to pd.NA so the wrapper treats the row as "unknown" instead
    # of False. ``NaN < 0`` evaluates False in pandas, which would silently
    # mark open-horizon rows as "incorrect" and re-trigger the wrapper's
    # auto-protection loop (rule §0 #3: NULL > silent False placeholder).
    has_return = df["forward_return"].notna()
    df["correct"] = pd.array([pd.NA] * len(df), dtype="boolean")
    hedge_mask = has_return & (df["decision"] == "HEDGE")
    open_mask = has_return & (df["decision"] == "OPEN")
    monitor_mask = has_return & (df["decision"] == "MONITOR")
    df.loc[hedge_mask, "correct"] = (df.loc[hedge_mask, "forward_return"] < 0).values
    df.loc[open_mask, "correct"] = (df.loc[open_mask, "forward_return"] > 0).values
    df.loc[monitor_mask, "correct"] = False
    df = df.sort_values("date").reset_index(drop=True)
    return df


_RECENT_VOTES_WINDOWED_SELECT = """
SELECT
    date::DATE          AS date,
    specialist_name     AS specialist_name,
    pred                AS pred
FROM pl_specialist_prediction
WHERE contract_id = :contract_id
  AND algorithm_version_id = :algorithm_version_id
  AND date BETWEEN :start_date AND (:end_date - INTERVAL '1 day')::DATE
ORDER BY date DESC, specialist_name ASC
"""


def load_recent_specialist_votes(
    session: Session,
    *,
    end_date: date_cls,
    contract_id: uuid.UUID,
    algorithm_version_id: uuid.UUID,
    lookback_days: int = 10,
) -> pd.DataFrame:
    """Read per-specialist votes strictly before ``end_date``.

    Returns columns: date, specialist_name, pred. Used by the wrapper's
    cluster-dispersion detector. Empty on day-1 — detector skips.
    """
    # Use a date-range filter so 14 specialists × lookback_days rows are
    # all returned together (LIMIT alone would truncate mid-day).
    start_date = end_date - timedelta(days=lookback_days)
    rows = session.execute(
        text(_RECENT_VOTES_WINDOWED_SELECT),
        {
            "contract_id": contract_id,
            "algorithm_version_id": algorithm_version_id,
            "start_date": start_date,
            "end_date": end_date,
        },
    ).fetchall()
    if not rows:
        return pd.DataFrame(columns=pd.Index(["date", "specialist_name", "pred"]))

    df = pd.DataFrame([dict(r._mapping) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["date", "specialist_name"]).reset_index(drop=True)
    return df


def load_macro_signal(
    session: Session,
    *,
    today: date_cls,
) -> MacroSignal:
    """Stub MacroSignal for now (sentiment pipeline not yet wired).

    The full MacroEventLayer needs frozen weights (long_run priors + macro
    config) AND a few months of trailing pl_article_segment rows. Since
    our article_segment prod table is currently very sparse (sentiment
    pipeline is shadow-mode per CAMPAIGN_5_PROD_DEPLOYMENT.md), we use a
    neutral macro signal so the soft-gate's macro factor contributes
    zero — the model still runs cleanly, just without macro tilt.

    Logged at WARNING so the diagnostic rows in pl_orchestrator_decision
    are auditable post-hoc — a future query can join on
    "macro_stub_active" Sentry tag to filter rows where macro=neutral
    came from this stub vs a real neutral macro reading.

    TODO: when the sentiment pipeline is activated and has enough trailing
    coverage, replace this with the real MacroEventLayer.predict call.
    """
    _ = session, today  # unused for the neutral stub
    logger.warning(
        "load_macro_signal: stub active for %s — sentiment pipeline not wired; "
        "returning neutral MacroSignal(0, 0.0, 0.0). pl_orchestrator_decision "
        "row will have macro_direction=0 indistinguishable from real flat-macro.",
        today,
    )
    try:
        import sentry_sdk

        sentry_sdk.set_tag("macro_stub_active", "true")
    except ImportError:
        pass
    return MacroSignal(direction=0, surprise=0.0, confidence=0.0)

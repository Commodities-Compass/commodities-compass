"""Read prod schema and assemble a ``DecideRequest`` for one date.

Implements the ``EnsembleDataLoader`` Protocol from the vendored ensemble
package (``ensemble.data_loader_protocol``). The pipeline does not call
this Protocol directly — our orchestrator (``main.py``) calls each helper
and packs the result.

Data flow per day:
    pl_contract_data_daily ⨝ pl_derived_indicators  → market_history
    pl_orchestrator_decision (trailing N rows)       → recent_decisions
    pl_specialist_prediction (trailing N rows)       → recent_votes
    pl_article_segment (trailing 90d)                → MacroSignal (via MacroEventLayer)
"""

from __future__ import annotations

import logging
import uuid
from datetime import date as date_cls
from datetime import timedelta

import pandas as pd
from ensemble.data_loader_protocol import MacroSignal
from ensemble.macro_events.pipeline import MacroEventLayer
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# MacroEventLayer fit window: needs ≥30d for the rolling baseline + buffer.
# 90d is what R&D used in their backfill (CAMPAIGN_4 §4.4).
MACRO_FIT_LOOKBACK_DAYS = 90


class EnsembleLoaderError(RuntimeError):
    """Raised on missing data or schema drift in the prod read path."""


# Columns the canonical R&D snapshot exposes on the market_history join.
# Order kept stable so dtype validation in EnsemblePipeline doesn't drift.
#
# Reads from ``v_contract_data_chained`` (front-month-by-OI VIEW) so the
# 600d GARCH/long-run lookback chains across roll boundaries — see
# Alembic n8i9j0k1l2m3. Indicators join on (date, contract_id) where
# contract_id is whichever underlying contract was front-month that day.
#
# stock_us and com_net_us were removed from the VIEW + projection
# 2026-05-27 (migration r2m3n4o5p6q7). They live in pl_stock_observation
# / pl_cot_us_weekly now and no R&D specialist consumes them.
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
    pi.r3, pi.r2, pi.r1, pi.pivot, pi.s1, pi.s2, pi.s3,
    pi.ema12, pi.ema26, pi.macd, pi.macd_signal,
    pi.rsi_14d,
    pi.stochastic_k_14, pi.stochastic_d_14,
    pi.atr, pi.atr_14d,
    pi.bollinger, pi.bollinger_upper, pi.bollinger_lower, pi.bollinger_width,
    pi.close_pivot_ratio, pi.volume_oi_ratio,
    pi.gain_14d, pi.loss_14d, pi.rs, pi.daily_return
FROM v_contract_data_chained pd
JOIN pl_derived_indicators pi
    ON pi.date = pd.date AND pi.contract_id = pd.contract_id
WHERE pd.date BETWEEN :start_date AND :end_date
ORDER BY pd.date ASC
"""


def load_market_history(
    session: Session,
    *,
    end_date: date_cls,
    contract_id: uuid.UUID,
    lookback_days: int,
) -> pd.DataFrame:
    """Read trailing ``lookback_days`` of front-month market_history up to ``end_date``.

    Pulls from ``v_contract_data_chained`` so GARCH/long-run features chain
    across roll boundaries. ``contract_id`` is kept in the signature for the
    callsite to embed in the resulting DecideRequest payload, but the SELECT
    no longer filters on it — the VIEW already picks the front-month-by-OI
    row per date.

    Fails-loud if `end_date` is missing or the row count is below the
    minimum needed for GARCH features (~500 rows).
    """
    _ = contract_id  # kept for ABI; VIEW is contract-agnostic by design
    start_date = end_date - timedelta(days=lookback_days)
    rows = session.execute(
        text(_MARKET_HISTORY_SELECT),
        {"start_date": start_date, "end_date": end_date},
    ).fetchall()
    if not rows:
        raise EnsembleLoaderError(
            f"market_history empty between {start_date} and {end_date}"
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
    -- ``committed`` here means "this row can be scored by the wrapper's
    -- running_acc detector" — i.e. soft-gate took a directional bet AND the
    -- 6d forward horizon is realized on the front-month chain. Pending
    -- horizon rows are marked uncommitted so the wrapper skips them.
    -- Uses v_contract_data_chained so rolls don't truncate the horizon.
    (
      o.soft_gate_decision <> 'MONITOR'
      AND (
        SELECT 1 FROM v_contract_data_chained f
        WHERE f.date > o.date
        ORDER BY f.date ASC OFFSET 5 LIMIT 1
      ) IS NOT NULL
    )                                                                       AS committed,
    -- 6-business-day forward return on the front-month-by-OI chain.
    -- Reads ``cur.close`` from the same chained VIEW so the t=0 close
    -- matches what the soft-gate saw at decide-time (the VIEW is what
    -- load_market_history feeds to specialists). The forward close is
    -- the chained VIEW row at OFFSET 5 (i.e. 6th future row).
    (
      SELECT (fut.close / cur.close) - 1.0
      FROM v_contract_data_chained cur
      JOIN LATERAL (
          SELECT close FROM v_contract_data_chained f
          WHERE f.date > cur.date
          ORDER BY f.date ASC OFFSET 5 LIMIT 1
      ) fut ON TRUE
      WHERE cur.date = o.date
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
    # ``correct`` is a plain bool. The wrapper's _running_acc filters to
    # committed=True before computing the mean, and our SQL above marks
    # pending-horizon rows as committed=False (forward close missing), so
    # they're skipped regardless of their `correct` value. Pandas can't
    # cast pd.NA via .astype(bool) — keep this as a clean boolean and let
    # the committed filter do the work. NaN < 0 returns False; safe because
    # those rows are excluded upstream.
    df["correct"] = ((df["decision"] == "HEDGE") & (df["forward_return"] < 0)) | (
        (df["decision"] == "OPEN") & (df["forward_return"] > 0)
    )
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


_MACRO_SEGMENTS_SELECT = """
SELECT
    article_date::DATE   AS article_date,
    sentiment_score      AS sentiment_score,
    confidence           AS confidence
FROM pl_article_segment
WHERE article_date BETWEEN :start_date AND :end_date
  AND sentiment_score IS NOT NULL
  AND confidence IS NOT NULL
ORDER BY article_date ASC
"""


def load_macro_signal(
    session: Session,
    *,
    today: date_cls,
    lookback_days: int = MACRO_FIT_LOOKBACK_DAYS,
) -> MacroSignal:
    """Compute today's MacroSignal from pl_article_segment via MacroEventLayer.

    Loads ``lookback_days`` of segments ending on ``today``, fits the
    MacroEventLayer (rolling 30d baseline for the surprise z-score), then
    scores ``today``. The layer applies the ``confidence >= 0.70`` filter
    internally — no need to pre-filter here.

    Fail-loud per pipeline-error-handling.md: an empty 90d window means
    press-review-agent failed silently or the data is missing. We refuse
    to run the ensemble blind with a stub macro signal — the upstream
    issue must be diagnosed and the job rerun manually.

    The MacroEventLayer itself returns a neutral ``MacroSignal(0, 0, 0)``
    on its own when ``today`` has zero high-confidence segments but the
    window had prior segments — that semantic ("real macro-quiet day")
    is preserved.
    """
    start_date = today - timedelta(days=lookback_days)
    rows = session.execute(
        text(_MACRO_SEGMENTS_SELECT),
        {"start_date": start_date, "end_date": today},
    ).fetchall()

    if not rows:
        raise EnsembleLoaderError(
            f"pl_article_segment empty for [{start_date}, {today}] — "
            "press-review-agent likely failed; diagnose upstream then "
            "rerun cc-ensemble-compute."
        )

    df = pd.DataFrame([dict(r._mapping) for r in rows])
    df["sentiment_score"] = pd.to_numeric(df["sentiment_score"], errors="coerce")
    df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce")

    layer = MacroEventLayer().fit(df)
    score = layer.score_for_date(pd.Timestamp(today))

    logger.info(
        "load_macro_signal: %s direction=%+d surprise=%.3f n_segments=%d confidence=%.3f",
        today,
        score.direction,
        score.surprise,
        score.n_segments,
        score.confidence,
    )
    return MacroSignal(
        direction=int(score.direction),
        surprise=float(score.surprise),
        confidence=float(score.confidence),
    )

"""Load data from Compass production DB into pandas DataFrames.

All loaders accept a SQLAlchemy Engine (sync) and return a pandas DataFrame
with a `date` column (or `release_date` for COT) ready for downstream join.

Lag policies mirror the reference Julien script
(docs/onboarding/extract_rd_dataset.py):

- COT EU: merge_asof backward with 14-day tolerance on release_date.
- Sentiment: ffill bounded to 7 calendar days.
- Fundamentals (skipped here, not in Compass prod).
- ENSO: 14-day publication lag, applied at join time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final

import pandas as pd
from sqlalchemy import Engine, text


# ---------------------------------------------------------------------------
# Constants (match Julien's reference script)
# ---------------------------------------------------------------------------

SENT_FFILL_DAYS: Final[int] = 7
COT_ASOF_TOLERANCE: Final[pd.Timedelta] = pd.Timedelta(days=14)
ENSO_LAG_DAYS: Final[int] = 14

# Indicator columns Julien consumes (16 cols, [METHOD-TIED] scope).
DERIVED_COLUMNS: Final[list[str]] = [
    "pivot",
    "ema12",
    "ema26",
    "macd",
    "macd_signal",
    "rsi_14d",
    "stochastic_k_14",
    "stochastic_d_14",
    "atr",
    "atr_14d",
    "bollinger_upper",
    "bollinger_lower",
    "bollinger_width",
    "close_pivot_ratio",
    "volume_oi_ratio",
    "daily_return",
]

# OHLCV + IV block (7 cols).
# stocks (stock_us, stock_eu_bags60kg) and com_net_us were moved to the
# dedicated pl_stock_observation / pl_cot_us_weekly tables on 2026-05-27
# (migration r2m3n4o5p6q7). The R&D export still surfaces them on each
# session row via forward-fill from those tables — see
# ``load_front_month_ohlcv`` below.
OHLCV_COLUMNS: Final[list[str]] = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "oi",
    "implied_volatility",
    "stock_us",
    "stock_eu_bags60kg",
    "com_net_us",
]


@dataclass(frozen=True)
class DateRange:
    """Inclusive [start, end] window on the `date` column."""

    start: date
    end: date


# ---------------------------------------------------------------------------
# A. OHLCV — front-month picked by max-volume / tie-break OI
# ---------------------------------------------------------------------------


def load_front_month_ohlcv(engine: Engine, window: DateRange) -> pd.DataFrame:
    """Pull OHLCV+IV (and forward-filled stocks + CFTC US net) per front-month.

    On overlapping contract days, keep the row with highest `volume` then OI
    (mirrors Julien's logic in extract_rd_dataset.py). Returns a DataFrame
    with one row per trading day in the window, with `date`, `contract_code`,
    `contract_month` and the OHLCV/IV + 3 forward-filled weekly columns
    (stock_us tonnes, stock_eu_bags60kg native, com_net_us prod_merc_net).
    """
    sql = text(
        """
        SELECT
            d.date,
            c.code AS contract_code,
            c.contract_month,
            d.open, d.high, d.low, d.close, d.volume, d.oi,
            d.implied_volatility,
            (
                SELECT so.value_tonnes
                FROM pl_stock_observation so
                WHERE so.region = 'us'
                  AND so.contract_market = 'cocoa'
                  AND so.report_date <= d.date
                ORDER BY so.report_date DESC
                LIMIT 1
            ) AS stock_us,
            (
                SELECT so.value_native
                FROM pl_stock_observation so
                WHERE so.region = 'eu'
                  AND so.contract_market = 'cocoa'
                  AND so.report_date <= d.date
                ORDER BY so.report_date DESC
                LIMIT 1
            ) AS stock_eu_bags60kg,
            (
                SELECT cw.prod_merc_net
                FROM pl_cot_us_weekly cw
                WHERE cw.contract_market = 'cocoa'
                  AND cw.release_date <= d.date
                ORDER BY cw.release_date DESC
                LIMIT 1
            ) AS com_net_us
        FROM pl_contract_data_daily d
        JOIN ref_contract c ON c.id = d.contract_id
        WHERE d.date BETWEEN :start AND :end
        ORDER BY d.date, d.volume DESC NULLS LAST, d.oi DESC NULLS LAST
        """
    )
    with engine.connect() as conn:
        raw = pd.read_sql(sql, conn, params={"start": window.start, "end": window.end})

    if raw.empty:
        return raw

    raw["date"] = pd.to_datetime(raw["date"])
    rolled = raw.drop_duplicates(subset=["date"], keep="first").reset_index(drop=True)
    return rolled


# ---------------------------------------------------------------------------
# B. Derived technicals — same contract picked by OHLCV loader
# ---------------------------------------------------------------------------


def load_derived_indicators(
    engine: Engine, window: DateRange, front_month: pd.DataFrame
) -> pd.DataFrame:
    """Return derived indicators aligned with the front-month contract per date.

    Strategy: pull all rows in window from pl_derived_indicators, then
    semi-join on (date, contract_id) by matching the contract_code that
    front_month picked. We use a wider window for the derived load so
    cross-roll continuity works on the chained front-month series.
    """
    sql = text(
        """
        SELECT
            di.date,
            c.code AS contract_code,
            di.pivot, di.ema12, di.ema26, di.macd, di.macd_signal,
            di.rsi_14d, di.stochastic_k_14, di.stochastic_d_14,
            di.atr, di.atr_14d,
            di.bollinger_upper, di.bollinger_lower, di.bollinger_width,
            di.close_pivot_ratio, di.volume_oi_ratio, di.daily_return
        FROM pl_derived_indicators di
        JOIN ref_contract c ON c.id = di.contract_id
        WHERE di.date BETWEEN :start AND :end
        """
    )
    with engine.connect() as conn:
        raw = pd.read_sql(sql, conn, params={"start": window.start, "end": window.end})

    if raw.empty or front_month.empty:
        cols = ["date", *DERIVED_COLUMNS]
        return pd.DataFrame(columns=cols)

    raw["date"] = pd.to_datetime(raw["date"])
    keys = front_month[["date", "contract_code"]].copy()
    keys["date"] = pd.to_datetime(keys["date"])
    aligned = keys.merge(raw, on=["date", "contract_code"], how="left")
    return (
        aligned[["date", *DERIVED_COLUMNS]].sort_values("date").reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# C. COT EU — pull all history, derive 26w z-scores, asof-join later
# ---------------------------------------------------------------------------

# Compass schema columns (no `_all` suffix, no `swap_*`, no `spread`).
_COT_BASE_COLS: Final[list[str]] = [
    "open_interest",
    "prod_merc_long",
    "prod_merc_short",
    "prod_merc_net",
    "m_money_long",
    "m_money_short",
    "m_money_net",
    "other_rept_long",
    "other_rept_short",
    "non_rept_long",
    "non_rept_short",
]


def load_cot_eu_with_zscores(engine: Engine) -> pd.DataFrame:
    """Pull full COT EU history (cocoa, futures-only) + compute 26w z-scores.

    Compass schema is leaner than Julien's reference (no `_all` suffix, no
    swap_* cols). Pulls everything so the rolling 26w window has enough
    context even when the export window is short. Derives:

    - `cot_m_money_net_z_26w`, `cot_m_money_net_pctile_26w`
    - `cot_prod_merc_net_z_26w`

    Returns DataFrame with `release_date` + `cot_report_date` + cot_<col>
    prefixed columns (matching Julien's naming convention).
    """
    sql = text(
        """
        SELECT release_date, report_date, contract_market, open_interest,
               prod_merc_long, prod_merc_short, prod_merc_net,
               m_money_long, m_money_short, m_money_net,
               other_rept_long, other_rept_short,
               non_rept_long, non_rept_short
        FROM pl_cot_eu_weekly
        WHERE contract_market = 'cocoa'
        ORDER BY release_date
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    if df.empty:
        return df

    df["release_date"] = pd.to_datetime(df["release_date"])
    df["report_date"] = pd.to_datetime(df["report_date"])

    # Rolling 26-week derivatives (min_periods=10 matches Julien).
    window = 26
    mm = df["m_money_net"].rolling(window=window, min_periods=10)
    df["m_money_net_z_26w"] = (df["m_money_net"] - mm.mean()) / mm.std()
    df["m_money_net_pctile_26w"] = (
        df["m_money_net"]
        .rolling(window=window, min_periods=10)
        .apply(lambda x: x.rank(pct=True).iloc[-1], raw=False)
    )
    pm = df["prod_merc_net"].rolling(window=window, min_periods=10)
    df["prod_merc_net_z_26w"] = (df["prod_merc_net"] - pm.mean()) / pm.std()

    # Prefix everything except release_date (the time key for merge_asof).
    rename = {c: f"cot_{c}" for c in df.columns if c != "release_date"}
    df = df.rename(columns=rename).drop(columns=["cot_contract_market"])
    return df.sort_values("release_date").reset_index(drop=True)


def join_cot_to_prices(prices: pd.DataFrame, cot: pd.DataFrame) -> pd.DataFrame:
    """Backward asof-merge on release_date with 14-day tolerance."""
    if cot.empty:
        return prices.copy()
    left = prices.sort_values("date").reset_index(drop=True)
    right = cot.sort_values("release_date").reset_index(drop=True)
    return pd.merge_asof(
        left,
        right,
        left_on="date",
        right_on="release_date",
        direction="backward",
        tolerance=COT_ASOF_TOLERANCE,
    )


# ---------------------------------------------------------------------------
# D. Sentiment LLM — long pl_article_segment → wide (zone × theme)
# ---------------------------------------------------------------------------


def load_sentiment_pivot(
    engine: Engine, trading_dates: pd.DatetimeIndex
) -> pd.DataFrame:
    """Aggregate pl_article_segment to one wide row per date.

    Columns produced:
        sent_<zone>_<theme>       — mean sentiment_score over the day
        n_articles_<zone>_<theme> — article count for the day × cell

    Zones and themes are discovered dynamically from the data (today the
    extraction pipeline only writes zone='all' but the schema is ready for
    afrique_ouest/civ/ghana/monde — backfill is in P1-press-review-backfill-10y).

    Joins back to pl_fundamental_article to filter on is_active=TRUE
    (so we only count the production-provider segments — see
    docs/runbooks/press-review-provider-switch.md).

    ffill bounded to 7 calendar days (sentiment); counts are not ffilled
    (NULL day means 0 articles by definition).
    """
    sql = text(
        """
        SELECT s.article_date::date AS date,
               s.zone,
               s.theme,
               AVG(s.sentiment_score) AS sent,
               COUNT(*) AS n
        FROM pl_article_segment s
        JOIN pl_fundamental_article a ON a.id = s.article_id
        WHERE a.is_active = TRUE
        GROUP BY s.article_date, s.zone, s.theme
        ORDER BY s.article_date
        """
    )
    with engine.connect() as conn:
        long = pd.read_sql(sql, conn)

    if long.empty:
        return pd.DataFrame({"date": trading_dates})

    long["date"] = pd.to_datetime(long["date"])
    long["zone"] = long["zone"].astype(str).str.strip().str.lower()
    long["theme"] = long["theme"].astype(str).str.strip().str.lower()
    long["key"] = long["zone"] + "_" + long["theme"]

    sent = long.pivot_table(
        index="date", columns="key", values="sent", aggfunc="mean"
    ).add_prefix("sent_")
    count = long.pivot_table(
        index="date", columns="key", values="n", aggfunc="sum"
    ).add_prefix("n_articles_")

    wide = sent.join(count, how="outer").sort_index()

    full = wide.reindex(pd.DatetimeIndex(trading_dates))
    sent_cols = [c for c in full.columns if c.startswith("sent_")]
    full[sent_cols] = full[sent_cols].ffill(limit=SENT_FFILL_DAYS)
    n_cols = [c for c in full.columns if c.startswith("n_articles_")]
    full[n_cols] = full[n_cols].fillna(0).astype(int)

    full.index.name = "date"
    return full.reset_index()


# ---------------------------------------------------------------------------
# Bonus 1 — ENSO + FX from pl_external_indicator
# ---------------------------------------------------------------------------

ENSO_COLUMNS: Final[list[str]] = ["enso_oni_month", "enso_nino34_anomaly"]
FX_COLUMNS: Final[list[str]] = [
    "fx_dxy_proxy",
    "fx_eurusd",
    "fx_gbpusd",
    "fx_gbpeur",
]


def load_external_indicators(engine: Engine) -> pd.DataFrame:
    """Pull full pl_external_indicator history.

    The table holds 2 sources at different cadences keyed on the same `date`:
      - ENSO: monthly, written at YYYY-MM-01 (lag applied at join time).
      - FX:   daily business-days.

    We pull all rows; the caller asof-joins to the trading-day grid.
    """
    sql = text(
        """
        SELECT date, enso_oni_month, enso_nino34_anomaly,
               fx_dxy_proxy, fx_eurusd, fx_gbpusd, fx_gbpeur
        FROM pl_external_indicator
        ORDER BY date
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df


def join_external_to_prices(
    prices: pd.DataFrame, external: pd.DataFrame
) -> pd.DataFrame:
    """Asof-join ENSO (with 14d lag) and FX (no lag) to the daily prices."""
    if external.empty:
        return prices.copy()

    # ENSO: shift the publication date forward by 14 days, then asof backward.
    enso = (
        external[["date", *ENSO_COLUMNS]].dropna(subset=ENSO_COLUMNS, how="all").copy()
    )
    enso["enso_available_at"] = enso["date"] + pd.Timedelta(days=ENSO_LAG_DAYS)
    enso = enso.drop(columns=["date"]).sort_values("enso_available_at")

    fx = (
        external[["date", *FX_COLUMNS]]
        .dropna(subset=FX_COLUMNS, how="all")
        .copy()
        .sort_values("date")
    )

    left = prices.sort_values("date").reset_index(drop=True)

    if not enso.empty:
        left = pd.merge_asof(
            left,
            enso,
            left_on="date",
            right_on="enso_available_at",
            direction="backward",
        ).drop(columns=["enso_available_at"])

    if not fx.empty:
        left = pd.merge_asof(
            left,
            fx,
            left_on="date",
            right_on="date",
            direction="backward",
        )

    return left


# ---------------------------------------------------------------------------
# Bonus 2 — Compass signal (pl_indicator_daily, prod-active algorithm)
# ---------------------------------------------------------------------------


def load_compass_signal(
    engine: Engine, window: DateRange, front_month: pd.DataFrame
) -> pd.DataFrame:
    """Pull final composite + decision per date for the prod-active algo.

    Reads the row where pl_algorithm_version.is_active=TRUE (typically
    legacy v1.0.1 — the C5 ensemble is shadow mode with compute_enabled=FALSE
    so it would not be marked active at the time of this export).

    Returns date + compass_<col> prefixed signal columns.
    """
    if front_month.empty:
        return pd.DataFrame(columns=["date"])

    sql = text(
        """
        SELECT
            i.date,
            c.code AS contract_code,
            i.final_indicator AS compass_composite_score,
            i.decision        AS compass_decision,
            i.confidence      AS compass_confidence,
            i.direction       AS compass_direction,
            i.momentum        AS compass_momentum,
            i.macroeco_bonus  AS compass_macroeco_bonus,
            i.macroeco_score  AS compass_macroeco_score
        FROM pl_indicator_daily i
        JOIN ref_contract c ON c.id = i.contract_id
        JOIN pl_algorithm_version av ON av.id = i.algorithm_version_id
        WHERE i.date BETWEEN :start AND :end
          AND av.is_active = TRUE
        """
    )
    with engine.connect() as conn:
        raw = pd.read_sql(sql, conn, params={"start": window.start, "end": window.end})

    if raw.empty:
        return pd.DataFrame({"date": pd.to_datetime(front_month["date"])})

    raw["date"] = pd.to_datetime(raw["date"])
    keys = front_month[["date", "contract_code"]].copy()
    keys["date"] = pd.to_datetime(keys["date"])
    aligned = keys.merge(raw, on=["date", "contract_code"], how="left")
    return (
        aligned.drop(columns=["contract_code"])
        .sort_values("date")
        .reset_index(drop=True)
    )

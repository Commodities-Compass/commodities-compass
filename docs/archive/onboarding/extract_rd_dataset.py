"""Build a single CSV extract for R&D on cocoa.

Combines, at daily front-month granularity (2016-01-04 -> latest):
  A. Raw OHLCV + IV + stocks (US, EU) + com_net_us   [pl_contract_data_daily]
  B. 14 derived technical indicators                  [pl_derived_indicators]
  C. LLM sentiment, wide by (zone x theme)            [pl_article_segment]
  D. Fundamentals (Tax + Achats + Grainage), monthly  [Db_Master_*.xlsx]
  E. COT EU cocoa (Disaggregated TFF, futures_only)   [pl_cot_eu_weekly]

Anti-look-ahead:
  - COT: joined on `release_date` (Friday) via merge_asof backward.
  - Fundamentals: monthly value M attributed to first business day of M+2
    (conservative ~30-day customs publication lag), then ffill within month.
  - Sentiment: ffill bounded to 7 calendar days; no stale-signal leak.

Reproducible: idempotent given the same DB state. Writes
  output/rd_extract/cocoa_rd_dataset_YYYYMMDD.csv
  output/rd_extract/cocoa_rd_dataset_YYYYMMDD.meta.json
  output/rd_extract/cocoa_rd_dataset_YYYYMMDD.dictionary.md

Usage:
    python -m scripts.extract_rd_dataset
    python -m scripts.extract_rd_dataset --no-recompute-indicators
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from scripts.db import get_daily_data, get_derived_indicators, query_df
from scripts.fundamental_data import (
    aggregate_achats_monthly,
    aggregate_tax_monthly,
    compute_grainage_anomaly,
    load_achats_data,
    load_grainage_data,
    load_tax_data,
)
from scripts.indicators import compute_all_indicators

_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
_OUT_DIR: Final[Path] = _ROOT / "output" / "rd_extract"

# Fundamentals: lag in months between observation and assumed availability.
# Customs declarations are aggregated monthly and published with ~30-day lag.
# M is attributed to first business day of M+_FUND_LAG_MONTHS.
_FUND_LAG_MONTHS: Final[int] = 2

# Sentiment: max forward-fill window in calendar days.
_SENT_FFILL_DAYS: Final[int] = 7

# COT: max staleness for merge_asof in days. Weekly cadence -> 14d covers gaps.
_COT_ASOF_TOLERANCE: Final[pd.Timedelta] = pd.Timedelta(days=14)


# ---------------------------------------------------------------------------
# Bloc A: raw OHLCV, front-month rolled
# ---------------------------------------------------------------------------

def load_front_month_ohlcv() -> pd.DataFrame:
    """Pull raw daily data and pick the front-month per date (max volume).

    On overlapping contract days (roll period), keep the row with highest
    `volume`; tie-break by `oi`. Result has exactly one row per trading day.
    """
    raw = get_daily_data("Cocoa").copy()
    raw["date"] = pd.to_datetime(raw["date"])
    # Sort so groupby().head(1) picks the most-liquid contract per date.
    raw = raw.sort_values(
        ["date", "volume", "oi"], ascending=[True, False, False]
    )
    rolled = raw.drop_duplicates(subset=["date"], keep="first").reset_index(drop=True)
    return rolled


# ---------------------------------------------------------------------------
# Bloc B: derived technicals
# ---------------------------------------------------------------------------

def _derived_columns() -> list[str]:
    return [
        "pivot", "ema12", "ema26", "macd", "macd_signal",
        "rsi_14d", "stochastic_k_14", "stochastic_d_14",
        "atr", "atr_14d", "bollinger_upper", "bollinger_lower",
        "bollinger_width", "close_pivot_ratio", "volume_oi_ratio",
        "daily_return",
    ]


def load_front_month_derived(
    df_price: pd.DataFrame, prefer_db: bool = True
) -> pd.DataFrame:
    """Return [date, <derived cols>] front-month aligned with df_price.

    If `prefer_db`, pull pre-computed values from pl_derived_indicators and
    recompute (via indicators.py) only the rows still missing. Otherwise
    recompute everything from the price series for full determinism.
    """
    derived_cols = _derived_columns()

    # Always compute from the price stream as the deterministic baseline.
    computed = compute_all_indicators(df_price).copy()
    keep_computed = [c for c in derived_cols if c in computed.columns]
    base = computed[["date"] + keep_computed].copy()

    if not prefer_db:
        return base

    db = get_derived_indicators("Cocoa").copy()
    db["date"] = pd.to_datetime(db["date"])
    # When duplicates exist (multi-contract), prefer the front-month contract
    # we already selected upstream.
    db = db.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    # Keep only columns present in both.
    overlap = [c for c in derived_cols if c in db.columns]
    db_slice = db[["date"] + overlap].copy()

    # Merge: DB values where present, computed fallback elsewhere.
    merged = base.merge(
        db_slice, on="date", how="left", suffixes=("_calc", "_db")
    )
    for col in overlap:
        calc_col, db_col = f"{col}_calc", f"{col}_db"
        if calc_col in merged.columns and db_col in merged.columns:
            merged[col] = merged[db_col].fillna(merged[calc_col])
            merged = merged.drop(columns=[calc_col, db_col])

    final_cols = ["date"] + [c for c in derived_cols if c in merged.columns]
    return merged[final_cols].sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Bloc C: sentiment LLM, wide pivot
# ---------------------------------------------------------------------------

def load_sentiment_pivot(trading_dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Aggregate pl_article_segment to one wide row per date.

    Columns produced:
      sent_<zone>_<theme>     -> mean sentiment_score over the day
      n_articles_<zone>_<theme> -> article count for the day x cell

    Forward-fill within _SENT_FFILL_DAYS calendar days; nulls beyond.
    Aligned to `trading_dates` (left-join).
    """
    sql = """
        SELECT article_date::date AS date,
               zone,
               theme,
               AVG(sentiment_score) AS sent,
               COUNT(*)             AS n
        FROM pl_article_segment
        WHERE sentiment_score IS NOT NULL
        GROUP BY article_date, zone, theme
        ORDER BY article_date
    """
    long = query_df(sql)
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

    # Reindex to the full trading calendar then ffill bounded.
    full = wide.reindex(pd.DatetimeIndex(trading_dates))
    sent_cols = [c for c in full.columns if c.startswith("sent_")]
    full[sent_cols] = full[sent_cols].ffill(limit=_SENT_FFILL_DAYS)
    # n_articles: counts shouldn't be ffilled; an absent day means 0 articles.
    n_cols = [c for c in full.columns if c.startswith("n_articles_")]
    full[n_cols] = full[n_cols].fillna(0).astype(int)

    full.index.name = "date"
    return full.reset_index()


# ---------------------------------------------------------------------------
# Bloc D: fundamentals (Tax + Achats + Grainage), daily ffill with lag
# ---------------------------------------------------------------------------

def _first_business_day(year: int, month: int) -> pd.Timestamp:
    """First business day of the given (year, month)."""
    return pd.Timestamp(year, month, 1) + pd.offsets.BusinessDay(0)


def _attribute_monthly_to_daily(
    monthly: pd.DataFrame,
    trading_dates: pd.DatetimeIndex,
    lag_months: int,
) -> pd.DataFrame:
    """Spread monthly fundamentals to a daily index with a publication lag.

    Value of month M -> first business day of (M + lag_months), then
    ffill until the next reported month appears.
    """
    if monthly.empty:
        return pd.DataFrame({"date": trading_dates})

    monthly = monthly.sort_values(["year", "month"]).copy()

    def _avail(row: pd.Series) -> pd.Timestamp:
        y, m = int(row["year"]), int(row["month"])
        # Add lag_months to (y, m).
        total = m + lag_months
        ny = y + (total - 1) // 12
        nm = ((total - 1) % 12) + 1
        return _first_business_day(ny, nm)

    monthly["available_at"] = monthly.apply(_avail, axis=1)
    monthly = monthly.drop(columns=["year", "month"]).set_index("available_at").sort_index()

    # Reindex on trading dates and ffill.
    daily = monthly.reindex(monthly.index.union(trading_dates)).sort_index()
    daily = daily.ffill()
    daily = daily.loc[daily.index.isin(trading_dates)]
    daily.index.name = "date"
    return daily.reset_index()


def load_fundamentals_daily(trading_dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Load Tax + Achats + Grainage monthly aggregates and propagate to daily."""
    tax_raw = load_tax_data()
    tax_m = aggregate_tax_monthly(tax_raw)
    # Strip noisy raw volume columns; keep informative aggregates.
    drop_cols = {"feves_volume_kg", "processed_volume_kg", "abj_volume_kg"}
    tax_m = tax_m[[c for c in tax_m.columns if c not in drop_cols]]

    achats_raw = load_achats_data()
    achats_m = aggregate_achats_monthly(achats_raw)

    grainage_raw = load_grainage_data()
    grainage_anom = compute_grainage_anomaly(grainage_raw)
    grain_m = grainage_anom[
        ["year", "month", "avg_bean_count", "grainage_anomaly"]
    ].drop_duplicates(subset=["year", "month"])

    # Outer-merge the three monthly sources on (year, month).
    merged = tax_m.merge(achats_m, on=["year", "month"], how="outer") \
                  .merge(grain_m, on=["year", "month"], how="outer")
    merged = merged.sort_values(["year", "month"]).reset_index(drop=True)

    return _attribute_monthly_to_daily(merged, trading_dates, _FUND_LAG_MONTHS)


# ---------------------------------------------------------------------------
# Bloc E: COT EU cocoa, merge_asof on release_date
# ---------------------------------------------------------------------------

_COT_RAW_COLS: Final[list[str]] = [
    "open_interest_all",
    "m_money_long_all", "m_money_short_all", "m_money_spread_all",
    "prod_merc_long_all", "prod_merc_short_all",
    "swap_long_all", "swap_short_all", "swap_spread_all",
    "other_rept_long_all", "other_rept_short_all", "other_rept_spread_all",
    "nonrept_long_all", "nonrept_short_all",
    # tot_rept_long_all / tot_rept_short_all excluded: CFTC does not
    # publish these for ICE Europe markets (always NULL).
]


def load_cot_eu_cocoa() -> pd.DataFrame:
    """Pull weekly COT for cocoa futures_only, plus 26-week derived features.

    Returns columns named with `cot_` prefix; uses release_date as the
    look-ahead-safe time key.
    """
    cols_sql = ", ".join(["as_of_date", "release_date"] + _COT_RAW_COLS)
    sql = f"""
        SELECT {cols_sql}
        FROM pl_cot_eu_weekly
        WHERE market_code = 'cocoa' AND variant = 'futures_only'
        ORDER BY release_date
    """
    df = query_df(sql)
    if df.empty:
        return df

    df["as_of_date"] = pd.to_datetime(df["as_of_date"])
    df["release_date"] = pd.to_datetime(df["release_date"])

    # Derived: net positioning per category.
    df["m_money_net"] = df["m_money_long_all"] - df["m_money_short_all"]
    df["prod_merc_net"] = df["prod_merc_long_all"] - df["prod_merc_short_all"]
    df["swap_net"] = df["swap_long_all"] - df["swap_short_all"]

    # 26-week rolling z-score & percentile for managed money net (speculative flow).
    window = 26
    rolling = df["m_money_net"].rolling(window=window, min_periods=10)
    df["m_money_net_z_26w"] = (df["m_money_net"] - rolling.mean()) / rolling.std()
    df["m_money_net_pctile_26w"] = (
        df["m_money_net"].rolling(window=window, min_periods=10)
        .apply(lambda x: (x.rank(pct=True).iloc[-1]), raw=False)
    )
    # Commercials net z-score for hedger flow.
    rolling_pm = df["prod_merc_net"].rolling(window=window, min_periods=10)
    df["prod_merc_net_z_26w"] = (
        (df["prod_merc_net"] - rolling_pm.mean()) / rolling_pm.std()
    )

    # Prefix all columns except the time key used in merge_asof.
    rename = {c: f"cot_{c}" for c in df.columns if c != "release_date"}
    df = df.rename(columns=rename)
    return df.sort_values("release_date").reset_index(drop=True)


def join_cot_to_prices(
    df_price: pd.DataFrame, df_cot: pd.DataFrame
) -> pd.DataFrame:
    """Backward asof-merge: each price date sees the latest COT released <= date."""
    if df_cot.empty:
        return df_price.copy()

    left = df_price.sort_values("date").reset_index(drop=True)
    right = df_cot.sort_values("release_date").reset_index(drop=True)
    merged = pd.merge_asof(
        left, right,
        left_on="date", right_on="release_date",
        direction="backward", tolerance=_COT_ASOF_TOLERANCE,
    )
    return merged


# ---------------------------------------------------------------------------
# Validation & output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationReport:
    n_rows: int
    n_cols: int
    date_min: str
    date_max: str
    null_pct: dict[str, float]
    sha256: str


def validate(df: pd.DataFrame) -> None:
    """Hard-stop checks on the assembled dataset."""
    assert not df.empty, "empty dataset"
    assert df["date"].is_monotonic_increasing, "date not monotonically increasing"
    assert df["date"].is_unique, "duplicate dates"
    assert df["date"].min() <= pd.Timestamp("2016-02-01"), "history starts too late"

    # `close` is the canonical price; null gate is strict.
    # `high`/`low`/`volume` are also strict. `open` has known live-feed gaps
    # (~15% post 2024-09 ingestion) — accepted with a warning, not a hard fail.
    strict = {"close": 1.0, "high": 2.0, "low": 2.0, "volume": 2.0}
    null_pct = df.isna().mean() * 100
    for col, gate in strict.items():
        pct = null_pct.get(col, 0.0)
        assert pct <= gate, f"{col} null% = {pct:.2f}, exceeds {gate}% gate"
    open_pct = null_pct.get("open", 0.0)
    if open_pct > 2.0:
        print(f"warning: open null% = {open_pct:.2f} (known live-feed gap)")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _column_source(name: str) -> tuple[str, str]:
    """Return (source, scope_tag) for a column name."""
    if name in {"date", "contract_code", "contract_month"}:
        return ("key", "[ABSOLUTE]")
    if name.startswith("cot_"):
        return ("pl_cot_eu_weekly", "[ABSOLUTE]")
    if name.startswith("sent_") or name.startswith("n_articles_"):
        return ("pl_article_segment", "[METHOD-TIED]")
    if name in _derived_columns():
        return ("pl_derived_indicators / indicators.py", "[METHOD-TIED]")
    fund_keys = {
        "total_volume_kg", "n_transactions", "feves_share", "processing_ratio",
        "dest_hhi", "mean_caf_per_kg", "port_abj_share",
        "total_procurement_kg", "n_exporters", "procurement_hhi",
        "top3_exporter_share", "avg_bean_count", "grainage_anomaly",
    }
    if name in fund_keys or name.startswith("vol_"):
        return ("Db_Master_Tax + Db_Master_Achats + Bilan Grainage", "[ABSOLUTE]")
    return ("pl_contract_data_daily", "[ABSOLUTE]")


def write_outputs(df: pd.DataFrame, out_dir: Path, run_date: date) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = run_date.strftime("%Y%m%d")
    csv_path = out_dir / f"cocoa_rd_dataset_{stamp}.csv"
    meta_path = out_dir / f"cocoa_rd_dataset_{stamp}.meta.json"
    dict_path = out_dir / f"cocoa_rd_dataset_{stamp}.dictionary.md"

    df.to_csv(csv_path, index=False, date_format="%Y-%m-%d")
    sha = _sha256(csv_path)

    null_pct = (df.isna().mean() * 100).round(2).to_dict()
    meta = {
        "dataset": "cocoa_rd_dataset",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_date": stamp,
        "rows": int(len(df)),
        "cols": int(df.shape[1]),
        "date_min": str(df["date"].min().date()),
        "date_max": str(df["date"].max().date()),
        "sha256": sha,
        "sources": {
            "A_raw_ohlcv": "pl_contract_data_daily (front-month, max volume)",
            "B_derived_technicals": "pl_derived_indicators + indicators.py fallback",
            "C_sentiment": "pl_article_segment (wide pivot by zone x theme)",
            "D_fundamentals": (
                "Db_Master_Tax.xlsx + Db_Master_Achats.xlsx + Bilan Grainage; "
                f"monthly -> daily with publication lag = {_FUND_LAG_MONTHS} months"
            ),
            "E_cot_eu": (
                "pl_cot_eu_weekly (market=cocoa, variant=futures_only); "
                "joined on release_date via merge_asof backward (no look-ahead)"
            ),
        },
        "lag_policy": {
            "fundamentals_months": _FUND_LAG_MONTHS,
            "sentiment_ffill_days": _SENT_FFILL_DAYS,
            "cot_asof_tolerance_days": _COT_ASOF_TOLERANCE.days,
        },
        "null_pct": null_pct,
    }
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True))

    lines = ["# Cocoa R&D dataset — column dictionary", "",
             f"Generated: {meta['generated_at_utc']}",
             f"Rows: {meta['rows']} | Cols: {meta['cols']}",
             f"Date range: {meta['date_min']} -> {meta['date_max']}",
             f"SHA-256: `{sha}`", "",
             "| Column | Source | Scope | Null % |",
             "|--------|--------|-------|--------|"]
    for col in df.columns:
        src, scope = _column_source(col)
        lines.append(
            f"| `{col}` | {src} | {scope} | {null_pct.get(col, 0.0):.2f} |"
        )
    dict_path.write_text("\n".join(lines) + "\n")

    return csv_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_dataset(prefer_db_indicators: bool = True) -> pd.DataFrame:
    df_price = load_front_month_ohlcv()

    # Drop columns we don't need in the final extract.
    price_drop = {"id", "contract_id"}
    df_price = df_price[[c for c in df_price.columns if c not in price_drop]]

    trading_dates = pd.DatetimeIndex(df_price["date"].unique()).sort_values()

    df_tech = load_front_month_derived(df_price, prefer_db=prefer_db_indicators)
    df_sent = load_sentiment_pivot(trading_dates)
    df_fund = load_fundamentals_daily(trading_dates)
    df_cot = load_cot_eu_cocoa()

    # Order: keys -> raw OHLCV -> derived -> COT -> sentiment -> fundamentals.
    df = df_price.merge(df_tech, on="date", how="left", validate="one_to_one")
    df = join_cot_to_prices(df, df_cot)
    df = df.merge(df_sent, on="date", how="left", validate="one_to_one")
    df = df.merge(df_fund, on="date", how="left", validate="one_to_one")

    # Final column order.
    key_cols = ["date", "contract_code", "contract_month"]
    a_cols = [
        "open", "high", "low", "close", "volume", "oi",
        "implied_volatility", "stock_us", "stock_eu_bags60kg", "com_net_us",
    ]
    b_cols = _derived_columns()
    e_cols = [c for c in df.columns if c.startswith("cot_") or c == "release_date"]
    c_cols = [c for c in df.columns if c.startswith("sent_") or c.startswith("n_articles_")]
    used = set(key_cols + a_cols + b_cols + e_cols + c_cols)
    d_cols = [c for c in df.columns if c not in used and c != "date"]

    ordered = key_cols + a_cols + [c for c in b_cols if c in df.columns] \
              + e_cols + c_cols + d_cols
    ordered = [c for c in ordered if c in df.columns]
    return df[ordered].sort_values("date").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-recompute-indicators",
        action="store_true",
        help="Trust DB-pre-computed indicators only; skip indicators.py fallback.",
    )
    parser.add_argument(
        "--run-date",
        default=None,
        help="Stamp the output filename (YYYY-MM-DD). Defaults to today UTC.",
    )
    args = parser.parse_args()

    run_date = (
        date.fromisoformat(args.run_date)
        if args.run_date
        else datetime.now(timezone.utc).date()
    )

    df = build_dataset(prefer_db_indicators=not args.no_recompute_indicators)
    validate(df)

    csv_path = write_outputs(df, _OUT_DIR, run_date)
    null_top = (df.isna().mean() * 100).sort_values(ascending=False).head(10)
    print(f"Wrote {csv_path}")
    print(f"Shape: {df.shape}  range: {df['date'].min().date()} -> {df['date'].max().date()}")
    print("Top-10 columns by null %:")
    print(null_top.round(2).to_string())


if __name__ == "__main__":
    main()

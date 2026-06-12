"""RESEARCH (non-production, ZERO-COST) — can a realized-vol proxy stand in for IV to test the IV-crush signal
over the decade, without buying option data?

We own OHLCV back to 2016 (v_contract_data_chained). True option IV only exists since 2025-01-28. The IV-crush
finding (vol-high & mm_z>0 & iv_chg5<0 -> forward J+4 flips +) needs a multi-year sample to validate. This script:

  1. FIDELITY CHECK (2025-26 overlap, the only window with BOTH): does the sign of a realized-vol-proxy 5d change
     agree with the sign of the true iv_chg5? If agreement is high, the proxy is a usable (if lagging) stand-in.
  2. DECADE TEST (2016+): replace iv_chg5 with the proxy-crush and re-run the zone-A coherence test. Does
     "vol peaking & rolling over & shorts-covered" predict a reversal up (HEDGE loses) across 10 years?

Proxies (all causal, $0): EWMA vol (RiskMetrics lambda=0.94, IV-like persistence) and 10d realized vol.

Honest asymmetry: a POSITIVE decade result SUPPORTS the IV-crush thesis; a NEGATIVE one is INCONCLUSIVE (could be
proxy lag, not signal absence). Definitive validation still needs real IV (Databento 2018+, see IV_HISTORY_SOURCING.md).

Run: PYTHONPATH=. poetry run python scripts/research/zero_cost_ivproxy_coherence.py
"""

from __future__ import annotations

import psycopg2
import pandas as pd
import numpy as np

LOCAL_DSN = "host=localhost port=5433 dbname=commodities_compass user=postgres password=password"
VOL_PCTL = 0.80
EWMA_LAMBDA = 0.94


def fetch() -> tuple[pd.DataFrame, pd.DataFrame]:
    with psycopg2.connect(LOCAL_DSN) as con:
        px = pd.read_sql(
            "select date, contract_id, high, low, close, implied_volatility iv "
            "from v_contract_data_chained order by date",
            con,
        )
        cot = pd.read_sql(
            "select release_date, m_money_net from pl_cot_eu_weekly "
            "where contract_market='cocoa' order by release_date",
            con,
        )
    return px, cot


def build(px: pd.DataFrame, cot: pd.DataFrame) -> pd.DataFrame:
    df = px.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    c = df["close"].astype(float)
    df["logret"] = np.log(c / c.shift(1))

    # --- vol level (ATR%) + causal percentile ---
    h, lo, pc = df["high"].astype(float), df["low"].astype(float), c.shift(1)
    tr = pd.concat([(h - lo).abs(), (h - pc).abs(), (lo - pc).abs()], axis=1).max(
        axis=1
    )
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    df["atr_pct"] = df["atr"] / c
    df["vol_pctl"] = (
        df["atr_pct"]
        .rolling(252, min_periods=60)
        .apply(lambda s: (s.iloc[-1] >= s).mean())
    )

    # --- zero-cost IV proxies ---
    df["ewma_vol"] = np.sqrt(
        df["logret"]
        .pow(2)
        .ewm(alpha=1 - EWMA_LAMBDA, adjust=False, min_periods=20)
        .mean()
    )
    df["rv10"] = df["logret"].rolling(10, min_periods=10).std()
    df["proxy_chg5_ewma"] = df["ewma_vol"] - df["ewma_vol"].shift(5)
    df["proxy_chg5_rv10"] = df["rv10"] - df["rv10"].shift(5)
    df["iv_chg5"] = df.groupby("contract_id")["iv"].transform(lambda s: s - s.shift(5))

    # forward J+4 within contract
    df["fwd4"] = df.groupby("contract_id")["close"].shift(-4) / c - 1.0

    # COT mm z (26w) as-of
    cot = cot.copy()
    cot["release_date"] = pd.to_datetime(cot["release_date"])
    cot = cot.sort_values("release_date")
    cot["mm_z26"] = (
        cot["m_money_net"] - cot["m_money_net"].rolling(26, min_periods=8).mean()
    ) / cot["m_money_net"].rolling(26, min_periods=8).std()
    df = pd.merge_asof(
        df,
        cot[["release_date", "mm_z26"]],
        left_on="date",
        right_on="release_date",
        direction="backward",
    )
    return df


def fwd_stats(s: pd.Series) -> str:
    s = s.dropna()
    if not len(s):
        return "n=0"
    return f"n={len(s):3d}  meanfwd4={100 * s.mean():+.2f}%  HEDGE-win={100 * (s < 0).mean():.1f}%"


def main() -> None:
    px, cot = fetch()
    df = build(px, cot)

    print("=" * 90)
    print(
        "1) FIDELITY — does the proxy 5d-change sign agree with TRUE iv_chg5 sign? (2025+ overlap)"
    )
    print("=" * 90)
    ov = df[(df["date"] >= "2025-01-28")].dropna(
        subset=["iv_chg5", "proxy_chg5_ewma", "proxy_chg5_rv10"]
    )
    for p in ("proxy_chg5_ewma", "proxy_chg5_rv10"):
        agree = (np.sign(ov[p]) == np.sign(ov["iv_chg5"])).mean()
        corr = ov[p].corr(ov["iv_chg5"])
        print(
            f"  {p:18s}  sign-agreement={100 * agree:.1f}%   pearson_corr={corr:+.2f}   (n={len(ov)})"
        )
    print(
        "  (>~65% agreement => proxy is a usable lagging stand-in; ~50% => coin flip, proxy useless)"
    )

    print("\n" + "=" * 90)
    print(
        f"2) DECADE TEST (2016+) — zone A = vol_high(p{int(VOL_PCTL * 100)}) & mm_z>0, with/without proxy-crush"
    )
    print("=" * 90)
    d = df.dropna(subset=["vol_pctl", "mm_z26", "fwd4"]).copy()
    volh = d["vol_pctl"] > VOL_PCTL
    zoneA = volh & (d["mm_z26"] > 0)
    print(f"  zone A (no crush filter)        : {fwd_stats(d.loc[zoneA, 'fwd4'])}")
    for p in ("proxy_chg5_ewma", "proxy_chg5_rv10"):
        za_crush = zoneA & (d[p] < 0)
        za_nocrush = zoneA & (d[p] >= 0)
        print(f"  zone A & {p}<0 (crush) : {fwd_stats(d.loc[za_crush, 'fwd4'])}")
        print(f"  zone A & {p}>=0 (rising): {fwd_stats(d.loc[za_nocrush, 'fwd4'])}")
    print(
        "  TEST: does crush flip zone A forward-return POSITIVE (HEDGE-win<50%) like real IV did (+1.42%) in 2025-26?"
    )

    print("\n--- per-year: zone A & ewma-crush forward J+4 ---")
    dz = d[zoneA & (d["proxy_chg5_ewma"] < 0)].copy()
    dz["yr"] = dz["date"].dt.year
    ya = dz.groupby("yr")["fwd4"].agg(
        n="size",
        meanfwd4=lambda s: round(100 * s.mean(), 2),
        hedge_win=lambda s: round(100 * (s < 0).mean(), 1),
    )
    print(ya.to_string())

    print(
        "\n--- 2025-26 cross-check: real IV-crush vs ewma-proxy-crush on the SAME zone A ---"
    )
    d25 = d[d["date"] >= "2025-01-28"]
    za25 = (d25["vol_pctl"] > VOL_PCTL) & (d25["mm_z26"] > 0)
    print(
        f"  real iv_chg5<0    : {fwd_stats(d25.loc[za25 & (d25['iv_chg5'] < 0), 'fwd4'])}"
    )
    print(
        f"  ewma proxy <0     : {fwd_stats(d25.loc[za25 & (d25['proxy_chg5_ewma'] < 0), 'fwd4'])}"
    )


if __name__ == "__main__":
    main()

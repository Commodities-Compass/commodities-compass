"""RESEARCH (non-production) — decade-long coherence test of the wrapper conditioning formula.

The ensemble decisions only exist since Dec-2025, but the formula's INPUTS have a decade:
    v_contract_data_chained : continuous front-month OHLCV(+IV) 2016-2026
    pl_cot_eu_weekly        : COT EU managed-money 2014-2026
    (implied_volatility is only populated from 2025-01-28 -> IV-crush tested on the 2025-26 subset only)

Falsifiable thesis behind the HEDGE->MONITOR veto:
    A HEDGE (short bet) is dangerous when managed money is NOT positioned short
    (no downside fuel / shorts already covered). So, conditional on a HIGH-VOL regime:
        zone A (m_money_z > 0, "short fuel spent")  -> forward return should skew  POSITIVE  (HEDGE loses)
        zone B (m_money_z < 0, "crowded short")     -> forward return should skew  NEGATIVE  (HEDGE wins)
    If A and B separate over 10 years, the conditioning signal is real, not a May-2026 artifact.

Forward returns are computed WITHIN contract (groupby) so contract rolls don't contaminate them.

Run:  PYTHONPATH=. poetry run python scripts/research/historical_conditioning_coherence.py
"""

from __future__ import annotations

import psycopg2
import pandas as pd

LOCAL_DSN = "host=localhost port=5433 dbname=commodities_compass user=postgres password=password"
ATR_WIN = 14
VOL_PCTL = 0.80  # high-vol regime = atr_pct in top quintile of trailing 252d
H = 4  # primary forward horizon (matches ensemble J+4)


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


def wilder_atr(df: pd.DataFrame, win: int = ATR_WIN) -> pd.Series:
    h, lo, c = (
        df["high"].astype(float),
        df["low"].astype(float),
        df["close"].astype(float),
    )
    pc = c.shift(1)
    tr = pd.concat([(h - lo).abs(), (h - pc).abs(), (lo - pc).abs()], axis=1).max(
        axis=1
    )
    return tr.ewm(alpha=1.0 / win, adjust=False, min_periods=win).mean()


def build(px: pd.DataFrame, cot: pd.DataFrame) -> pd.DataFrame:
    df = px.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    df["atr"] = wilder_atr(df)
    df["atr_pct"] = df["atr"] / df["close"]
    # causal rolling percentile of atr_pct over trailing 252 sessions
    df["vol_pctl"] = (
        df["atr_pct"]
        .rolling(252, min_periods=60)
        .apply(lambda s: (s.iloc[-1] >= s).mean(), raw=False)
    )

    # forward returns WITHIN contract (rolls -> NaN at contract ends, dropped from stats)
    g = df.groupby("contract_id")["close"]
    df["fwd4"] = g.shift(-4) / df["close"] - 1.0
    df["fwd10"] = g.shift(-10) / df["close"] - 1.0
    df["iv_chg5"] = df.groupby("contract_id")["iv"].transform(lambda s: s - s.shift(5))

    # COT managed-money z (26 weekly) AS-OF release_date <= date
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


def stats(s: pd.Series) -> dict:
    s = s.dropna()
    return {
        "n": len(s),
        "mean%": round(100 * s.mean(), 2) if len(s) else float("nan"),
        "median%": round(100 * s.median(), 2) if len(s) else float("nan"),
        "pos%": round(100 * (s > 0).mean(), 1) if len(s) else float("nan"),
        "hedge_win%": round(100 * (s < 0).mean(), 1) if len(s) else float("nan"),
    }


def main() -> None:
    pd.set_option("display.width", 220)
    px, cot = fetch()
    df = build(px, cot)
    d = df.dropna(subset=["vol_pctl", "mm_z26", "fwd4"]).copy()

    vol_high = d["vol_pctl"] > VOL_PCTL
    zoneA = vol_high & (d["mm_z26"] > 0)  # veto-HEDGE zone (short fuel spent)
    zoneB = vol_high & (d["mm_z26"] < 0)  # HEDGE-OK zone (crowded short)

    print("=" * 88)
    print(
        f"DECADE COHERENCE — forward J+{H} return by regime (chained 2016-2026, {len(d)} sessions w/ COT)"
    )
    print("=" * 88)
    rows = {
        "ALL days": d["fwd4"],
        f"vol_high (atr_pct>p{int(VOL_PCTL * 100)})": d.loc[vol_high, "fwd4"],
        "  A: vol_high & mm_z>0  (HEDGE suspect)": d.loc[zoneA, "fwd4"],
        "  B: vol_high & mm_z<0  (HEDGE ok)": d.loc[zoneB, "fwd4"],
        "low-vol days": d.loc[~vol_high, "fwd4"],
    }
    tbl = pd.DataFrame({k: stats(v) for k, v in rows.items()}).T
    print(tbl.to_string())

    print(
        f"\nSEPARATION (the test): zone A mean fwd{H} should be > 0 (HEDGE loses), zone B < 0 (HEDGE wins)"
    )
    a, b = d.loc[zoneA, "fwd4"], d.loc[zoneB, "fwd4"]
    print(
        f"  A mean={100 * a.mean():+.2f}%  vs  B mean={100 * b.mean():+.2f}%   spread={100 * (a.mean() - b.mean()):+.2f}pp"
    )
    print(
        f"  A HEDGE-win-rate={100 * (a < 0).mean():.1f}%  vs  B HEDGE-win-rate={100 * (b < 0).mean():.1f}%"
    )

    print("\n--- per-year zone A (HEDGE-suspect) forward J+4 ---")
    d["yr"] = d["date"].dt.year
    ya = (
        d[zoneA]
        .groupby("yr")["fwd4"]
        .agg(
            n="size",
            mean=lambda s: round(100 * s.mean(), 2),
            hedge_win=lambda s: round(100 * (s < 0).mean(), 1),
        )
    )
    print(ya.to_string())

    print(
        "\n--- COT m_money_z buckets: forward J+4 (decade) — is there ANY coherent contrarian edge? ---"
    )
    d["zbkt"] = pd.cut(
        d["mm_z26"],
        [-9, -1.5, -0.5, 0.5, 1.5, 9],
        labels=[
            "z<-1.5(vshort)",
            "-1.5..-0.5",
            "-0.5..0.5",
            "0.5..1.5",
            "z>1.5(covered)",
        ],
    )
    bk = d.groupby("zbkt", observed=True)["fwd4"].agg(
        n="size",
        mean=lambda s: round(100 * s.mean(), 2),
        hedge_win=lambda s: round(100 * (s < 0).mean(), 1),
    )
    print(bk.to_string())
    print(
        "  (contrarian edge would show monotonic: vshort -> price up (HEDGE bad), covered -> price down (HEDGE good))"
    )

    print("\n--- IV-crush refinement (2025+ only): does iv_chg5<0 sharpen zone A? ---")
    d25 = d[(d["date"] >= "2025-01-28")]
    za25 = d25[(d25["vol_pctl"] > VOL_PCTL) & (d25["mm_z26"] > 0)]
    za25_iv = za25[za25["iv_chg5"] < 0]
    print(
        f"  zone A (2025+):            n={len(za25):3d}  mean fwd4={100 * za25['fwd4'].mean():+.2f}%  HEDGE-win={100 * (za25['fwd4'] < 0).mean():.1f}%"
    )
    print(
        f"  zone A & IV-crush (2025+): n={len(za25_iv):3d}  mean fwd4={100 * za25_iv['fwd4'].mean():+.2f}%  HEDGE-win={100 * (za25_iv['fwd4'] < 0).mean():.1f}%"
    )


if __name__ == "__main__":
    main()

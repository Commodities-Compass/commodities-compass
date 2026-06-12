"""RESEARCH (non-production) — decade test of candidate WRAPPER detectors (owned data only).

Problem: the ensemble decisions only exist since Dec-2025, so we can't directly backtest wrapper detectors on the
decade. Trick: the 14 specialists are TREND-FOLLOWING, so a momentum-sign baseline is a faithful proxy for their
committed direction. We:
  1. build a trend-following baseline commit on the chained series 2016-2026 (OPEN if N-day return up, else HEDGE),
  2. score it with the exact bilan J+4 grid,
  3. for each candidate detector, dampen the baseline commit -> MONITOR when it fires, and measure the score delta
     over the decade, split by VOL REGIME (the detector must help in high-vol WITHOUT bleeding calm trends),
  4. check whether it would have fired on the May-2026 killer days (05-19..22) and 05-01.

A lever is real if: Σ-delta > 0 on high-vol days, ~>=0 on calm days, and it fires on the May killer cluster.
This is the SAME discipline that refuted the COT veto — a single-episode win is not enough.

Run: PYTHONPATH=. poetry run python scripts/research/wrapper_levers_decade_backtest.py
"""

from __future__ import annotations

import psycopg2
import pandas as pd
import numpy as np

LOCAL_DSN = "host=localhost port=5433 dbname=commodities_compass user=postgres password=password"
MOM_WIN = 10  # baseline trend-follower lookback
KILLER = ["2026-05-19", "2026-05-20", "2026-05-21", "2026-05-22"]


def score_row(decision: str, r: float) -> float:
    if r is None or (isinstance(r, float) and np.isnan(r)):
        return np.nan
    if decision == "OPEN":
        return 1.25 if r > 0.01 else (1.00 if r > 0 else -2.0 * abs(r))
    if decision == "HEDGE":
        return 1.25 if r < -0.01 else (1.00 if r < 0 else -2.0 * abs(r))
    return 1.00 if abs(r) > 0.01 else (0.75 if abs(r) > 0 else 0.0)


def wilder_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0.0)
    dn = (-d).clip(lower=0.0)
    rs = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / dn.ewm(
        alpha=1 / n, adjust=False, min_periods=n
    ).mean().replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def build() -> pd.DataFrame:
    with psycopg2.connect(LOCAL_DSN) as con:
        df = pd.read_sql(
            "select date, contract_id, high, low, close, volume, oi "
            "from v_contract_data_chained order by date",
            con,
        )
    df["date"] = pd.to_datetime(df["date"])
    c, h, lo = (
        df["close"].astype(float),
        df["high"].astype(float),
        df["low"].astype(float),
    )

    # forward J+4 within contract (roll-safe)
    df["fwd4"] = df.groupby("contract_id")["close"].shift(-4) / c - 1.0

    # returns
    df["ret1"] = c.pct_change()
    df["ret5"] = c / c.shift(5) - 1
    df["ret10"] = c / c.shift(MOM_WIN) - 1

    # ATR% + causal 252d percentile (vol regime)
    pc = c.shift(1)
    tr = pd.concat([(h - lo).abs(), (h - pc).abs(), (lo - pc).abs()], axis=1).max(
        axis=1
    )
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    df["atr_pct"] = df["atr"] / c
    df["atr_p252"] = (
        df["atr_pct"]
        .rolling(252, min_periods=60)
        .apply(lambda s: (s.iloc[-1] >= s).mean())
    )
    df["atr_chg3"] = df["atr_pct"] - df["atr_pct"].shift(3)

    # trend stretch (mean-reversion)
    ema20 = c.ewm(span=20, adjust=False).mean()
    stretch = c / ema20 - 1
    df["stretch_z"] = (
        stretch - stretch.rolling(60, min_periods=20).mean()
    ) / stretch.rolling(60, min_periods=20).std()

    # RSI, Bollinger %B
    df["rsi"] = wilder_rsi(c)
    sma20 = c.rolling(20, min_periods=20).mean()
    sd20 = c.rolling(20, min_periods=20).std()
    df["bb_pctb"] = (c - (sma20 - 2 * sd20)) / ((sma20 + 2 * sd20) - (sma20 - 2 * sd20))

    # volume z, OI change
    df["vol_z"] = (df["volume"] - df["volume"].rolling(60, min_periods=20).mean()) / df[
        "volume"
    ].rolling(60, min_periods=20).std()
    df["oi_chg5"] = df["oi"] - df["oi"].shift(5)

    # |ret5| 252d percentile (climax)
    df["abs_ret5_p"] = (
        df["ret5"]
        .abs()
        .rolling(252, min_periods=60)
        .apply(lambda s: (s.iloc[-1] >= s).mean())
    )

    # baseline trend-following commit + committed streak
    df["commit"] = np.where(df["ret10"] > 0, "OPEN", "HEDGE")
    grp = (df["commit"] != df["commit"].shift()).cumsum()
    df["streak"] = df.groupby(grp).cumcount() + 1

    df["score_base"] = [score_row(dc, r) for dc, r in zip(df["commit"], df["fwd4"])]
    return df


def detectors(df: pd.DataFrame) -> dict:
    return {
        "oi_unwind(oiΔ5<0 & |ret5|>3%)": df["oi_chg5"] < 0,  # combined with move below
        "move_climax(|ret5| p90)": df["abs_ret5_p"] > 0.90,
        "stretch_revert(|z|>2)": df["stretch_z"].abs() > 2.0,
        "vol_rollover(atr p80 & falling)": (df["atr_p252"] > 0.80)
        & (df["atr_chg3"] < 0),
        "vol_blowoff(atr p80 & |ret10| p? )": (df["atr_p252"] > 0.80)
        & (df["ret10"].abs() > 0.10),
        "rsi_extreme(>72|<28)": (df["rsi"] > 72) | (df["rsi"] < 28),
        "bb_excursion(%B>1|<0)": (df["bb_pctb"] > 1.0) | (df["bb_pctb"] < 0.0),
        "volume_climax(z>2)": df["vol_z"] > 2.0,
        "overstay(streak>=8)": df["streak"] >= 8,
    }


def main() -> None:
    pd.set_option("display.width", 240)
    df = build().dropna(subset=["fwd4", "atr_p252"]).reset_index(drop=True)
    base_dets = detectors(df)
    base_dets["oi_unwind(oiΔ5<0 & |ret5|>3%)"] = (df["oi_chg5"] < 0) & (
        df["ret5"].abs() > 0.03
    )
    # COMBOS — gate the promising single signals on high-vol regime (sharpen selectivity, keep May coverage)
    _hv = df["atr_p252"] > 0.80
    base_dets["[combo] oi_unwind & hivol"] = (
        (df["oi_chg5"] < 0) & (df["ret5"].abs() > 0.03) & _hv
    )
    base_dets["[combo] shortcover(ret5>0&oiΔ<0) & hivol"] = (
        (df["ret5"] > 0) & (df["oi_chg5"] < 0) & _hv
    )
    base_dets["[combo] stretch|z|>2 & hivol"] = (df["stretch_z"].abs() > 2.0) & _hv
    base_dets["[combo] vol_rollover & oi_unwind"] = (
        (df["atr_p252"] > 0.80) & (df["atr_chg3"] < 0) & (df["oi_chg5"] < 0)
    )

    df["yr"] = df["date"].dt.year
    # recency weight: half-life ~2.5y -> recent years dominate (user: weight recent > old)
    df["w"] = 0.75 ** (2026 - df["yr"])
    df["monitor_score"] = [score_row("MONITOR", r) for r in df["fwd4"]]
    df["d_if_damp"] = (
        df["monitor_score"] - df["score_base"]
    )  # gain from dampening THIS commit
    df["wrong"] = df["score_base"] < 1.0  # commit was PAS BON

    modern = df["yr"] >= 2023  # the structurally-volatile cocoa regime
    hv = df["atr_p252"] > 0.80
    killer = df["date"].isin(pd.to_datetime(KILLER))

    # BLANKET benchmark = dampen EVERY committed day. The bar a real detector must beat on selectivity.
    blanket_avg_all = df["d_if_damp"].mean()
    blanket_avg_mod = df.loc[modern, "d_if_damp"].mean()
    base_wrong_mod = df.loc[modern, "wrong"].mean()

    print("=" * 118)
    print(
        f"WRAPPER LEVER TEST — recency-weighted, modern-regime-focused ({len(df)} sessions; modern=2023+ ={int(modern.sum())})"
    )
    print(
        f"BLANKET 'dampen-all' avg gain/fire: all={blanket_avg_all:+.3f}  modern={blanket_avg_mod:+.3f}  "
        f"| base wrong-rate(modern)={100 * base_wrong_mod:.0f}%  | killer baseline=4xHEDGE Σ={df.loc[killer, 'score_base'].sum():+.2f}"
    )
    print(
        "A real lever beats blanket avg/fire (selectivity), concentrates in hi-vol, and fires on the killer days."
    )
    print("=" * 118)
    print(
        f"{'detector':<36}{'fires':>6}{'avgΔ/fire':>10}{'lift_mod':>9}{'precis_mod':>11}{'hivol%':>8}{'recΣ':>9}{'killer':>8}"
    )
    rows = []
    for name, fire in base_dets.items():
        fire = fire.fillna(False)
        n = int(fire.sum())
        if n == 0:
            continue
        avg_fire = df.loc[fire, "d_if_damp"].mean()
        fm = fire & modern
        avg_fire_mod = df.loc[fm, "d_if_damp"].mean() if fm.any() else float("nan")
        lift_mod = avg_fire_mod / blanket_avg_mod if blanket_avg_mod else float("nan")
        precis_mod = (
            df.loc[fm, "wrong"].mean() if fm.any() else float("nan")
        )  # P(commit wrong | fired)
        hivol_pct = 100 * (fire & hv).sum() / n
        rec_sigma = (
            df.loc[fire, "d_if_damp"] * df.loc[fire, "w"]
        ).sum()  # recency-weighted total gain
        rows.append(
            (
                name,
                n,
                avg_fire,
                lift_mod,
                precis_mod,
                hivol_pct,
                rec_sigma,
                int((fire & killer).sum()),
            )
        )
    # rank by modern selectivity (lift) then killer-fire
    for r in sorted(rows, key=lambda x: (-(x[3] if x[3] == x[3] else -9), -x[7])):
        lift = f"{r[3]:.2f}x" if r[3] == r[3] else "  n/a"
        prec = (
            f"{100 * r[4]:.0f}% vs{100 * base_wrong_mod:.0f}" if r[4] == r[4] else "n/a"
        )
        print(
            f"{r[0]:<36}{r[1]:>6}{r[2]:>+10.3f}{lift:>9}{prec:>11}{r[5]:>7.0f}%{r[6]:>9.1f}{r[7]:>6d}/4"
        )
    print(
        "\nlift_mod = (avgΔ/fire on 2023+ days) / (blanket avgΔ/fire on 2023+).  >1 = selective in the modern regime."
    )
    print(
        "precis_mod = P(the dampened commit was actually wrong | detector fired), 2023+, vs base wrong-rate."
    )


if __name__ == "__main__":
    main()

"""RESEARCH (non-production) — re-simulate May-2026 -> now applying the session's proposed changes.

Layers stacked on the ACTUAL shipped ensemble decisions (pl_orchestrator_decision.decision_wrapped):
  L1 FIX2 trend-conflict : committed day -> MONITOR if |realized_return_7d| > 0.03 AND sign opposite net_score
                           (re-enables the wrapper's off-in-prod detector; validated +1.69 on 6mo).
  L2 regime-MONITOR      : committed day -> MONITOR if atr_pct in top quintile (atr_p252 > 0.80)
                           (EV result: in high-vol, accuracy 76% < ~81% threshold -> MONITOR beats publishing).
                           CAVEAT: the 0.80 threshold was derived ON this data -> in-sample/circular; treat as illustrative.

Macro-gate cap (alpha_macro<1.0) is NOT applied here: the P0 demo showed it changes only 05-12 in May (≈neutral);
its value is robustness in OTHER regimes, not this month. Noted, not double-counted.

Scoring = exact bilan §II J+4 grid. Run:
    PYTHONPATH=. poetry run python scripts/research/resimulate_may_to_now.py
"""

from __future__ import annotations

import psycopg2
import pandas as pd
import numpy as np

DSN = "host=localhost port=5433 dbname=commodities_compass user=postgres password=password"


def score(dec: str, r: float) -> float:
    if pd.isna(r):
        return np.nan
    if dec == "OPEN":
        return 1.25 if r > 0.01 else (1.0 if r > 0 else -2 * abs(r))
    if dec == "HEDGE":
        return 1.25 if r < -0.01 else (1.0 if r < 0 else -2 * abs(r))
    return 1.0 if abs(r) > 0.01 else (0.75 if abs(r) > 0 else 0.0)


def load() -> pd.DataFrame:
    with psycopg2.connect(DSN) as con:
        o = pd.read_sql(
            "select o.date, o.contract_id, o.decision_wrapped dec, o.net_score, cd.close "
            "from pl_orchestrator_decision o "
            "join pl_algorithm_version v on v.id=o.algorithm_version_id and v.name='ensemble_v1_softgate_wrapper' "
            "join pl_contract_data_daily cd on cd.date=o.date and cd.contract_id=o.contract_id "
            "order by o.date",
            con,
        )
        ch = pd.read_sql(
            "select date, high, low, close from v_contract_data_chained order by date",
            con,
        )
    o["date"] = pd.to_datetime(o["date"])
    ch["date"] = pd.to_datetime(ch["date"])
    h, lo, c = ch.high.astype(float), ch.low.astype(float), ch.close.astype(float)
    pc = c.shift(1)
    tr = pd.concat([(h - lo).abs(), (h - pc).abs(), (lo - pc).abs()], axis=1).max(
        axis=1
    )
    ch["atr_p"] = (
        (tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / c)
        .rolling(252, min_periods=60)
        .apply(lambda s: (s.iloc[-1] >= s).mean())
    )
    ch["ret7"] = c / c.shift(7) - 1
    o = o.merge(ch[["date", "atr_p", "ret7"]], on="date", how="left")
    o["c4"] = o.groupby("contract_id")["close"].shift(-4)
    o["r4"] = o["c4"] / o["close"] - 1
    return o


def variants(o: pd.DataFrame) -> pd.DataFrame:
    o = o.copy()
    committed = o["dec"] != "MONITOR"
    fix2 = (
        committed
        & (o["ret7"].abs() > 0.03)
        & (np.sign(o["ret7"]) != np.sign(o["net_score"]))
        & (o["net_score"] != 0)
    )
    regime = committed & (o["atr_p"] > 0.80)
    o["dec_baseline"] = o["dec"]
    o["dec_fix2"] = np.where(fix2, "MONITOR", o["dec"])
    o["dec_regime"] = np.where(regime, "MONITOR", o["dec"])
    o["dec_all"] = np.where(fix2 | regime, "MONITOR", o["dec"])
    return o


def summarize(o: pd.DataFrame, col: str) -> tuple[int, int, float, float]:
    s = o.dropna(subset=["r4"]).copy()
    s["sc"] = [score(d, r) for d, r in zip(s[col], s["r4"])]
    bon = int((s["sc"] >= 1.0).sum())
    n = len(s)
    return bon, n, round(100 * bon / n, 1), round(s["sc"].sum(), 3)


def main() -> None:
    o = variants(load())
    o = o[(o["date"] >= "2026-05-01")].sort_values("date").reset_index(drop=True)

    print("=" * 92)
    print(
        "RE-SIMULATION  May 1 -> now  (scored days have J+4 available; later days PENDING)"
    )
    print("=" * 92)
    print(f"{'variant':<34}{'BON':>5}{'/n':>4}{'acc%':>7}{'Σ score':>10}")
    for col, name in [
        ("dec_baseline", "ACTUAL (shipped)"),
        ("dec_fix2", "+ FIX2 (trend-conflict)"),
        ("dec_regime", "+ regime-MONITOR (hi-vol)"),
        ("dec_all", "+ ALL (FIX2 + regime)"),
    ]:
        bon, n, acc, sig = summarize(o, col)
        print(f"{name:<34}{bon:>5}{n:>4}{acc:>7}{sig:>10}")

    print("\n--- day-by-day (only days where a layer CHANGED the decision) ---")
    o["d"] = o["date"].dt.strftime("%m-%d")
    chg = o[(o["dec_baseline"] != o["dec_all"])].copy()
    rows = []
    for _, r in chg.iterrows():
        rows.append(
            {
                "d": r["d"],
                "r4%": round(100 * r["r4"], 1) if pd.notna(r["r4"]) else None,
                "shipped": r["dec_baseline"],
                "ALL": r["dec_all"],
                "by": ("FIX2" if (r["dec_fix2"] != r["dec_baseline"]) else "")
                + ("+regime" if (r["dec_regime"] != r["dec_baseline"]) else ""),
                "sc_base": round(score(r["dec_baseline"], r["r4"]), 3)
                if pd.notna(r["r4"])
                else None,
                "sc_all": round(score(r["dec_all"], r["r4"]), 3)
                if pd.notna(r["r4"])
                else None,
            }
        )
    df = pd.DataFrame(rows)
    if len(df):
        df["Δ"] = (df["sc_all"].fillna(0) - df["sc_base"].fillna(0)).round(3)
        print(df.to_string(index=False))
        print(f"\n  net Δscore from all changes: {df['Δ'].sum():+.3f}")
    print(
        "\nCAVEATS: 6-month in-sample; regime threshold (atr_p>0.80) derived on this data (circular); "
        "macro-cap ~neutral on May (not applied). FIX2 is the only out-of-mechanism-validated layer."
    )


if __name__ == "__main__":
    main()

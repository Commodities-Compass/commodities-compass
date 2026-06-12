"""RESEARCH (non-production) — backtest the two wrapper ROBUSTNESS fixes on the 6-month ensemble backfill.

These are NOT predictive-edge claims (they can't be — ensemble decisions only exist since Dec-2025,
so no decade validation is possible). They are robustness/plumbing changes. The backtest's job is only
to confirm they don't blow up, and to expose the calm-period (Q1-Apr) collateral honestly.

FIX 1 — NaN-inversion in compass_wrapper.py:
    Today: when running_acc_5d is NaN (cold-start) AND only dispersion fired, the Compass override
    RELEASES the veto (keeps the commit). Rationale was avoiding the 73%-over-veto problem.
    Counter-claim: cold-start = max uncertainty => should VETO (->MONITOR), not release.
    This is a TRADE-OFF: it protects regime-break days (05-19) but re-introduces over-veto on calm
    cold-start days. Net must be measured.
    Sim: decision -> MONITOR where (fired_dispersion & running_acc_5d IS NULL & decision != MONITOR).

FIX 2 — re-enable trend-conflict detector (off in prod; tau_trend=0.03, window=7):
    fired_trend = |realized_return_7d| > 0.03 AND sign(realized_return_7d) opposite sign(net_score).
    Sim: committed decision -> MONITOR where fired_trend.
    (NB: real impl also needs writer plumbing — _build_diagnostics hardcodes fired_trend=False.)

Scoring = bilan §II grid (J+4). Run:
    PYTHONPATH=. poetry run python scripts/research/robustness_fixes_backtest.py
"""

from __future__ import annotations

import psycopg2
import pandas as pd
import numpy as np

LOCAL_DSN = "host=localhost port=5433 dbname=commodities_compass user=postgres password=password"
ENSEMBLE = "ensemble_v1_softgate_wrapper"
TAU_TREND = 0.03
TREND_WINDOW = 7


def score_row(decision: str, r: float) -> float:
    if r is None or (isinstance(r, float) and np.isnan(r)):
        return np.nan
    if decision == "OPEN":
        return 1.25 if r > 0.01 else (1.00 if r > 0 else -2.0 * abs(r))
    if decision == "HEDGE":
        return 1.25 if r < -0.01 else (1.00 if r < 0 else -2.0 * abs(r))
    return 1.00 if abs(r) > 0.01 else (0.75 if abs(r) > 0 else 0.0)


def fetch() -> pd.DataFrame:
    with psycopg2.connect(LOCAL_DSN) as con:
        df = pd.read_sql(
            """
            select o.date, o.contract_id, o.net_score, o.decision_wrapped,
                   o.fired_dispersion, o.fired_running_acc, o.running_acc_5d,
                   o.wrapper_active, cd.close
            from pl_orchestrator_decision o
            join pl_algorithm_version v
              on v.id=o.algorithm_version_id and v.name=%s
            join pl_contract_data_daily cd
              on cd.date=o.date and cd.contract_id=o.contract_id
            order by o.date
            """,
            con,
            params=(ENSEMBLE,),
        )
    df["date"] = pd.to_datetime(df["date"])
    df["c4"] = df.groupby("contract_id")["close"].shift(-4)
    df["r4"] = df["c4"] / df["close"] - 1.0
    df["r7"] = (
        df["close"] / df.groupby("contract_id")["close"].shift(TREND_WINDOW) - 1.0
    )
    df["score_base"] = [
        score_row(d, r) for d, r in zip(df["decision_wrapped"], df["r4"])
    ]
    return df


def summarize(df: pd.DataFrame, col: str, label: str) -> None:
    d = df.dropna(subset=[col])
    calm = d[d["date"] < "2026-05-01"]
    may = d[(d["date"] >= "2026-05-01") & (d["date"] < "2026-06-01")]
    print(
        f"  {label:<26} totΣ={d[col].sum():7.3f}  BON={int((d[col] >= 1).sum()):2d}  "
        f"| Q1-Apr Σ={calm[col].sum():7.3f}  | May Σ={may[col].sum():6.3f} acc={100 * (may[col] >= 1).mean():4.1f}%"
    )


def main() -> None:
    pd.set_option("display.width", 200)
    df = fetch()

    # FIX 1 — NaN-inversion
    inv = df.copy()
    flip1 = (
        inv["fired_dispersion"].astype(bool)
        & inv["running_acc_5d"].isna()
        & (inv["decision_wrapped"] != "MONITOR")
    )
    inv["dec1"] = np.where(flip1, "MONITOR", inv["decision_wrapped"])
    inv["score1"] = [score_row(d, r) for d, r in zip(inv["dec1"], inv["r4"])]

    # FIX 2 — trend detector on
    fired_trend = (
        (inv["r7"].abs() > TAU_TREND)
        & (np.sign(inv["r7"]) != np.sign(inv["net_score"]))
        & (inv["net_score"] != 0)
    )
    flip2 = fired_trend & (inv["decision_wrapped"] != "MONITOR")
    inv["dec2"] = np.where(flip2, "MONITOR", inv["decision_wrapped"])
    inv["score2"] = [score_row(d, r) for d, r in zip(inv["dec2"], inv["r4"])]

    # COMBINED
    flipc = flip1 | flip2
    inv["decc"] = np.where(flipc, "MONITOR", inv["decision_wrapped"])
    inv["scorec"] = [score_row(d, r) for d, r in zip(inv["decc"], inv["r4"])]

    print("=" * 92)
    print("ROBUSTNESS FIXES — 6-month ensemble backfill (J+4 bilan scoring)")
    print("=" * 92)
    summarize(inv, "score_base", "BASELINE (prod)")
    summarize(inv, "score1", "FIX1 NaN-inversion")
    summarize(inv, "score2", "FIX2 trend-on")
    summarize(inv, "scorec", "FIX1+FIX2 combined")

    for tag, flip, sc in (
        ("FIX1 NaN-inv", flip1, "score1"),
        ("FIX2 trend-on", flip2, "score2"),
    ):
        f = inv[flip].copy()
        f["d"] = f["date"].dt.strftime("%m-%d")
        f["delta"] = f[sc] - f["score_base"]
        print(f"\n--- {tag}: flipped sessions ({int(flip.sum())}) ---")
        if len(f):
            print(
                f[
                    [
                        "d",
                        "decision_wrapped",
                        "r4",
                        "running_acc_5d",
                        "net_score",
                        "score_base",
                        sc,
                        "delta",
                    ]
                ]
                .round(3)
                .to_string(index=False)
            )
            print(
                f"  net delta={f['delta'].sum():.3f}  "
                f"(calm Q1-Apr delta={f[f['date'] < '2026-05-01']['delta'].sum():.3f})"
            )


if __name__ == "__main__":
    main()

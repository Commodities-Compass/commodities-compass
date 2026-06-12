"""RESEARCH (non-production) — backtest a HEDGE->MONITOR conditioning veto for the Compass wrapper.

Hypothesis (from the May-2026 bilan + prod data dive):
    The ensemble's worst losses in volatile regimes are HIGH-conviction HEDGE calls held
    through a short-covering rebound (05-19->05-22). They are unprotected because the wrapper's
    running_acc detector goes NULL in cold-start and dispersion rarely fires.

    A deterministic conditioning veto can dampen those commits to MONITOR using signals already
    in the DB (no new scraper, no retrain, no ML — only 12 wrong-commit events exist, far too few
    to train a meta-label model):
        - atr_pct  = atr_14d / close                         (vol regime, causal)
        - mm_z26   = z-score of COT EU managed-money net      (positioning, AS-OF release_date)
        - iv_z60   = z-score of implied_volatility (60d)      (IV crush, causal)

    Rule v1 (HEDGE side only — the validated, high-value path):
        flip HEDGE -> MONITOR  iff  atr_pct > ATR_THR  AND  mm_z26 > MM_Z_THR
        (high vol regime AND managed-money short fuel spent => a max-conviction HEDGE is suspect)

Scoring grid = exact bilan §II (J+4 forward return r, fractional):
    OPEN : r>+1% -> +1.25 ; 0<r<=+1% -> +1.00 ; r<=0 -> -2*|r|
    HEDGE: r<-1% -> +1.25 ; -1%<=r<0 -> +1.00 ; r>=0 -> -2*|r|
    MONITOR: |r|>1% -> +1.00 ; 0<|r|<=1% -> +0.75 ; r==0 -> 0
    BON = score >= 1.00

Guardrail: report Q1-Apr separately — the veto must NOT degrade the calm-regime winners
(the original 73%-veto failure mode the Compass override was built to avoid).

Run:  PYTHONPATH=. poetry run python scripts/research/wrapper_conditioning_backtest.py
"""

from __future__ import annotations

import psycopg2
import pandas as pd
import numpy as np

LOCAL_DSN = "host=localhost port=5433 dbname=commodities_compass user=postgres password=password"
ENSEMBLE = "ensemble_v1_softgate_wrapper"
HORIZON = 4

# --- tunable thresholds (swept below) ---
ATR_THR = 0.048  # April max atr_pct ~0.047 -> fires only in the May/Jun vol regime
MM_Z_THR = 0.0  # managed-money net z > 0 => no longer crowded short => HEDGE suspect


def fetch() -> tuple[pd.DataFrame, pd.DataFrame]:
    with psycopg2.connect(LOCAL_DSN) as con:
        dec = pd.read_sql(
            """
            select o.date, o.contract_id,
                   o.soft_gate_decision, o.decision_wrapped, o.net_score,
                   o.macro_direction, o.running_acc_5d, o.fired_dispersion,
                   cd.close, cd.implied_volatility iv, cd.oi,
                   di.atr_14d
            from pl_orchestrator_decision o
            join pl_algorithm_version v
              on v.id=o.algorithm_version_id and v.name=%s
            join pl_contract_data_daily cd
              on cd.date=o.date and cd.contract_id=o.contract_id
            left join pl_derived_indicators di
              on di.date=o.date and di.contract_id=o.contract_id
            order by o.date
            """,
            con,
            params=(ENSEMBLE,),
        )
        cot = pd.read_sql(
            """
            select release_date, m_money_net
            from pl_cot_eu_weekly
            where contract_market='cocoa'
            order by release_date
            """,
            con,
        )
    return dec, cot


def score_row(decision: str, r: float) -> float:
    if r is None or np.isnan(r):
        return np.nan
    if decision == "OPEN":
        if r > 0.01:
            return 1.25
        if r > 0:
            return 1.00
        return -2.0 * abs(r)
    if decision == "HEDGE":
        if r < -0.01:
            return 1.25
        if r < 0:
            return 1.00
        return -2.0 * abs(r)
    # MONITOR
    if abs(r) > 0.01:
        return 1.00
    if abs(r) > 0:
        return 0.75
    return 0.0


def build(dec: pd.DataFrame, cot: pd.DataFrame) -> pd.DataFrame:
    dec = dec.copy()
    dec["date"] = pd.to_datetime(dec["date"])
    dec = dec.sort_values("date").reset_index(drop=True)

    # forward J+4 return per contract (roll-boundary rows -> NaN, dropped from scoring)
    dec["c4"] = dec.groupby("contract_id")["close"].shift(-HORIZON)
    dec["r4"] = dec["c4"] / dec["close"] - 1.0

    # causal conditioning signals
    dec["atr_pct"] = dec["atr_14d"] / dec["close"]
    g = dec.groupby("contract_id")["iv"]
    dec["iv_z60"] = g.transform(
        lambda s: (
            (s - s.rolling(60, min_periods=20).mean())
            / s.rolling(60, min_periods=20).std()
        )
    )
    # IV crush = implied vol falling over 5 sessions (squeeze exhaustion, NOT fresh fear).
    # June's correct HEDGEs ran with RISING iv (real downtrend); May's wrong HEDGEs with crushing iv.
    dec["iv_chg5"] = g.transform(lambda s: s - s.shift(5))

    # COT managed-money z (26 weekly) then AS-OF merge by release_date <= decision date
    cot = cot.copy()
    cot["release_date"] = pd.to_datetime(cot["release_date"])
    cot = cot.sort_values("release_date")
    cot["mm_z26"] = (
        cot["m_money_net"] - cot["m_money_net"].rolling(26, min_periods=8).mean()
    ) / cot["m_money_net"].rolling(26, min_periods=8).std()
    dec = pd.merge_asof(
        dec,
        cot[["release_date", "mm_z26"]],
        left_on="date",
        right_on="release_date",
        direction="backward",
    )

    dec["score_base"] = [
        score_row(d, r) for d, r in zip(dec["decision_wrapped"], dec["r4"])
    ]
    return dec


def apply_rule(
    dec: pd.DataFrame, atr_thr: float, mm_z_thr: float, require_iv_crush: bool = False
) -> pd.DataFrame:
    dec = dec.copy()
    suspect_hedge = (
        (dec["decision_wrapped"] == "HEDGE")
        & (dec["atr_pct"] > atr_thr)
        & (dec["mm_z26"] > mm_z_thr)
    )
    if require_iv_crush:
        suspect_hedge = suspect_hedge & (dec["iv_chg5"] < 0)
    dec["decision_new"] = np.where(suspect_hedge, "MONITOR", dec["decision_wrapped"])
    dec["flipped"] = suspect_hedge
    dec["score_new"] = [score_row(d, r) for d, r in zip(dec["decision_new"], dec["r4"])]
    return dec


def agg(dec: pd.DataFrame, col: str) -> pd.DataFrame:
    d = dec.dropna(subset=[col]).copy()
    d["mon"] = d["date"].dt.strftime("%Y-%m")
    out = d.groupby("mon").apply(
        lambda x: pd.Series(
            {
                "n": len(x),
                "BON": int((x[col] >= 1.0).sum()),
                "PASBON": int((x[col] < 1.0).sum()),
                "acc%": round(100 * (x[col] >= 1.0).mean(), 1),
                "sum": round(x[col].sum(), 3),
            }
        ),
        include_groups=False,
    )
    return out


def main() -> None:
    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 200)
    dec, cot = fetch()
    dec = build(dec, cot)
    v1 = apply_rule(dec, ATR_THR, MM_Z_THR, require_iv_crush=False)
    v2 = apply_rule(dec, ATR_THR, MM_Z_THR, require_iv_crush=True)

    def totals(d: pd.DataFrame, col: str) -> str:
        x = d.dropna(subset=[col])
        return f"BON={int((x[col] >= 1).sum())}  Sum={x[col].sum():.3f}  acc={100 * (x[col] >= 1).mean():.1f}%"

    print("=" * 84)
    print(
        f"RULE base: HEDGE->MONITOR if atr_pct>{ATR_THR} & mm_z26>{MM_Z_THR}   |   v2 adds: & iv_chg5<0 (IV crush)"
    )
    print("=" * 84)
    cmp = (
        agg(v2, "score_base")
        .join(agg(v1, "score_new"), rsuffix="_v1")
        .join(agg(v2, "score_new").add_suffix("_v2"))
    )[["sum", "sum_v1", "sum_v2", "acc%", "acc%_v1", "acc%_v2"]]
    print(cmp.to_string())

    print("\n--- TOTALS ---")
    print(f"  baseline : {totals(v2, 'score_base')}")
    print(f"  v1 vol×COT       : {totals(v1, 'score_new')}")
    print(f"  v2 vol×COT×IVcrush: {totals(v2, 'score_new')}")

    for tag, r in (("v1", v1), ("v2", v2)):
        print(f"\n--- FLIPPED SESSIONS [{tag}] (HEDGE -> MONITOR) ---")
        fl = r[r["flipped"]].copy()
        fl["d"] = fl["date"].dt.strftime("%m-%d")
        fl["delta"] = fl["score_new"] - fl["score_base"]
        print(
            fl[
                [
                    "d",
                    "r4",
                    "atr_pct",
                    "mm_z26",
                    "iv_chg5",
                    "score_base",
                    "score_new",
                    "delta",
                ]
            ]
            .round(3)
            .to_string(index=False)
        )
        print(
            f"  flips={len(fl)}  net delta={fl['delta'].sum():.3f}  "
            f"(prize 05-19..22={fl[fl['d'].between('05-19', '05-22')]['delta'].sum():.3f})"
        )


if __name__ == "__main__":
    main()

"""RESEARCH (non-production) — P0 feasibility proof: can we retune the soft-gate macro gate IN THIS PROJECT?

We re-run the REAL vendor SoftGateOrchestrator (ensemble.orchestrator.soft_gate) on our own 6-month vote history,
varying ONLY alpha_macro, to demonstrate:
  (a) the retune harness is buildable in-project from data we already have (votes + context in the DB), and
  (b) capping alpha_macro < 1.0 dissolves the May "unanimous HEDGE (net_score=-1.000)" collapse without
      damaging the calm Q1-Apr months.

Inputs (all in local DB, synced from prod):
  pl_specialist_prediction  -> the 14 votes per day
  pl_orchestrator_decision  -> the OrchestratorContext fields (macro_direction, priors, anomaly_z) + the actual
                               prod soft_gate_decision (to VALIDATE the harness reproduces prod at alpha=1.477)
  pl_contract_data_daily    -> close (forward J+4 return for bilan scoring)

CAVEATS (honest): base_accuracy is set UNIFORM (=0.5 -> base weight 1.0) because the per-specialist rolling-30d
accuracy isn't stored; prod uses the real values. The macro-ZEROING mechanism is base_acc-independent (0 x w = 0),
so the unanimity effect reproduces regardless, but absolute net_scores differ slightly from prod. This is a
DIRECTIONAL in-project prototype; the production-grade, decade-walk-forward retune still belongs to R&D
(their Optuna walk-forward isn't shipped in the vendor package).

Run: PYTHONPATH=. poetry run python scripts/research/p0_macro_gate_retune.py
"""

from __future__ import annotations

import psycopg2
import pandas as pd
import numpy as np

from ensemble.orchestrator.soft_gate import (
    SoftGateOrchestrator,
    SoftGateConfig,
    OrchestratorContext,
)

LOCAL_DSN = "host=localhost port=5433 dbname=commodities_compass user=postgres password=password"
ENSEMBLE = "ensemble_v1_softgate_wrapper"
# Prod-tuned soft-gate params (pl_algorithm_config, ensemble version)
ALPHA_PRIOR = 0.1664
ALPHA_ANOM = 0.7219
COMMIT_THR = 0.2493
ALPHA_MACRO_PROD = 1.477


def score_row(decision: str, r: float) -> float:
    if r is None or (isinstance(r, float) and np.isnan(r)):
        return np.nan
    if decision == "OPEN":
        return 1.25 if r > 0.01 else (1.00 if r > 0 else -2.0 * abs(r))
    if decision == "HEDGE":
        return 1.25 if r < -0.01 else (1.00 if r < 0 else -2.0 * abs(r))
    return 1.00 if abs(r) > 0.01 else (0.75 if abs(r) > 0 else 0.0)


def fetch():
    with psycopg2.connect(LOCAL_DSN) as con:
        votes = pd.read_sql(
            """select o.date, sp.specialist_name, sp.pred
               from pl_specialist_prediction sp
               join pl_orchestrator_decision o on o.date=sp.date and o.contract_id=sp.contract_id
                    and o.algorithm_version_id=sp.algorithm_version_id
               join pl_algorithm_version v on v.id=sp.algorithm_version_id and v.name=%s
               order by o.date""",
            con,
            params=(ENSEMBLE,),
        )
        ctx = pd.read_sql(
            """select o.date, o.contract_id, o.soft_gate_decision, o.net_score,
                      o.macro_direction, o.macro_surprise, o.prior_open, o.prior_hedge, o.prior_monitor,
                      o.anomaly_score_z, cd.close
               from pl_orchestrator_decision o
               join pl_algorithm_version v on v.id=o.algorithm_version_id and v.name=%s
               join pl_contract_data_daily cd on cd.date=o.date and cd.contract_id=o.contract_id
               order by o.date""",
            con,
            params=(ENSEMBLE,),
        )
    return votes, ctx


def build(ctx: pd.DataFrame) -> pd.DataFrame:
    ctx = ctx.copy()
    ctx["date"] = pd.to_datetime(ctx["date"])
    ctx["c4"] = ctx.groupby("contract_id")["close"].shift(-4)
    ctx["r4"] = ctx["c4"] / ctx["close"] - 1.0
    return ctx


def run_alpha(
    votes_by_day: dict, ctx: pd.DataFrame, alpha_macro: float
) -> pd.DataFrame:
    orch = SoftGateOrchestrator(
        config=SoftGateConfig(
            alpha_macro=alpha_macro,
            alpha_prior=ALPHA_PRIOR,
            alpha_anomaly=ALPHA_ANOM,
            commit_threshold=COMMIT_THR,
        ),
        base_accuracy=None,  # uniform (see caveat)
    )
    out = []
    for _, row in ctx.iterrows():
        d = row["date"]
        vd = votes_by_day.get(d, {})
        if not vd:
            continue
        context = OrchestratorContext(
            date=d,
            macro_direction=int(row["macro_direction"])
            if pd.notna(row["macro_direction"])
            else 0,
            macro_surprise=float(row["macro_surprise"])
            if pd.notna(row["macro_surprise"])
            else 0.0,
            macro_confidence=1.0,  # unused by decide()
            prior_open=float(row["prior_open"])
            if pd.notna(row["prior_open"])
            else 1 / 3,
            prior_hedge=float(row["prior_hedge"])
            if pd.notna(row["prior_hedge"])
            else 1 / 3,
            prior_monitor=float(row["prior_monitor"])
            if pd.notna(row["prior_monitor"])
            else 1 / 3,
            anomaly_score_z=float(row["anomaly_score_z"])
            if pd.notna(row["anomaly_score_z"])
            else 0.0,
            cluster_weights={},  # unused by decide()
        )
        dec = orch.decide(vd, context)
        out.append(
            {
                "date": d,
                "decision": dec.decision,
                "net_score": dec.net_score,
                "r4": row["r4"],
                "prod_sg": row["soft_gate_decision"],
            }
        )
    df = pd.DataFrame(out)
    df["score"] = [score_row(dc, r) for dc, r in zip(df["decision"], df["r4"])]
    return df


def agg(df: pd.DataFrame) -> str:
    s = df.dropna(subset=["score"])
    may = s[(s["date"] >= "2026-05-01") & (s["date"] < "2026-06-01")]
    calm = s[s["date"] < "2026-05-01"]
    unan = (df["net_score"].abs() > 0.99).mean()
    return (
        f"May acc={100 * (may['score'] >= 1).mean():4.1f}% Σ={may['score'].sum():6.2f} | "
        f"Q1-Apr Σ={calm['score'].sum():6.2f} | unanimous(|net|>.99)={100 * unan:4.1f}% | "
        f"totΣ={s['score'].sum():7.2f}"
    )


def main() -> None:
    votes, ctx = fetch()
    ctx = build(ctx)
    votes["date"] = pd.to_datetime(votes["date"])
    votes_by_day = {
        d: dict(zip(g["specialist_name"], g["pred"])) for d, g in votes.groupby("date")
    }

    # Harness validation: reproduce prod soft_gate_decision at alpha=1.477
    base = run_alpha(votes_by_day, ctx, ALPHA_MACRO_PROD)
    agree = (base["decision"] == base["prod_sg"]).mean()
    print("=" * 96)
    print("P0 IN-PROJECT RETUNE — real vendor SoftGateOrchestrator re-run on our votes")
    print(
        f"Harness validation: reproduces prod soft_gate_decision at alpha_macro={ALPHA_MACRO_PROD} "
        f"in {100 * agree:.0f}% of {len(base)} days (uniform base_acc approx)"
    )
    print("=" * 96)
    for am in (1.477, 1.0, 0.9, 0.7, 0.5):
        tag = "  (PROD)" if am == 1.477 else ("  <- cap <1.0" if am == 0.9 else "")
        print(f"  alpha_macro={am:<5} {agg(run_alpha(votes_by_day, ctx, am))}{tag}")

    print("\n--- May decisions: PROD(alpha=1.477) vs capped(alpha=0.9) ---")
    a = run_alpha(votes_by_day, ctx, 1.477).set_index("date")
    b = run_alpha(votes_by_day, ctx, 0.9).set_index("date")
    may = a[(a.index >= "2026-05-01") & (a.index < "2026-06-01")]
    rows = []
    for d in may.index:
        rows.append(
            {
                "d": d.strftime("%m-%d"),
                "r4%": round(100 * a.loc[d, "r4"], 1),
                "prod_dec": a.loc[d, "decision"],
                "prod_net": round(a.loc[d, "net_score"], 2),
                "cap_dec": b.loc[d, "decision"],
                "cap_net": round(b.loc[d, "net_score"], 2),
                "Δscore": round(
                    (b.loc[d, "score"] if not np.isnan(b.loc[d, "score"]) else 0)
                    - (a.loc[d, "score"] if not np.isnan(a.loc[d, "score"]) else 0),
                    3,
                ),
            }
        )
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()

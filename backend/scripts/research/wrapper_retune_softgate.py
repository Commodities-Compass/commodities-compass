"""RESEARCH — soft-gate lever exploration (the levers the wrapper CAN'T reach).

The recency analysis showed the wrapper is near-exhausted (C4) and recent accuracy is
capped ~60% by the SOFT-GATE, not the wrapper. The soft-gate is a pure function of the
cached inputs (votes + macro_direction + priors + anomaly_z; base_accuracy is empty in
prod => uniform base_weight 1.0). So we re-run ONLY the soft-gate per (alpha_macro,
commit_threshold) in microseconds — no specialists, no recompute — then feed the new
soft-gate outputs through the C4 wrapper and score full + last-50.

Prod soft-gate: alpha_macro=1.477 CAPPED to 0.9, alpha_prior=0.166, alpha_anomaly=0.722,
commit_threshold=0.249, anomaly_clip_abs=2.5.

Run: PYTHONPATH=. poetry run python scripts/research/wrapper_retune_softgate.py
"""

from __future__ import annotations

import dataclasses

import pandas as pd
from ensemble.orchestrator.soft_gate import (
    OrchestratorContext,
    SoftGateConfig,
    SoftGateOrchestrator,
)

from scripts.research.wrapper_retune_lib import (
    build_decisions_df,
    evaluate,
    load_cache,
    metrics_from_out,
)
from scripts.research.wrapper_retune_lib import load_prod_config

# Prod soft-gate (alpha_macro already the 0.9 Compass cap, not the raw 1.477).
PROD_SG = SoftGateConfig(
    alpha_macro=0.9,
    alpha_prior=0.16637118046802363,
    alpha_anomaly=0.7218905885571766,
    commit_threshold=0.24926406400500623,
    anomaly_clip_abs=2.5,
)
LAST50 = 50


def resim_softgate(
    cache: pd.DataFrame, votes: pd.DataFrame, cfg: SoftGateConfig
) -> pd.DataFrame:
    """Re-run the soft-gate for one config; return a cache-shaped frame with new
    soft_gate_decision + net_score (everything else preserved from the original cache)."""
    votes_by_date = {
        d: dict(zip(g["specialist_name"], g["pred"])) for d, g in votes.groupby("date")
    }
    orch = SoftGateOrchestrator(config=cfg)  # base_accuracy empty = prod
    out = cache.copy()
    sg_dec, ns = [], []
    for _, r in cache.iterrows():
        ctx = OrchestratorContext(
            date=r["date"],
            macro_direction=int(r["macro_direction"]),
            macro_surprise=float(r["macro_surprise"]),
            macro_confidence=0.0,
            prior_open=float(r["prior_open"]),
            prior_hedge=float(r["prior_hedge"]),
            prior_monitor=float(r["prior_monitor"]),
            anomaly_score_z=float(r["anomaly_score_z"]),
            cluster_weights={},
        )
        d = orch.decide(votes_by_date[r["date"]], ctx)
        sg_dec.append(d.decision)
        ns.append(d.net_score)
    out["soft_gate_decision"] = sg_dec
    out["net_score"] = ns
    return out


def _windows(out):
    o = out.sort_values("date").reset_index(drop=True)
    return metrics_from_out(o), metrics_from_out(o.tail(LAST50))


def _row(label, mf, ml, sg_mon):
    return (
        f"{label:<26} sgMON={sg_mon:>3} | FULL O/H/M={mf.n_open}/{mf.n_hedge}/{mf.n_monitor} "
        f"act={mf.actionable_pct:>4}% acc={mf.dir_acc}%({mf.n_committed_scored}) Σ={mf.sigma:>6.1f} | "
        f"L50 act={ml.actionable_pct:>4}% acc={ml.dir_acc}%({ml.n_committed_scored}) Σ={ml.sigma:>5.1f}"
    )


def main() -> None:
    cache, votes, series, cmap = load_cache()
    # C4 wrapper = prod wrapper + regime OFF + tau_trend 0.05 (the wrapper optimum).
    wc0, ct0, _ = load_prod_config()
    C4 = dataclasses.replace(wc0, tau_trend=0.05)

    def eval_cfg(sg_cfg, label):
        c = resim_softgate(cache, votes, sg_cfg)
        ddf = build_decisions_df(c, series)
        _, out = evaluate(
            ddf,
            votes,
            series,
            cmap,
            wrapper_config=C4,
            compass_threshold=ct0,
            regime_threshold=None,
        )
        mf, ml = _windows(out)
        sg_mon = int((c["soft_gate_decision"] == "MONITOR").sum())
        return mf, ml, sg_mon, out

    # ---- 0. validate the cheap re-runner reproduces the cached soft-gate ----
    resim0 = resim_softgate(cache, votes, PROD_SG)
    match = int(
        (
            resim0["soft_gate_decision"].values == cache["soft_gate_decision"].values
        ).sum()
    )
    ns_max = float(
        (resim0["net_score"].values - cache["net_score"].values).__abs__().max()
    )
    print(
        f"VALIDATION: re-run soft-gate vs cached — decision match {match}/{len(cache)}, "
        f"max |Δnet_score|={ns_max:.4f}  {'OK' if match == len(cache) and ns_max < 1e-3 else 'MISMATCH!'}"
    )

    # ---- reference: prod soft-gate under C4 wrapper ----
    print("\n=== reference (prod soft-gate) under C4 wrapper ===")
    mf, ml, sgm, _ = eval_cfg(PROD_SG, "prod SG + C4")
    print(_row("prod SG (a_macro=0.9)", mf, ml, sgm))

    # ---- 1. sweep alpha_macro (commit_threshold at prod) ----
    print("\n=== 1. alpha_macro sweep (commit_threshold=0.249, C4 wrapper) ===")
    for am in (0.0, 0.3, 0.5, 0.7, 0.9, 1.1, 1.477):
        mf, ml, sgm, _ = eval_cfg(
            dataclasses.replace(PROD_SG, alpha_macro=am), f"a_macro={am}"
        )
        print(_row(f"a_macro={am}", mf, ml, sgm))

    # ---- 2. sweep commit_threshold (alpha_macro at prod 0.9) ----
    print("\n=== 2. commit_threshold sweep (alpha_macro=0.9, C4 wrapper) ===")
    for ct in (0.10, 0.15, 0.20, 0.24926, 0.30, 0.40):
        mf, ml, sgm, _ = eval_cfg(
            dataclasses.replace(PROD_SG, commit_threshold=ct), f"commit={ct}"
        )
        print(_row(f"commit_thr={ct}", mf, ml, sgm))

    # ---- 3. joint alpha_macro x commit_threshold, ranked by L50 Σ ----
    print(
        "\n=== 3. joint (alpha_macro x commit_threshold) — top by L50 Σ, guardrail full_acc≥73 ==="
    )
    rows = []
    for am in (0.0, 0.3, 0.5, 0.7, 0.9, 1.1):
        for ct in (0.10, 0.15, 0.20, 0.24926, 0.30):
            mf, ml, sgm, _ = eval_cfg(
                dataclasses.replace(PROD_SG, alpha_macro=am, commit_threshold=ct),
                f"a={am},c={ct}",
            )
            rows.append((am, ct, mf, ml, sgm))
    rows = [r for r in rows if r[2].dir_acc >= 73 and not pd.isna(r[3].dir_acc)]
    for am, ct, mf, ml, sgm in sorted(rows, key=lambda x: -x[3].sigma)[:12]:
        print(_row(f"a={am} c={ct}", mf, ml, sgm))
    print("\n=== top by FULL Σ ===")
    for am, ct, mf, ml, sgm in sorted(rows, key=lambda x: -x[2].sigma)[:8]:
        print(_row(f"a={am} c={ct}", mf, ml, sgm))


if __name__ == "__main__":
    main()

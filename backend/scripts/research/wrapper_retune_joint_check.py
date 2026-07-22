"""RESEARCH — confirm the wrapper optimum (regime OFF + tau_trend 0.05) is STILL optimal
under the alpha_macro=0.3 soft-gate (the wrapper was tuned on the prod soft-gate; C5-full
stacks both, so re-validate the interaction before shipping).

Run: PYTHONPATH=. poetry run python scripts/research/wrapper_retune_joint_check.py
"""

from __future__ import annotations

import dataclasses


from scripts.research.wrapper_retune_lib import (
    build_decisions_df,
    evaluate,
    load_cache,
    load_prod_config,
    metrics_from_out,
)
from scripts.research.wrapper_retune_softgate import PROD_SG, resim_softgate

LAST50 = 50


def main() -> None:
    cache, votes, series, cmap = load_cache()
    wc0, ct0, rt0 = load_prod_config()
    # C5 soft-gate = alpha_macro 0.3 + commit 0.15
    sg = dataclasses.replace(PROD_SG, alpha_macro=0.3, commit_threshold=0.15)
    c = resim_softgate(cache, votes, sg)
    ddf = build_decisions_df(c, series)
    print(
        f"soft-gate α=0.3 c=0.15 → sgMON={int((c['soft_gate_decision'] == 'MONITOR').sum())}/143"
    )

    R = dataclasses.replace

    def ev(cfg, ct, rt, label):
        _, out = evaluate(
            ddf,
            votes,
            series,
            cmap,
            wrapper_config=cfg,
            compass_threshold=ct,
            regime_threshold=rt,
        )
        o = out.sort_values("date").reset_index(drop=True)
        mf, ml = metrics_from_out(o), metrics_from_out(o.tail(LAST50))
        print(
            f"{label:<32} FULL O/H/M={mf.n_open}/{mf.n_hedge}/{mf.n_monitor} "
            f"act={mf.actionable_pct}% acc={mf.dir_acc}%({mf.n_committed_scored}) Σ={mf.sigma:.1f} | "
            f"L50 act={ml.actionable_pct}% acc={ml.dir_acc}%({ml.n_committed_scored}) Σ={ml.sigma:.1f}"
        )

    print(
        "\n=== wrapper ablations UNDER the α=0.3 soft-gate (which wrapper is best now?) ==="
    )
    ev(wc0, ct0, rt0, "prod wrapper (regime@0.8)")
    ev(wc0, ct0, None, "regime OFF only")
    ev(R(wc0, tau_trend=0.05), ct0, None, "C4: regime OFF + trend0.05")
    ev(R(wc0, tau_trend=0.05), ct0, 0.90, "regime@0.9 + trend0.05")
    ev(R(wc0, tau_trend=0.04), ct0, None, "regime OFF + trend0.04")
    ev(R(wc0, tau_trend=0.06), ct0, None, "regime OFF + trend0.06")
    ev(R(wc0, use_trend_conflict=False), ct0, None, "regime OFF + trend OFF")
    ev(
        R(wc0, tau_trend=0.05, use_cluster_dispersion=False),
        ct0,
        None,
        "C4 + dispersion OFF",
    )
    ev(R(wc0, tau_trend=0.05, tau_run=0.50), ct0, None, "C4 + tau_run0.50")
    ev(R(wc0, tau_trend=0.05, tau_run=0.65), ct0, None, "C4 + tau_run0.65")
    print(
        "\n=> confirm 'C4: regime OFF + trend0.05' is on the frontier (best or ~tied full+L50 Σ)."
    )


if __name__ == "__main__":
    main()

"""RESEARCH — broad recency-focused wrapper lever exploration.

User steer (2026-07-22): focus on what performs better on the RECENT sessions (last ~50),
we're OK removing levers but also explore OTHER lever settings for even better perf.
Recency matters because the C1/regime-off win is Jan-Feb-driven; regime barely fires
Mar-Jul, so the recent frontier is shaped by running_acc / trend / dispersion instead.

Sweeps the full config-as-data lever space (the 4 wrapper detectors' thresholds +
dispersion-release + regime), scores each on full / last50 / last30 windows from a single
full-history wrapper pass, and ranks by recent Σ with an accuracy guardrail.

Run: PYTHONPATH=. poetry run python scripts/research/wrapper_retune_explore.py
"""

from __future__ import annotations

import dataclasses

import pandas as pd

from scripts.research.wrapper_retune_lib import (
    build_decisions_df,
    evaluate,
    load_cache,
    load_prod_config,
    metrics_from_out,
)

LAST50 = 50
LAST30 = 30


def _windows(out: pd.DataFrame) -> dict:
    o = out.sort_values("date").reset_index(drop=True)
    return {
        "full": metrics_from_out(o),
        "l50": metrics_from_out(o.tail(LAST50)),
        "l30": metrics_from_out(o.tail(LAST30)),
    }


def _row(label: str, w: dict) -> str:
    f, l5, l3 = w["full"], w["l50"], w["l30"]
    return (
        f"{label:<30} "
        f"FULL O/H/M={f.n_open}/{f.n_hedge}/{f.n_monitor} act={f.actionable_pct:>4}% "
        f"acc={f.dir_acc}%({f.n_committed_scored}) Σ={f.sigma:>6.1f}  |  "
        f"L50 act={l5.actionable_pct:>4}% acc={l5.dir_acc}%({l5.n_committed_scored}) Σ={l5.sigma:>5.1f}  |  "
        f"L30 act={l3.actionable_pct:>4}% acc={l3.dir_acc}%({l3.n_committed_scored}) Σ={l3.sigma:>5.1f}"
    )


def _label(cfg, disp_rel, regime) -> str:
    ra = "off" if not cfg.use_running_acc else f"{cfg.tau_run:g}"
    tr = (
        "off" if not cfg.use_trend_conflict else f"{cfg.tau_trend:g}/{cfg.trend_window}"
    )
    dp = "off" if not cfg.use_cluster_dispersion else f"rel{disp_rel:g}"
    rg = "off" if regime is None else f"{regime:g}"
    return f"ra={ra} tr={tr} disp={dp} rg={rg}"


def main() -> None:
    cache, votes, series, cmap = load_cache()
    ddf = build_decisions_df(cache, series)
    cfg0, ct0, rt0 = load_prod_config()

    def run(cfg, disp_rel, regime):
        _, out = evaluate(
            ddf,
            votes,
            series,
            cmap,
            wrapper_config=cfg,
            compass_threshold=disp_rel,
            regime_threshold=regime,
        )
        return _windows(out)

    R = dataclasses.replace
    # ---- anchors ----
    print("=== ANCHORS ===")
    print(_row("baseline (prod)", run(cfg0, ct0, rt0)))
    print(_row("C1 regime OFF", run(cfg0, ct0, None)))
    print(
        _row("C3 regime+trend OFF", run(R(cfg0, use_trend_conflict=False), ct0, None))
    )

    # ---- broad grid ----
    ra_opts = [("off", R(cfg0, use_running_acc=False))] + [
        (f"{t:g}", R(cfg0, use_running_acc=True, tau_run=t))
        for t in (0.40, 0.50, 0.5931, 0.65)
    ]
    tr_opts = [("off", {"use_trend_conflict": False})] + [
        (f"{t:g}", {"use_trend_conflict": True, "tau_trend": t})
        for t in (0.02, 0.03, 0.04, 0.05)
    ]
    disp_opts = [("off", {"use_cluster_dispersion": False}, 0.0)] + [
        (f"rel{r:g}", {"use_cluster_dispersion": True}, r) for r in (0.0, 0.40, 0.60)
    ]
    regime_opts = [None, 0.80, 0.90, 0.95]

    results = []
    for _ra_l, ra_cfg in ra_opts:
        for _tr_l, tr_over in tr_opts:
            for _dp_l, dp_over, dp_rel in disp_opts:
                for rg in regime_opts:
                    cfg = R(ra_cfg, **tr_over, **dp_over)
                    w = run(cfg, dp_rel, rg)
                    results.append((_label(cfg, dp_rel, rg), cfg, dp_rel, rg, w))

    base = run(cfg0, ct0, rt0)
    base_full_acc = base["full"].dir_acc
    base_l50_acc = base["l50"].dir_acc

    def guardrail(w) -> bool:
        # accuracy ≥ current on full AND recent (allow tiny slack), and some recent activity
        return (
            w["full"].dir_acc >= base_full_acc - 1
            and (pd.isna(w["l50"].dir_acc) or w["l50"].dir_acc >= base_l50_acc - 1)
            and w["l50"].n_open + w["l50"].n_hedge >= 5
        )

    print(
        f"\n=== TOP by RECENT (L50) Σ — guardrail: full_acc≥{base_full_acc - 1} & L50_acc≥{base_l50_acc - 1} & L50 active≥5 ==="
    )
    kept = [r for r in results if guardrail(r[4])]
    for r in sorted(kept, key=lambda x: -x[4]["l50"].sigma)[:15]:
        print(_row(r[0], r[4]))
    print(f"(kept {len(kept)}/{len(results)})")

    print("\n=== TOP by FULL Σ (guardrail same) ===")
    for r in sorted(kept, key=lambda x: -x[4]["full"].sigma)[:12]:
        print(_row(r[0], r[4]))

    print("\n=== MOST ACTIVE with L50 acc ≥ baseline (ranked by L50 activity) ===")
    active = [
        r
        for r in results
        if not pd.isna(r[4]["l50"].dir_acc)
        and r[4]["l50"].dir_acc >= base_l50_acc
        and r[4]["full"].dir_acc >= base_full_acc - 3
    ]
    for r in sorted(active, key=lambda x: -x[4]["l50"].actionable_pct)[:12]:
        print(_row(r[0], r[4]))


if __name__ == "__main__":
    main()

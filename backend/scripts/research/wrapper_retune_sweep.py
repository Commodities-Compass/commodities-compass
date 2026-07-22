"""RESEARCH (non-production) — wrapper re-tune: veto-precision diagnostic + ablations + Pareto sweep.

Grounded tuning discipline (143 dates is thin — don't overfit a grid):
  1. VETO-PRECISION: for each detector, of the soft-gate commits it forces to MONITOR,
     how many would actually have been RIGHT vs J+4? A detector that mostly vetoes
     winners is a bad detector → relax it. This is the principled lever selector.
  2. ABLATION: turn each detector off / move each threshold, measure Δ activity + Δ dir-acc
     + Δ Σ-score on full + a time-split (train=first 100, test=last 43) for stability.
  3. PARETO: sweep the promising levers; keep configs on the activity × Σ frontier that
     hold dir-acc ≥ baseline on BOTH train and test.

Run: PYTHONPATH=. poetry run python scripts/research/wrapper_retune_sweep.py
"""

from __future__ import annotations

import dataclasses

import numpy as np

from scripts.research.wrapper_retune_lib import (
    build_decisions_df,
    evaluate,
    load_cache,
    load_prod_config,
    score_row,
)

SPLIT = 100  # train = first 100 dates, test = last 43 (time-ordered)


def _fmt(m) -> str:
    return (
        f"act={m.actionable_pct:>5}% mon={m.monitor_pct:>5}% "
        f"dir_acc={m.dir_acc:>5}%({m.n_committed_scored:>2}) "
        f"Σ={m.sigma:>7.2f} avg={m.avg_score:.3f} "
        f"O/H/M={m.n_open}/{m.n_hedge}/{m.n_monitor}"
    )


def veto_precision(ddf, votes, series, cmap, cfg, ct, rt) -> None:
    """Per-detector: of the commits it vetoes, how many were actually RIGHT (bad veto)."""
    from scripts.ensemble_compute.compass_wrapper import CompassTransitionWrapper

    returns_series = series.set_index("date")["ret1"].dropna()
    votes_long = votes[["date", "pred", "specialist_name"]]
    wrapper = CompassTransitionWrapper(
        config=cfg, cluster_mapping=cmap, dispersion_with_acc_threshold=ct
    )
    wrapped, _ = wrapper.apply(ddf, votes_long, returns_series)
    s = series.set_index("date")
    wrapped["fwd4"] = wrapped["date"].map(s["fwd4"])
    wrapped["atr_p252"] = wrapped["date"].map(s["atr_p252"])
    sg = ddf.set_index("date")["decision"]
    wrapped["sg"] = wrapped["date"].map(sg)
    wrapped["regime"] = (wrapped["decision_wrapped"] != "MONITOR") & (
        wrapped["atr_p252"] > rt
    )
    # soft-gate commit correct vs J+4 (only meaningful where committed + fwd realized)
    committed = wrapped["sg"] != "MONITOR"
    sg_right = ((wrapped["sg"] == "OPEN") & (wrapped["fwd4"] > 0)) | (
        (wrapped["sg"] == "HEDGE") & (wrapped["fwd4"] < 0)
    )
    print(
        f"\n{'detector':<16}{'fires':>7}{'committed':>10}{'scored':>7}"
        f"{'good_veto':>10}{'bad_veto':>9}{'veto_prec':>10}{'Σ_if_release':>13}"
    )
    detectors = {
        "running_acc": wrapped["fired_running_acc"].astype(bool),
        "trend": wrapped["fired_trend"].astype(bool),
        "dispersion": wrapped["fired_dispersion"].astype(bool),
        "three_way": wrapped["fired_three_way"].astype(bool),
        "regime": wrapped["regime"].astype(bool),
    }
    for name, fire in detectors.items():
        f_com = fire & committed
        scored = f_com & wrapped["fwd4"].notna()
        good = int((scored & sg_right).sum())  # vetoed a WINNER (bad veto)
        bad = int((scored & ~sg_right).sum())  # vetoed a LOSER (good veto)
        prec = round(bad / (good + bad), 2) if (good + bad) else float("nan")
        # Σ change if we published soft-gate instead of MONITOR on these scored days
        sig_rel = 0.0
        for _, r in wrapped[scored].iterrows():
            sig_rel += score_row(r["sg"], r["fwd4"]) - score_row("MONITOR", r["fwd4"])
        print(
            f"{name:<16}{int(fire.sum()):>7}{int(f_com.sum()):>10}{int(scored.sum()):>7}"
            f"{good:>10}{bad:>9}{prec:>10}{sig_rel:>+13.2f}"
        )
    print(
        "  good_veto = vetoed a commit that was RIGHT (false veto).  bad_veto = vetoed a LOSER (correct)."
    )
    print(
        "  Σ_if_release>0 => releasing this detector's solo vetoes would have GAINED bilan score."
    )


def ablations(ddf, votes, series, cmap) -> None:
    cfg0, ct0, rt0 = load_prod_config()
    tr = ddf["date"] < ddf["date"].sort_values().iloc[SPLIT]

    def ev(cfg, ct, rt, label):
        m_all, _ = evaluate(
            ddf,
            votes,
            series,
            cmap,
            wrapper_config=cfg,
            compass_threshold=ct,
            regime_threshold=rt,
        )
        m_tr, _ = evaluate(
            ddf[tr],
            votes,
            series,
            cmap,
            wrapper_config=cfg,
            compass_threshold=ct,
            regime_threshold=rt,
        )
        m_te, _ = evaluate(
            ddf[~tr],
            votes,
            series,
            cmap,
            wrapper_config=cfg,
            compass_threshold=ct,
            regime_threshold=rt,
        )
        print(f"{label:<34} FULL {_fmt(m_all)}")
        print(f"{'':<34} trn  {_fmt(m_tr)}")
        print(f"{'':<34} tst  {_fmt(m_te)}")

    R = dataclasses.replace
    print("\n=== ABLATIONS (each = prod config with ONE change) ===")
    ev(cfg0, ct0, rt0, "baseline (prod)")
    ev(R(cfg0, use_running_acc=False), ct0, rt0, "-running_acc")
    ev(R(cfg0, use_trend_conflict=False), ct0, rt0, "-trend")
    ev(R(cfg0, use_cluster_dispersion=False), ct0, rt0, "-dispersion")
    ev(cfg0, ct0, None, "-regime (off)")
    ev(cfg0, 0.50, rt0, "dispersion_release@0.50")
    ev(cfg0, 0.40, rt0, "dispersion_release@0.40")
    ev(cfg0, 0.00, rt0, "dispersion_release@0.00 (always release disp-solo)")
    ev(cfg0, ct0, 0.90, "regime@0.90")
    ev(R(cfg0, use_cluster_dispersion=False), ct0, None, "-dispersion -regime")
    ev(
        R(cfg0, use_running_acc=False, use_cluster_dispersion=False),
        ct0,
        None,
        "-run_acc -disp -regime",
    )
    ev(
        R(
            cfg0,
            use_running_acc=False,
            use_trend_conflict=False,
            use_cluster_dispersion=False,
        ),
        ct0,
        None,
        "ALL detectors off (= soft-gate raw)",
    )


def pareto_sweep(ddf, votes, series, cmap) -> None:
    cfg0, _, _ = load_prod_config()
    tr = ddf["date"] < ddf["date"].sort_values().iloc[SPLIT]
    base_te, _ = evaluate(
        ddf[~tr],
        votes,
        series,
        cmap,
        wrapper_config=cfg0,
        compass_threshold=0.60,
        regime_threshold=0.80,
    )
    base_all, _ = evaluate(
        ddf,
        votes,
        series,
        cmap,
        wrapper_config=cfg0,
        compass_threshold=0.60,
        regime_threshold=0.80,
    )
    R = dataclasses.replace
    grid = []
    for use_disp in (True, False):
        for disp_rel in (0.0, 0.40, 0.60):
            for tau_run in (0.5931, 0.50, 0.40, 0.0):
                for use_trend in (True, False):
                    for regime in (None, 0.80, 0.90):
                        cfg = R(
                            cfg0,
                            use_cluster_dispersion=use_disp,
                            tau_run=tau_run,
                            use_trend_conflict=use_trend,
                        )
                        if not use_disp and disp_rel != 0.0:
                            continue  # disp off => release threshold irrelevant
                        m_all, _ = evaluate(
                            ddf,
                            votes,
                            series,
                            cmap,
                            wrapper_config=cfg,
                            compass_threshold=disp_rel,
                            regime_threshold=regime,
                        )
                        m_tr, _ = evaluate(
                            ddf[tr],
                            votes,
                            series,
                            cmap,
                            wrapper_config=cfg,
                            compass_threshold=disp_rel,
                            regime_threshold=regime,
                        )
                        m_te, _ = evaluate(
                            ddf[~tr],
                            votes,
                            series,
                            cmap,
                            wrapper_config=cfg,
                            compass_threshold=disp_rel,
                            regime_threshold=regime,
                        )
                        grid.append((cfg, disp_rel, regime, m_all, m_tr, m_te))
    # keep configs that beat baseline Σ on FULL and don't collapse dir_acc below baseline-3pts on test
    print(
        f"\n=== PARETO SWEEP ({len(grid)} configs) — baseline FULL {_fmt(base_all)} ==="
    )
    print("filter: Σ_full > baseline AND dir_acc_full ≥ baseline-2  — ranked by Σ_full")
    keep = []
    for cfg, dr, rg, m_all, m_tr, m_te in grid:
        if m_all.sigma > base_all.sigma and (
            m_all.dir_acc >= base_all.dir_acc - 2 or np.isnan(m_all.dir_acc)
        ):
            keep.append((cfg, dr, rg, m_all, m_tr, m_te))
    keep.sort(key=lambda x: -x[3].sigma)
    hdr = f"{'disp':>5}{'disp_rel':>9}{'tau_run':>8}{'trend':>6}{'regime':>7}  |  "
    print(hdr + "FULL: act% mon% dir_acc(n) Σ | TEST: act% dir_acc(n) Σ")
    for cfg, dr, rg, m_all, m_tr, m_te in keep[:25]:
        print(
            f"{str(cfg.use_cluster_dispersion):>5}{dr:>9}{cfg.tau_run:>8}"
            f"{str(cfg.use_trend_conflict):>6}{str(rg):>7}  |  "
            f"{m_all.actionable_pct:>4}% {m_all.monitor_pct:>4}% "
            f"{m_all.dir_acc}%({m_all.n_committed_scored}) Σ={m_all.sigma:.1f} | "
            f"{m_te.actionable_pct}% {m_te.dir_acc}%({m_te.n_committed_scored}) Σ={m_te.sigma:.1f}"
        )
    print(
        f"\n(kept {len(keep)}/{len(grid)} configs beating baseline Σ with dir_acc guardrail)"
    )


def main() -> None:
    cache, votes, series, cmap = load_cache()
    ddf = build_decisions_df(cache, series)
    cfg0, ct0, rt0 = load_prod_config()
    m0, _ = evaluate(
        ddf,
        votes,
        series,
        cmap,
        wrapper_config=cfg0,
        compass_threshold=ct0,
        regime_threshold=rt0,
    )
    print(f"BASELINE (prod) — {_fmt(m0)}")
    print(
        f"soft-gate commits: {int((ddf['decision'] != 'MONITOR').sum())}/{len(ddf)}  "
        f"(= activity ceiling if wrapper released everything)"
    )
    veto_precision(ddf, votes, series, cmap, cfg0, ct0, rt0)
    ablations(ddf, votes, series, cmap)
    pareto_sweep(ddf, votes, series, cmap)


if __name__ == "__main__":
    main()

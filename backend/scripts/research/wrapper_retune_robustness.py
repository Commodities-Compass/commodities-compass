"""RESEARCH — harden the "regime-MONITOR off" finding: horizon-robustness, temporal
stability, and exactly what the regime lever kills. Big prod-decision change => verify hard.

Run: PYTHONPATH=. poetry run python scripts/research/wrapper_retune_robustness.py
"""

from __future__ import annotations

import dataclasses


from scripts.research.wrapper_retune_lib import (
    build_decisions_df,
    evaluate,
    load_cache,
    load_prod_config,
)


def main() -> None:
    cache, votes, series, cmap = load_cache()
    ddf = build_decisions_df(cache, series)
    cfg0, ct0, rt0 = load_prod_config()

    # ---- 1. HORIZON robustness: baseline vs regime-off across J+3..J+6 ----
    print(
        "=== 1. HORIZON robustness (baseline=regime@0.80 vs candidate=regime OFF) ==="
    )
    print(
        f"{'horizon':>8}{'':>4}{'base act%':>10}{'base acc':>9}{'base Σ':>8}"
        f"{'  ':>4}{'C1 act%':>9}{'C1 acc':>8}{'C1 Σ':>8}{'  Δacc':>7}{'ΔΣ':>8}"
    )
    for k in (3, 4, 5, 6):
        col = f"fwd{k}"
        mb, _ = evaluate(
            ddf,
            votes,
            series,
            cmap,
            wrapper_config=cfg0,
            compass_threshold=ct0,
            regime_threshold=rt0,
            score_col=col,
        )
        mc, _ = evaluate(
            ddf,
            votes,
            series,
            cmap,
            wrapper_config=cfg0,
            compass_threshold=ct0,
            regime_threshold=None,
            score_col=col,
        )
        print(
            f"{'J+' + str(k):>8}{'':>4}{mb.actionable_pct:>9}%{mb.dir_acc:>8}%{mb.sigma:>8.1f}"
            f"{'  ':>4}{mc.actionable_pct:>8}%{mc.dir_acc:>7}%{mc.sigma:>8.1f}"
            f"{mc.dir_acc - mb.dir_acc:>+7.1f}{mc.sigma - mb.sigma:>+8.1f}"
        )
    print("  robust if C1 (regime off) beats baseline acc AND Σ at every horizon.")

    # ---- 2. TEMPORAL stability: monthly, baseline vs regime-off ----
    print("\n=== 2. MONTHLY stability (regime OFF vs baseline) ===")
    _, out_b = evaluate(
        ddf,
        votes,
        series,
        cmap,
        wrapper_config=cfg0,
        compass_threshold=ct0,
        regime_threshold=rt0,
    )
    _, out_c = evaluate(
        ddf,
        votes,
        series,
        cmap,
        wrapper_config=cfg0,
        compass_threshold=ct0,
        regime_threshold=None,
    )
    for tag, out in (("baseline", out_b), ("regime_off", out_c)):
        o = out.dropna(subset=["fwd4"]).copy()
        o["ym"] = o["date"].dt.strftime("%Y-%m")
        rows = []
        for ym, g in o.groupby("ym"):
            com = g[g["published"] != "MONITOR"]
            nsc = len(com)
            acc = (
                ((com["published"] == "OPEN") & (com["fwd4"] > 0))
                | ((com["published"] == "HEDGE") & (com["fwd4"] < 0))
            ).sum()
            rows.append(
                (
                    ym,
                    len(g),
                    nsc,
                    f"{100 * acc / nsc:.0f}%" if nsc else "-",
                    round(g["score"].sum(), 1),
                )
            )
        print(f"  [{tag}]")
        print(
            "    "
            + "  ".join(f"{r[0]}:act{r[2]}/{r[1]} acc{r[3]} Σ{r[4]}" for r in rows)
        )

    # ---- 3. WHAT regime kills: the 30 regime-fired days ----
    print("\n=== 3. Regime-fired days detail (soft-gate commit vs J+4) ===")
    s = series.set_index("date")
    w = out_b.copy()
    w["atr_p252"] = w["date"].map(s["atr_p252"])
    fired = w[w["regime_fired"]].copy()
    fired["sg_right"] = ((fired["soft_gate"] == "OPEN") & (fired["fwd4"] > 0)) | (
        (fired["soft_gate"] == "HEDGE") & (fired["fwd4"] < 0)
    )
    fired["ym"] = fired["date"].dt.strftime("%Y-%m")
    print(
        f"  regime fired {len(fired)} days | soft-gate was RIGHT on {int(fired['sg_right'].sum())} of "
        f"{int(fired['fwd4'].notna().sum())} scored (these are the winners regime killed)"
    )
    by_month = fired.groupby("ym").agg(
        n=("date", "size"),
        killed_winners=("sg_right", "sum"),
    )
    print("  by month (n fired / winners killed):")
    print(
        "    "
        + "  ".join(
            f"{ym}:{r.n}/{int(r.killed_winners)}" for ym, r in by_month.iterrows()
        )
    )
    conc = by_month["killed_winners"].max() / max(1, by_month["killed_winners"].sum())
    print(
        f"  concentration: max-month holds {100 * conc:.0f}% of killed winners "
        f"({'CONCENTRATED (one episode)' if conc > 0.5 else 'SPREAD (not one lucky episode)'})"
    )

    # ---- 4. Candidate summary vs user constraints ----
    print("\n=== 4. CANDIDATE C1 = regime OFF (everything else prod) ===")
    R = dataclasses.replace
    for label, ct, rt, cfg in [
        ("baseline (prod, regime@0.80)", ct0, rt0, cfg0),
        ("C1 regime OFF", ct0, None, cfg0),
        ("C2 regime@0.90 (keep top-vol only)", ct0, 0.90, cfg0),
        ("C3 regime OFF + trend OFF", ct0, None, R(cfg0, use_trend_conflict=False)),
    ]:
        m, _ = evaluate(
            ddf,
            votes,
            series,
            cmap,
            wrapper_config=cfg,
            compass_threshold=ct,
            regime_threshold=rt,
        )
        print(
            f"  {label:<38} O/H/M={m.n_open}/{m.n_hedge}/{m.n_monitor}  "
            f"act={m.actionable_pct}% acc={m.dir_acc}%({m.n_committed_scored}) Σ={m.sigma}"
        )


if __name__ == "__main__":
    main()

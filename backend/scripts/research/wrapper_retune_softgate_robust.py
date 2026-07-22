"""RESEARCH — harden the alpha_macro=0.3 soft-gate finding before recommending it.
Checks: horizon J+3..J+6, monthly stability, OPEN-vs-HEDGE accuracy split (downtrend-beta
control), and the recent trades detail. Big finding on a thin sample => verify hard.

Run: PYTHONPATH=. poetry run python scripts/research/wrapper_retune_softgate_robust.py
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
from scripts.research.wrapper_retune_softgate import PROD_SG, resim_softgate


def _c4():
    wc0, ct0, _ = load_prod_config()
    return dataclasses.replace(wc0, tau_trend=0.05), ct0


def _out_for(cache, votes, series, cmap, sg_cfg, score_col="fwd4"):
    c = resim_softgate(cache, votes, sg_cfg)
    ddf = build_decisions_df(c, series)
    C4, ct0 = _c4()
    _, out = evaluate(
        ddf,
        votes,
        series,
        cmap,
        wrapper_config=C4,
        compass_threshold=ct0,
        regime_threshold=None,
        score_col=score_col,
    )
    return out


def _acc(sub):
    com = sub.dropna(subset=["fwd4"])
    com = com[com["published"] != "MONITOR"]
    if not len(com):
        return float("nan"), 0
    ok = (
        ((com["published"] == "OPEN") & (com["fwd4"] > 0))
        | ((com["published"] == "HEDGE") & (com["fwd4"] < 0))
    ).sum()
    return round(100 * ok / len(com), 1), len(com)


def main() -> None:
    cache, votes, series, cmap = load_cache()
    prod = PROD_SG
    cand = dataclasses.replace(PROD_SG, alpha_macro=0.3, commit_threshold=0.15)

    # 1. horizon
    print("=== 1. HORIZON (prod α=0.9 vs cand α=0.3/c0.15, C4 wrapper) ===")
    print(
        f"{'H':>4}{'prod acc':>10}{'prod Σ':>8}{'cand acc':>10}{'cand Σ':>8}{'Δacc':>7}"
    )
    for k in (3, 4, 5, 6):
        col = f"fwd{k}"
        op = _out_for(cache, votes, series, cmap, prod, col)
        oc = _out_for(cache, votes, series, cmap, cand, col)
        mp, mc = metrics_from_out(op), metrics_from_out(oc)
        print(
            f"J+{k:<2}{mp.dir_acc:>10}{mp.sigma:>8.1f}{mc.dir_acc:>10}{mc.sigma:>8.1f}{mc.dir_acc - mp.dir_acc:>+7.1f}"
        )

    # 2. monthly
    print("\n=== 2. MONTHLY (published acc, C4 wrapper) ===")
    for tag, cfg in (("prod α0.9", prod), ("cand α0.3", cand)):
        out = _out_for(cache, votes, series, cmap, cfg)
        out["ym"] = out["date"].dt.strftime("%Y-%m")
        parts = []
        for ym, g in out.groupby("ym"):
            acc, n = _acc(g)
            parts.append(f"{ym}:{n}t {acc}%")
        print(f"  {tag}: " + "  ".join(parts))

    # 3. OPEN vs HEDGE accuracy (downtrend-beta control)
    print("\n=== 3. OPEN vs HEDGE accuracy (beta control) ===")
    for tag, cfg in (("prod α0.9", prod), ("cand α0.3", cand)):
        out = _out_for(cache, votes, series, cmap, cfg).dropna(subset=["fwd4"])
        for side in ("OPEN", "HEDGE"):
            s = out[out["published"] == side]
            if len(s):
                ok = ((s["fwd4"] > 0) if side == "OPEN" else (s["fwd4"] < 0)).sum()
                print(f"  {tag} {side}: {ok}/{len(s)} = {100 * ok / len(s):.0f}%")
        # naive baseline: always-HEDGE accuracy over all scored days
    allscored = _out_for(cache, votes, series, cmap, prod).dropna(subset=["fwd4"])
    hedge_beta = (allscored["fwd4"] < 0).mean()
    print(
        f"  [control] fraction of scored days market FELL (always-HEDGE acc) = {100 * hedge_beta:.0f}%"
    )

    # 4. recent trades detail
    print("\n=== 4. RECENT trades (last 50 sessions, cand α0.3) ===")
    out = _out_for(cache, votes, series, cmap, cand).sort_values("date").tail(50)
    tr = out[out["published"] != "MONITOR"].copy()
    tr["ok"] = ((tr["published"] == "OPEN") & (tr["fwd4"] > 0)) | (
        (tr["published"] == "HEDGE") & (tr["fwd4"] < 0)
    )
    for _, r in tr.iterrows():
        rr = f"{100 * r['fwd4']:+.1f}%" if pd.notna(r["fwd4"]) else "PENDING"
        print(
            f"  {r['date'].date()}  {r['published']:<6} J+4={rr:>8}  {'OK' if r['ok'] else 'WRONG' if pd.notna(r['fwd4']) else '-'}"
        )


if __name__ == "__main__":
    main()

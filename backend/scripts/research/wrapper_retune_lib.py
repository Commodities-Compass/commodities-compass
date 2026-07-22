"""RESEARCH (non-production) — in-memory wrapper re-evaluation harness.

The C5 Compass wrapper is a PURE, NON-RECURSIVE post-process of the soft-gate outputs
(db_loader.py computes the running-acc detector's committed/correct from the SOFT-GATE
decision, never the wrapped one — deliberately, to avoid the self-referencing MONITOR
lock). So we can cache the soft-gate outputs once (wrapper_retune_recompute.py) and
re-evaluate any wrapper/regime config in-memory by calling the REAL
CompassTransitionWrapper.apply() — zero re-implementation of the detectors, zero recompute.

This module:
  - loads the cache (softgate + votes + chained series),
  - rebuilds the exact wrapper inputs (decisions_df / votes_long / returns_series) with
    db_loader's committed/correct semantics (6-session forward on the chained VIEW),
  - reproduces main.py's regime-MONITOR post-step from the causal ATR%-252 percentile,
  - scores the PUBLISHED decision on the bilan §II J+4 grid (same as resimulate_may_to_now).

evaluate(cfg) -> metrics is the fast kernel the sweep calls thousands of times.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np
import pandas as pd
import psycopg2
from ensemble.orchestrator.transition_wrapper import WrapperConfig

from scripts.ensemble_compute.compass_wrapper import CompassTransitionWrapper

DSN = "host=localhost port=5433 dbname=commodities_compass user=postgres password=password"
SCRATCH = "/private/tmp/claude-501/-Users-hediblagui-Developer-work-commodities-compass/7899f171-a6c8-4f83-b792-ca6cafc37aa6/scratchpad"
ALGO_V100 = "84adf719-e8c3-4ad8-83b7-0dfea8b805fc"


# ---------- scoring (bilan §II J+4 grid — identical to resimulate_may_to_now.py) ----------
def score_row(dec: str, r: float) -> float:
    if r is None or (isinstance(r, float) and np.isnan(r)):
        return np.nan
    if dec == "OPEN":
        return 1.25 if r > 0.01 else (1.0 if r > 0 else -2.0 * abs(r))
    if dec == "HEDGE":
        return 1.25 if r < -0.01 else (1.0 if r < 0 else -2.0 * abs(r))
    return 1.0 if abs(r) > 0.01 else (0.75 if abs(r) > 0 else 0.0)


@dataclass(frozen=True)
class Metrics:
    n: int
    n_open: int
    n_hedge: int
    n_monitor: int
    actionable_pct: float
    monitor_pct: float
    dir_acc: float  # directional accuracy on committed (scored) days
    n_committed_scored: int
    sigma: float  # Σ bilan score
    avg_score: float
    fires: dict


# ---------- cache + series ----------
def load_cache() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    cache = pd.read_parquet(f"{SCRATCH}/softgate_cache.parquet")
    votes = pd.read_parquet(f"{SCRATCH}/votes_long.parquet")
    cache["date"] = pd.to_datetime(cache["date"])
    votes["date"] = pd.to_datetime(votes["date"])

    # chained series with atr_14d joined from corrected pl_derived_indicators, so the
    # regime ATR%-percentile matches main.py's market_history exactly.
    with psycopg2.connect(DSN) as con:
        ch = pd.read_sql(
            "SELECT c.date, c.contract_id, c.high, c.low, c.close, pi.atr_14d "
            "FROM v_contract_data_chained c "
            "JOIN pl_derived_indicators pi ON pi.date=c.date AND pi.contract_id=c.contract_id "
            "ORDER BY c.date",
            con,
        )
        cl = pd.read_sql(
            "SELECT parameter_name, value FROM pl_algorithm_config "
            f"WHERE algorithm_version_id='{ALGO_V100}' AND parameter_name LIKE 'cluster\\_%%'",
            con,
        )
    ch["date"] = pd.to_datetime(ch["date"])
    cluster_mapping = {
        r.parameter_name[len("cluster_") :]: r.value for r in cl.itertuples()
    }
    return cache, votes, _build_series(ch), cluster_mapping


def _build_series(ch: pd.DataFrame) -> pd.DataFrame:
    ch = ch.sort_values("date").reset_index(drop=True)
    c = ch["close"].astype(float)
    ch["ret1"] = c.pct_change()
    # positional forward returns on the continuous front-month chain (roll-safe)
    for k in (3, 4, 5, 6):
        ch[f"fwd{k}"] = (
            c.shift(-k) / c - 1.0
        )  # fwd4 = bilan §II scoring; fwd6 = db_loader running-acc
    # ATR%-252 causal percentile — regime lever input (atr_14d matches main.py's market)
    atr_pct = ch["atr_14d"].astype(float) / c
    ch["atr_pct"] = atr_pct
    ch["atr_p252"] = atr_pct.rolling(252, min_periods=60).apply(
        lambda s: float((s <= s.iloc[-1]).mean())
    )
    return ch


def build_decisions_df(cache: pd.DataFrame, series: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct the wrapper input frame with db_loader's committed/correct semantics."""
    s = series.set_index("date")
    d = cache.copy()
    d["fwd6"] = d["date"].map(s["fwd6"])
    d["fwd4"] = d["date"].map(s["fwd4"])
    d["atr_p252"] = d["date"].map(s["atr_p252"])
    d = d.rename(columns={"soft_gate_decision": "decision"})
    # db_loader: committed = soft-gate committed AND the 6th-future chained row exists.
    d["committed"] = (d["decision"] != "MONITOR") & d["fwd6"].notna()
    # correct = soft-gate direction right vs the 6-session forward.
    d["correct"] = ((d["decision"] == "HEDGE") & (d["fwd6"] < 0)) | (
        (d["decision"] == "OPEN") & (d["fwd6"] > 0)
    )
    # the wrapper reads forward_return to recompute correct_wrapped (6-session horizon).
    d["forward_return"] = d["fwd6"]
    return d.sort_values("date").reset_index(drop=True)


# ---------- evaluation kernel ----------
def evaluate(
    decisions_df: pd.DataFrame,
    votes: pd.DataFrame,
    series: pd.DataFrame,
    cluster_mapping: dict,
    *,
    wrapper_config: WrapperConfig,
    compass_threshold: float,
    regime_threshold: float | None,
    score_col: str = "fwd4",
) -> tuple[Metrics, pd.DataFrame]:
    """Run the real Compass wrapper + regime override for one config; score the published signal."""
    returns_series = series.set_index("date")["ret1"].dropna()
    votes_long = votes.rename(columns={"pred": "pred"})[
        ["date", "pred", "specialist_name"]
    ]

    wrapper = CompassTransitionWrapper(
        config=wrapper_config,
        cluster_mapping=cluster_mapping,
        dispersion_with_acc_threshold=compass_threshold,
    )
    wrapped, _diag = wrapper.apply(decisions_df, votes_long, returns_series)

    # regime-MONITOR override (main.py): committed day -> MONITOR when atr%-252 > threshold.
    atr_p = wrapped["date"].map(series.set_index("date")["atr_p252"])
    if regime_threshold is None:
        regime_fired = pd.Series(False, index=wrapped.index)
    else:
        regime_fired = (wrapped["decision_wrapped"] != "MONITOR") & (
            atr_p > float(regime_threshold)
        )
    published = wrapped["decision_wrapped"].where(~regime_fired, "MONITOR")

    fwd4 = wrapped["date"].map(series.set_index("date")[score_col])
    sc = [score_row(dec, r) for dec, r in zip(published, fwd4)]
    out = pd.DataFrame(
        {
            "date": wrapped["date"].values,
            "soft_gate": decisions_df.set_index("date")
            .loc[wrapped["date"], "decision"]
            .values,
            "decision_wrapped": wrapped["decision_wrapped"].values,
            "regime_fired": regime_fired.values,
            "published": published.values,
            "fwd4": fwd4.values,
            "score": sc,
            "fired_running_acc": wrapped["fired_running_acc"].astype(bool).values,
            "fired_trend": wrapped["fired_trend"].astype(bool).values,
            "fired_dispersion": wrapped["fired_dispersion"].astype(bool).values,
        }
    )
    return metrics_from_out(out), out


def metrics_from_out(out: pd.DataFrame) -> Metrics:
    """Compute Metrics over any subset of an evaluate() output frame (the wrapper must be
    run on FULL history first — running_acc needs the trailing context — then sliced here)."""
    published = out["published"]
    scored = out.dropna(subset=["fwd4"])
    committed = scored[scored["published"] != "MONITOR"]
    n_scored = len(committed)
    dir_ok = (
        ((committed["published"] == "OPEN") & (committed["fwd4"] > 0))
        | ((committed["published"] == "HEDGE") & (committed["fwd4"] < 0))
    ).sum()
    n = len(out)
    n_open = int((published == "OPEN").sum())
    n_hedge = int((published == "HEDGE").sum())
    n_mon = int((published == "MONITOR").sum())
    return Metrics(
        n=n,
        n_open=n_open,
        n_hedge=n_hedge,
        n_monitor=n_mon,
        actionable_pct=round(100 * (n_open + n_hedge) / n, 1) if n else float("nan"),
        monitor_pct=round(100 * n_mon / n, 1) if n else float("nan"),
        dir_acc=round(100 * dir_ok / n_scored, 1) if n_scored else float("nan"),
        n_committed_scored=n_scored,
        sigma=round(float(scored["score"].sum()), 2),
        avg_score=round(float(scored["score"].mean()), 4)
        if len(scored)
        else float("nan"),
        fires={
            "running_acc": int(out["fired_running_acc"].sum()),
            "trend": int(out["fired_trend"].sum()),
            "dispersion": int(out["fired_dispersion"].sum()),
            "regime": int(out["regime_fired"].sum()),
        },
    )


_WRAPPER_FIELD_TYPES = {f.name: f.type for f in dataclasses.fields(WrapperConfig)}


def _cast(field: str, raw: str):
    t = _WRAPPER_FIELD_TYPES[field]
    if t is bool or t == "bool":
        return str(raw).strip().lower() in {"1", "1.0", "true", "yes", "on"}
    if t is int or t == "int":
        return int(float(raw))
    if t is float or t == "float":
        return float(raw)
    return raw


def load_prod_config() -> tuple[WrapperConfig, float, float]:
    """Load the ACTUAL shipped v1.0.0 config from pl_algorithm_config (wrapper_* rows +
    compass thresholds) — same source main.py reads. Never hardcode: the prod wrapper is
    already tuned (tau_run=0.5931, running_window=3, trend on, three_way off)."""
    with psycopg2.connect(DSN) as con:
        rows = pd.read_sql(
            "SELECT parameter_name, value FROM pl_algorithm_config "
            f"WHERE algorithm_version_id='{ALGO_V100}' "
            "AND (parameter_name LIKE 'wrapper\\_%%' OR parameter_name LIKE 'compass\\_%%')",
            con,
        )
    kv = dict(zip(rows["parameter_name"], rows["value"]))
    overrides = {
        k[len("wrapper_") :]: _cast(k[len("wrapper_") :], v)
        for k, v in kv.items()
        if k.startswith("wrapper_")
    }
    cfg = dataclasses.replace(WrapperConfig(), **overrides)
    compass_threshold = float(kv["compass_wrapper_dispersion_with_acc_threshold"])
    regime_threshold = float(kv["compass_regime_monitor_atr_pctl"])
    return cfg, compass_threshold, regime_threshold


if __name__ == "__main__":
    cache, votes, series, cmap = load_cache()
    ddf = build_decisions_df(cache, series)
    print(
        f"cache dates={len(cache)}  votes={len(votes)}  chained={len(series)}  clusters={len(cmap)}"
    )
    print(
        f"cluster_mapping winters={sum(1 for v in cmap.values() if v == 'winter')} "
        f"springs={sum(1 for v in cmap.values() if v == 'spring')}"
    )
    wc, ct, rt = load_prod_config()
    print(f"prod config: {wc}  compass_thr={ct}  regime_thr={rt}")
    m, out = evaluate(
        ddf,
        votes,
        series,
        cmap,
        wrapper_config=wc,
        compass_threshold=ct,
        regime_threshold=rt,
    )
    print("\n=== BASELINE (current prod config) reproduced in-memory ===")
    print(
        f"  published: OPEN={m.n_open} HEDGE={m.n_hedge} MONITOR={m.n_monitor}  "
        f"(actionable {m.actionable_pct}%, monitor {m.monitor_pct}%)"
    )
    print(
        f"  wrapped:   MONITOR={(out['decision_wrapped'] == 'MONITOR').sum()} "
        f"HEDGE={(out['decision_wrapped'] == 'HEDGE').sum()} OPEN={(out['decision_wrapped'] == 'OPEN').sum()}"
    )
    print(
        f"  dir_acc={m.dir_acc}% on {m.n_committed_scored} scored committed  Σ={m.sigma}  avg={m.avg_score}"
    )
    print(
        f"  fires: {m.fires}  (DB target: run_acc=61 trend=40 disp=77 three_way=0 regime=30)"
    )
    print(
        "  DB target published: OPEN=9 HEDGE=11 MONITOR=123 | wrapped MONITOR=93 HEDGE=40 OPEN=10"
    )

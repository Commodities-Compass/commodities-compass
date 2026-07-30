"""R&D freezer for the `regime` algorithm v1.0.0.

Two-layer architecture:
  Layer 1 (router)  : causal regime detector — classifies today's market state
                      (bull / bear / transition / high-vol / oversold / overbought)
                      from trailing features only (no look-ahead).
  Layer 2 (specialists): one classifier per condition, each trained on ALL 10y of
                      its condition, predicting the sign of the next trading day (J+1).

Produces frozen/ + manifest.json (SHA-256 + provenance per artifact). Deterministic:
re-running with the same DATA_CUTOFF yields byte-identical model artifacts (seed=42).

Usage:
  DATA_CUTOFF=2026-07-27 python tools/freeze_regime.py
"""
from __future__ import annotations
import hashlib, json, os, pickle, platform, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
import sklearn, scipy, lightgbm  # noqa: F401  (recorded in lib_versions)

SEED = 42
ALGO_NAME, ALGO_VERSION, HORIZON = "regime", "1.0.0", "J+1"
REPO = Path("/Users/hediblagui/Developer/work/RnD_Compass")
PKG = Path(__file__).resolve().parents[1]
FROZEN = PKG / "frozen"
DATASET = REPO / "output/rd_extract/cocoa_rd_dataset_20260727.csv"
CUTOFF = os.environ.get("DATA_CUTOFF", "2026-07-27")

FEATS = ["macd","macd_signal","rsi_14d","atr_14d","stochastic_d_14","close_pivot_ratio",
         "volume_oi_ratio","daily_return","bollinger_width","trend20","trend60","vol20"]

# Router thresholds (causal). K scales the trend band by trailing vol. RSI/ATR extremes.
ROUTER = {
    "trend_band_k": 0.8, "trend_window": 20, "trend_confirm_window": 60,
    "vol_window": 20, "rsi_oversold": 35.0, "rsi_overbought": 65.0,
    "atr_high_pctile": 0.67,
    # priority: most-specific/extreme first; every day resolves to exactly one specialist
    "priority": ["oversold","overbought","highvol","bull","bear","transition"],
    "note": "regime from trailing trend vs vol band; bull needs trend20>+band AND trend60>0; "
            "bear trend20<-band; else transition. oversold/overbought/highvol override by RSI/ATR.",
}

def _sha(b: bytes) -> str: return hashlib.sha256(b).hexdigest()
def _git_sha() -> str:
    try: return subprocess.check_output(["git","-C",str(REPO),"rev-parse","HEAD"]).decode().strip()
    except Exception: return "unknown"

def classify_regime(df: pd.DataFrame) -> pd.DataFrame:
    """Causal regime labels from trailing trend vs a vol-scaled band (same logic the live router uses)."""
    r = df["daily_return"].fillna(0.0)
    idx = (1 + r).cumprod()
    tw, cw, vw, K = ROUTER["trend_window"], ROUTER["trend_confirm_window"], ROUTER["vol_window"], ROUTER["trend_band_k"]
    df = df.assign(idx=idx,
                   trend20=idx / idx.shift(tw) - 1,
                   trend60=idx / idx.shift(cw) - 1,
                   vol20=r.rolling(vw).std() * np.sqrt(252))
    band = K * df["vol20"] * np.sqrt(tw / 252)
    df["regime"] = np.where(df.trend20 < -band, "bear",
                     np.where((df.trend20 > band) & (df.trend60 > 0), "bull", "transition"))
    return df

def load() -> pd.DataFrame:
    df = pd.read_csv(DATASET, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    df = df[df["date"] <= pd.Timestamp(CUTOFF)].reset_index(drop=True)
    df = classify_regime(df)
    df["fwd1"] = df["idx"].shift(-1) / df["idx"] - 1
    df["y"] = (df["fwd1"] > 0).astype(int)
    return df.dropna(subset=FEATS + ["fwd1","regime"]).reset_index(drop=True)

def conditions(d: pd.DataFrame) -> dict[str, pd.Series]:
    atr_hi = d["atr_14d"].quantile(ROUTER["atr_high_pctile"])
    return {
        "bull": d.regime == "bull", "bear": d.regime == "bear", "transition": d.regime == "transition",
        "highvol": d.atr_14d > atr_hi, "oversold": d.rsi_14d < ROUTER["rsi_oversold"],
        "overbought": d.rsi_14d > ROUTER["rsi_overbought"],
    }

def make_model():
    return HistGradientBoostingClassifier(max_depth=3, max_iter=200, learning_rate=0.05,
        l2_regularization=1.0, min_samples_leaf=25, random_state=SEED)

def main() -> int:
    d = load()
    conds = conditions(d)
    artifacts = []
    lib_versions = {"python": platform.python_version(), "scikit-learn": sklearn.__version__,
                    "scipy": scipy.__version__, "lightgbm": lightgbm.__version__, "numpy": np.__version__,
                    "pandas": pd.__version__}
    print(f"[freeze-regime] dataset -> {CUTOFF}, n={len(d)} rows")
    for name, mask in conds.items():
        tr = d[mask].reset_index(drop=True)
        if len(tr) < 30:
            print(f"  SKIP {name}: only {len(tr)} rows (< 30 guard)"); continue
        if tr.y.nunique() < 2:
            raise SystemExit(f"single-class labels for {name!r} — stop & escalate (do not shrink)")
        m = make_model(); m.fit(tr[FEATS], tr.y)
        blob = pickle.dumps(m, protocol=pickle.HIGHEST_PROTOCOL)
        (FROZEN/"specialist_models"/f"{name}.pkl").write_bytes(blob)
        hp = {"name": name, "model": "HistGradientBoostingClassifier",
              "params": m.get_params(), "features": FEATS, "target": "sign(fwd1)", "seed": SEED}
        hpb = json.dumps(hp, indent=2, default=str).encode()
        (FROZEN/"specialist_hps"/f"{name}.json").write_bytes(hpb)
        bal = tr.y.value_counts(normalize=True).to_dict()
        artifacts += [
            {"artifact_kind":"regime_specialist_model","artifact_name":name,"file":f"specialist_models/{name}.pkl",
             "sha256":_sha(blob),"n_bytes":len(blob),"payload_encoding":"pickle_highest",
             "fit_train_start":str(tr.date.min().date()),"fit_train_end":str(tr.date.max().date()),
             "n_train":int(len(tr)),"class_balance":{"UP":round(float(bal.get(1,0)),4),"DOWN":round(float(bal.get(0,0)),4)}},
            {"artifact_kind":"regime_specialist_hp","artifact_name":name,"file":f"specialist_hps/{name}.json",
             "sha256":_sha(hpb),"n_bytes":len(hpb),"payload_encoding":"json"},
        ]
        print(f"  froze {name:12s} n_train={len(tr):5d}  UP={bal.get(1,0):.3f}  sha={_sha(blob)[:10]}")
    # router config (bake in the absolute ATR threshold so live routing matches training)
    atr_high_value = float(d["atr_14d"].quantile(ROUTER["atr_high_pctile"]))
    router_out = {**ROUTER, "atr_high_value": round(atr_high_value, 4)}
    rb = json.dumps(router_out, indent=2).encode()
    (FROZEN/"router"/"regime_router.json").write_bytes(rb)
    artifacts.append({"artifact_kind":"regime_router","artifact_name":"causal_router","file":"router/regime_router.json",
                      "sha256":_sha(rb),"n_bytes":len(rb),"payload_encoding":"json"})
    # canonical snapshot (reference rows for train/serve parity checks)
    snap = d[["date"]+FEATS+["regime","fwd1"]].tail(120)
    snp = FROZEN/"canonical_snapshot"/"reference_tail_120.parquet"
    snap.to_parquet(snp, index=False)
    sb = snp.read_bytes()
    artifacts.append({"artifact_kind":"canonical_snapshot","artifact_name":"reference_tail_120","file":"canonical_snapshot/reference_tail_120.parquet",
                      "sha256":_sha(sb),"n_bytes":len(sb),"payload_encoding":"parquet"})
    manifest = {
        "algorithm_version": ALGO_VERSION, "algorithm_version_name": ALGO_NAME,
        "manifest_version":"1.0","horizon":HORIZON,"data_source":"rd_local","data_cutoff":CUTOFF,
        "seed":SEED,"git_sha":_git_sha(),"lib_versions":lib_versions,
        "created_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "router_features":FEATS,"artifacts":artifacts,
    }
    (FROZEN/"manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"[freeze-regime] wrote manifest.json ({len(artifacts)} artifacts, "
          f"{sum(1 for a in artifacts if a['artifact_kind']=='regime_specialist_model')} specialists)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

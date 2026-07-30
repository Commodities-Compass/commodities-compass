"""Verification gates for the regime v1.0.0 pack.

  1. inventory  — manifest present, every file on disk, SHA-256 matches
  2. repro      — re-freeze to a temp dir; specialist model SHAs are byte-identical
  3. imports    — the regime package imports cleanly
  4. smoke      — RegimePipeline.from_frozen(...).decide(...) returns a valid decision
                  for a recent real trading day

Exit 0 iff all gates pass.
"""
from __future__ import annotations
import hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path
import pandas as pd

PKG = Path(__file__).resolve().parents[1]
REPO = Path("/Users/hediblagui/Developer/work/RnD_Compass")
PY = str(REPO / ".venv/bin/python")
sys.path.insert(0, str(PKG))


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def gate_inventory() -> None:
    m = json.loads((PKG / "frozen/manifest.json").read_text())
    for e in m["artifacts"]:
        f = PKG / "frozen" / e["file"]
        assert f.exists(), f"missing {e['file']}"
        assert sha(f) == e["sha256"], f"SHA mismatch {e['file']}"
    n_spec = sum(1 for e in m["artifacts"] if e["artifact_kind"] == "regime_specialist_model")
    print(f"  [1] inventory OK — {len(m['artifacts'])} artifacts, {n_spec} specialists, all SHA-256 verified")


def gate_repro() -> None:
    with tempfile.TemporaryDirectory() as td:
        for sub in ("specialist_models", "specialist_hps", "router", "canonical_snapshot"):
            (Path(td) / sub).mkdir(parents=True)
        env = {**os.environ, "DATA_CUTOFF": "2026-07-27"}
        # freeze into a copy of the package pointed at the temp frozen dir
        script = (PKG / "tools/freeze_regime.py").read_text().replace(
            'FROZEN = PKG / "frozen"', f'FROZEN = Path("{td}")')
        tf = Path(td) / "freeze_copy.py"; tf.write_text(script)
        subprocess.run([PY, str(tf)], check=True, capture_output=True,
                       env={**env, "PYTHONPATH": str(REPO)})
        a = json.loads((PKG / "frozen/manifest.json").read_text())
        b = json.loads((Path(td) / "manifest.json").read_text())
        sa = {x["artifact_name"]: x["sha256"] for x in a["artifacts"] if x["artifact_kind"] == "regime_specialist_model"}
        sb = {x["artifact_name"]: x["sha256"] for x in b["artifacts"] if x["artifact_kind"] == "regime_specialist_model"}
        match = sum(1 for k in sa if sa[k] == sb.get(k))
        assert match == len(sa), f"NON-DETERMINISTIC: {match}/{len(sa)} specialist SHAs match"
        print(f"  [2] reproducibility OK — {match}/{len(sa)} specialist SHAs byte-identical on re-freeze")


def gate_imports_and_smoke() -> None:
    from regime.pipeline import RegimePipeline
    from regime.data_loader_protocol import DecideRequest
    print("  [3] imports OK — regime package loads")
    pipe = RegimePipeline.from_frozen(PKG / "frozen")
    df = pd.read_csv(REPO / "output/rd_extract/cocoa_rd_dataset_20260727.csv", parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    today = df["date"].iloc[-1]
    hist = df[df["date"] <= today].tail(120)
    dec = pipe.decide(DecideRequest(today=today, contract_id="front", market_history=hist))
    assert dec.decision in ("OPEN", "HEDGE", "MONITOR")
    assert dec.specialist in pipe.specialists or dec.decision == "MONITOR"
    print(f"  [4] smoke OK — decide({today.date()}) = {dec.decision} "
          f"(regime={dec.regime}, specialist={dec.specialist}, P(up)={dec.prob_up:.3f})")


def main() -> int:
    print("verify_regime — gates:")
    gate_inventory(); gate_repro(); gate_imports_and_smoke()
    print("ALL GATES PASS ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""R&D-side freezer — turns 14 top1 Optuna configs into fitted models + manifest.

Bootstrap-only tool: produces the very first ``frozen/`` payload that prod will
load into ``pl_model_artifact``. After day 1, prod's
``cc-ensemble-monthly-retrain`` job re-runs this logic via
``ensemble.retrain.monthly_retrainer.MonthlyRetrainer`` on prod's
``pl_contract_data_daily`` directly. This script is NOT shipped to prod.

Pipeline (deterministic, fail-loud — rule #1):

    1. Resolve env: TRAINING_CUTOFF, OUTPUT_DIR, DATA_SOURCE.
    2. Load canonical 10y dataset via R&D's ``methodology.data_loader`` filtered
       to ``date <= TRAINING_CUTOFF``.
    3. For each of 14 specialists in ``ensemble.optimizer.specialists.SPECIALISTS``:
         a. Read ``output/exp_optim_018c__<name>/top1_config.json``.
         b. Resolve window = max(spec.min_window_months, 12). Per MR-001:
            baseline/TB/calibrated-TB specialists use 12mo; GARCH-using use 24mo.
         c. Slice train = df[(date >= cutoff - window_months) & (date <= cutoff)].
         d. Build candidate via ``MonthlyRetrainer._make_candidate`` (reuses
            ``_build_candidate`` from ``ensemble.optimizer.objective``).
         e. Compute target + sample_weight per architecture; fit.
         f. ``pickle.dumps(candidate, protocol=HIGHEST_PROTOCOL)``.
         g. Write ``frozen/specialist_models/<name>.pkl``.
         h. Copy ``top1_config.json`` to ``frozen/specialist_hps/<name>.json``.
    4. Copy the 5 long-run + tuned-config artifacts from R&D ``output/``:
         - ``output/exp_optim_020/anomaly_veto.pkl``
         - ``output/exp_optim_020/structural_priors.json``
         - ``output/exp_optim_021b/regime_clusters.json``
         - Fold-B params extracted from ``output/exp_optim_022/tuned_configs.json``
           → ``frozen/tuned_configs/soft_gate.json``
         - ``output/exp_optim_025/tuned_config.json``
           → ``frozen/tuned_configs/transition_wrapper.json``
    5. Copy 5 canonical_snapshot reference rows from ``data/db_snapshots/latest/``:
         - ``pl_contract_data_daily.parquet``, ``pl_derived_indicators.parquet``,
           ``pl_article_segment.parquet``, ``ref_contract.parquet``
         - ``output/exp005/regime_tags.csv``
    6. Write ``frozen/manifest.json`` with SHA-256 + provenance per row.

Reproducibility: re-running with the same ``TRAINING_CUTOFF`` MUST produce a
bit-identical ``manifest.json`` (modulo ``created_at`` and ``fit_time_seconds``).
The reproducibility test in ``tests/test_reproducibility.py`` is the binding gate.
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Configuration (env-driven, with locked defaults per the deliverable plan)
# ---------------------------------------------------------------------------
TRAINING_CUTOFF = pd.Timestamp(os.environ.get("TRAINING_CUTOFF", "2026-04-30"))
DATA_SOURCE = os.environ.get("DATA_SOURCE", "rd_local")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_OUTPUT_DIR = _REPO_ROOT / "deliverables" / "campaign5_ensemble_v1.0.0" / "frozen"
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", str(_DEFAULT_OUTPUT_DIR)))

RD_OUTPUT_DIR = _REPO_ROOT / "output"
RD_SNAPSHOT_DIR = _REPO_ROOT / "data" / "db_snapshots" / "latest"
RD_REGIME_TAGS = _REPO_ROOT / "output" / "exp005" / "regime_tags.csv"

ALGORITHM_VERSION_NAME = "ensemble_v1_softgate_wrapper"
ALGORITHM_VERSION = "1.0.1"

SEED = 42

# Per MR-001 (knowledge/established-facts.md): Phase 1 monthly retrain ran
# baseline/TB/calibrated-TB specialists on 12mo, GARCH-using on 24mo. The
# architecture-level ``spec.min_window_months`` is the FLOOR, not the chosen
# value; the freezer picks ``max(floor, 12)`` which respects MR-001 and the
# 24-month GARCH minimum simultaneously.
WINDOW_MONTHS_BASE = 12

# Inserted into ``MEMORY.md``-style 14-row cluster mapping for SQL seed
# generation (Phase 5). Source of truth is
# ``ensemble.orchestrator.transition_wrapper.DEFAULT_CLUSTER_MAPPING`` —
# the freezer emits it into the manifest for cross-checking, but does NOT
# decide it.


# ---------------------------------------------------------------------------
# Provenance helpers
# ---------------------------------------------------------------------------
def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
            stderr=subprocess.STDOUT,
            text=True,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise RuntimeError(f"unable to resolve git sha: {exc}") from exc


def _lib_versions() -> dict[str, str]:
    import lightgbm  # type: ignore
    import scipy  # type: ignore
    import sklearn  # type: ignore
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "scikit-learn": sklearn.__version__,
        "lightgbm": lightgbm.__version__,
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Data loading (R&D-side — methodology.data_loader is NOT in the shipped pkg)
# ---------------------------------------------------------------------------
def _ensure_rd_loader_on_path() -> None:
    """Make sure ``methodology.data_loader`` is importable from this script.

    The freezer runs from within the R&D repo, so the project root contains
    ``methodology/`` alongside the deliverable. Add it to sys.path defensively
    in case the script is invoked from elsewhere.
    """
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))


def load_canonical_dataset(cutoff: pd.Timestamp, horizon: int) -> pd.DataFrame:
    """Load the R&D canonical dataset filtered to ``date <= cutoff``.

    Adds ``forward_return_<H>d`` columns for every specialist horizon (not just
    the base ``horizon`` arg). MR-001 mixes h=6 and h=22 across the 14
    specialists; baseline-target specialists call ``compute_3class_target``
    which reads ``forward_return_{spec.horizon}d`` directly.
    """
    if DATA_SOURCE != "rd_local":
        raise NotImplementedError(
            f"DATA_SOURCE={DATA_SOURCE!r} not supported; the freezer is "
            "rd_local-only by design (see plan §3.3)."
        )
    _ensure_rd_loader_on_path()
    from methodology import data_loader  # type: ignore

    df = data_loader.load_dataset(horizon=horizon)
    df = df[df["date"] <= cutoff].reset_index(drop=True)
    if df.empty:
        raise RuntimeError(
            f"empty dataset after filtering date <= {cutoff.date()}; "
            f"check the R&D Parquet snapshot at {RD_SNAPSHOT_DIR}"
        )
    # Add forward_return columns for every horizon the registry references.
    # Same formula as R&D's methodology/data_loader.py:62.
    from ensemble.optimizer.specialists import SPECIALISTS

    extra_horizons = {int(spec.horizon) for spec in SPECIALISTS} - {horizon}
    for h in sorted(extra_horizons):
        col = f"forward_return_{h}d"
        if col not in df.columns:
            df[col] = (df["close"].shift(-h) - df["close"]) / df["close"]
    return df


# ---------------------------------------------------------------------------
# Specialist freezing
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FitResult:
    name: str
    window_months: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    n_train: int
    class_balance: dict[str, float]
    fit_time_seconds: float
    pickle_bytes: bytes
    sha256: str
    top1_config_json: str


def _resolve_window_months(spec: Any) -> int:
    """Choose the freezer training window per MR-001."""
    return max(int(spec.min_window_months), WINDOW_MONTHS_BASE)


def _slice_train(df: pd.DataFrame, cutoff: pd.Timestamp, window_months: int) -> pd.DataFrame:
    train_start = cutoff - pd.DateOffset(months=window_months)
    train = df[(df["date"] > train_start) & (df["date"] <= cutoff)].reset_index(drop=True)
    if len(train) < 30:
        raise RuntimeError(
            f"training slice too thin: n={len(train)} for "
            f"window [{train_start.date()}, {cutoff.date()}]"
        )
    return train


def fit_one_specialist(
    spec: Any,
    df: pd.DataFrame,
    *,
    cutoff: pd.Timestamp,
) -> FitResult:
    """Fit a single specialist on its MR-001-mandated rolling window."""
    from ensemble.retrain.monthly_retrainer import MonthlyRetrainer

    top1_path = RD_OUTPUT_DIR / f"exp_optim_018c__{spec.name}" / "top1_config.json"
    if not top1_path.exists():
        raise FileNotFoundError(f"missing top1_config.json for {spec.name}: {top1_path}")
    top1_json = top1_path.read_text()

    retrainer = MonthlyRetrainer.from_top1_path(spec, top1_path)
    window_months = _resolve_window_months(spec)
    train = _slice_train(df, cutoff, window_months)

    y_train = retrainer._resolve_target(train)
    n_classes = int(pd.Series(y_train).nunique())
    if n_classes < 2:
        present = sorted(pd.Series(y_train).unique().tolist())
        raise RuntimeError(
            f"degenerate labels for {spec.name!r} on window={window_months}mo, "
            f"cutoff={cutoff.date()}: only {present!r} present."
        )
    balance = MonthlyRetrainer._class_balance(y_train)

    sw_fn, _ = retrainer._resolve_sample_weight_fn(window_months=window_months)
    sw = sw_fn(train, y_train) if sw_fn is not None else None

    cand = retrainer._make_candidate()
    t0 = time.perf_counter()
    if sw is not None:
        try:
            cand.fit(train, y_train, sample_weight=sw)
        except (TypeError, ValueError) as exc:
            if "sample_weight" in str(exc):
                cand.fit(train, y_train)
            else:
                raise
    else:
        cand.fit(train, y_train)
    fit_time = time.perf_counter() - t0

    pickle_bytes = pickle.dumps(cand, protocol=pickle.HIGHEST_PROTOCOL)
    return FitResult(
        name=spec.name,
        window_months=window_months,
        train_start=train["date"].min(),
        train_end=train["date"].max(),
        n_train=int(len(train)),
        class_balance=balance,
        fit_time_seconds=float(fit_time),
        pickle_bytes=pickle_bytes,
        sha256=_sha256(pickle_bytes),
        top1_config_json=top1_json,
    )


# ---------------------------------------------------------------------------
# Long-run artifact copy
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CopyResult:
    name: str
    payload: bytes
    sha256: str
    payload_encoding: str  # 'pickle' | 'json-utf8' | 'parquet' | 'csv-utf8'


def _read_bytes(path: Path) -> bytes:
    if not path.exists():
        raise FileNotFoundError(f"expected file missing: {path}")
    return path.read_bytes()


def _copy_long_run(src: Path, encoding: str, name: str) -> CopyResult:
    data = _read_bytes(src)
    return CopyResult(name=name, payload=data, sha256=_sha256(data), payload_encoding=encoding)


def _extract_fold_b_softgate() -> CopyResult:
    """Soft-gate config artifact (name kept ``softgate_v1_foldB`` so the loader resolves it).

    v1.0.1: sources the VOL-STRATIFIED retune (WS-2, EXP-OPTIM-022b) — the 4 scalars
    incl. ``alpha_macro<=0.9`` that dissolved the 2026-05 unanimous-HEDGE collapse.
    Falls back to the v1.0.0 Fold-B config only if the retune output is absent.
    """
    keys = ("alpha_macro", "alpha_prior", "alpha_anomaly", "commit_threshold")
    src_v101 = RD_OUTPUT_DIR / "exp_optim_022b" / "tuned_config.json"
    if src_v101.exists():
        cfg = json.loads(src_v101.read_text())
        missing = [k for k in keys if k not in cfg]
        if missing:
            raise RuntimeError(f"{src_v101} missing soft-gate keys {missing}")
        payload = json.dumps({k: cfg[k] for k in sorted(keys)}, indent=2, sort_keys=True).encode("utf-8")
        return CopyResult(name="softgate_v1_foldB", payload=payload,
                          sha256=_sha256(payload), payload_encoding="json-utf8")

    src = RD_OUTPUT_DIR / "exp_optim_022" / "tuned_configs.json"
    raw = json.loads(src.read_text())
    fold_b = raw.get("fold_B_for_april", {}).get("params")
    if not fold_b:
        raise RuntimeError(f"missing fold_B_for_april.params in {src}")
    payload = json.dumps(fold_b, indent=2, sort_keys=True).encode("utf-8")
    return CopyResult(
        name="softgate_v1_foldB",
        payload=payload,
        sha256=_sha256(payload),
        payload_encoding="json-utf8",
    )


# ---------------------------------------------------------------------------
# Output layout writers
# ---------------------------------------------------------------------------
def _write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _ensure_clean_output() -> None:
    """Reset the frozen/ tree so re-running the freezer yields a deterministic layout.

    Reproducibility test relies on stable file membership; leaving stale files
    from a prior run would silently inflate the manifest.
    """
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    for sub in ("specialist_models", "specialist_hps", "long_run", "tuned_configs", "canonical_snapshot"):
        (OUTPUT_DIR / sub).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def main() -> int:
    np.random.seed(SEED)
    _ensure_clean_output()
    _ensure_rd_loader_on_path()

    from ensemble.optimizer.specialists import SPECIALISTS
    from ensemble.orchestrator.transition_wrapper import DEFAULT_CLUSTER_MAPPING

    # Use horizon=6 (matches the canonical R&D dataset; specialist-specific
    # horizons are resolved internally via target_fn / target_kwargs).
    df = load_canonical_dataset(TRAINING_CUTOFF, horizon=6)
    print(f"[freezer] loaded {len(df):,} rows up to {TRAINING_CUTOFF.date()}")

    git_sha = _git_sha()
    lib_versions = _lib_versions()
    training_month = f"{TRAINING_CUTOFF.year:04d}-{TRAINING_CUTOFF.month:02d}"

    manifest: dict[str, Any] = {
        "manifest_version": "1.0",
        "algorithm_version_name": ALGORITHM_VERSION_NAME,
        "algorithm_version": ALGORITHM_VERSION,
        "training_cutoff": TRAINING_CUTOFF.strftime("%Y-%m-%d"),
        "training_month": training_month,
        "data_source": DATA_SOURCE,
        "git_sha": git_sha,
        "lib_versions": lib_versions,
        "seed": SEED,
        "cluster_mapping": dict(DEFAULT_CLUSTER_MAPPING),
        "artifacts": [],
    }

    # 1) Fit 14 specialists -----------------------------------------------------
    specs_sorted = sorted(SPECIALISTS, key=lambda s: s.name)
    for spec in specs_sorted:
        print(f"[freezer] fitting {spec.name} (cluster={spec.cluster}) ...", flush=True)
        result = fit_one_specialist(spec, df, cutoff=TRAINING_CUTOFF)
        model_path = OUTPUT_DIR / "specialist_models" / f"{result.name}.pkl"
        hp_path = OUTPUT_DIR / "specialist_hps" / f"{result.name}.json"
        _write_file(model_path, result.pickle_bytes)
        _write_file(hp_path, result.top1_config_json.encode("utf-8"))
        manifest["artifacts"].append({
            "artifact_kind": "specialist_model",
            "artifact_name": result.name,
            "training_month": training_month,
            "filename": str(model_path.relative_to(OUTPUT_DIR)),
            "payload_encoding": "pickle",
            "sha256": result.sha256,
            "n_bytes": len(result.pickle_bytes),
            "fit_train_start": result.train_start.strftime("%Y-%m-%d"),
            "fit_train_end": result.train_end.strftime("%Y-%m-%d"),
            "n_train": result.n_train,
            "class_balance": result.class_balance,
            "fit_time_seconds": round(result.fit_time_seconds, 3),
            "window_months": result.window_months,
        })
        hp_sha = _sha256(result.top1_config_json.encode("utf-8"))
        manifest["artifacts"].append({
            "artifact_kind": "specialist_hp",
            "artifact_name": result.name,
            "training_month": training_month,
            "filename": str(hp_path.relative_to(OUTPUT_DIR)),
            "payload_encoding": "json-utf8",
            "sha256": hp_sha,
            "n_bytes": len(result.top1_config_json.encode("utf-8")),
        })

    # 2) Long-run artifacts -----------------------------------------------------
    long_run: list[tuple[str, Path, str, str]] = [
        ("long_run_anomaly", RD_OUTPUT_DIR / "exp_optim_020" / "anomaly_veto.pkl",
         "anomaly_veto_10y", "pickle"),
        ("long_run_priors", RD_OUTPUT_DIR / "exp_optim_020" / "structural_priors.json",
         "structural_priors_10y", "json-utf8"),
        ("long_run_regime_clusters", RD_OUTPUT_DIR / "exp_optim_021b" / "regime_clusters.json",
         "regime_clusters_10y", "json-utf8"),
    ]
    for artifact_kind, src, art_name, encoding in long_run:
        copy = _copy_long_run(src, encoding, art_name)
        dst = OUTPUT_DIR / "long_run" / src.name
        _write_file(dst, copy.payload)
        manifest["artifacts"].append({
            "artifact_kind": artifact_kind,
            "artifact_name": copy.name,
            "training_month": None,
            "filename": str(dst.relative_to(OUTPUT_DIR)),
            "payload_encoding": copy.payload_encoding,
            "sha256": copy.sha256,
            "n_bytes": len(copy.payload),
        })

    # 3) Tuned configs ----------------------------------------------------------
    softgate = _extract_fold_b_softgate()
    softgate_path = OUTPUT_DIR / "tuned_configs" / "soft_gate.json"
    _write_file(softgate_path, softgate.payload)
    manifest["artifacts"].append({
        "artifact_kind": "soft_gate_config",
        "artifact_name": softgate.name,
        "training_month": None,
        "filename": str(softgate_path.relative_to(OUTPUT_DIR)),
        "payload_encoding": softgate.payload_encoding,
        "sha256": softgate.sha256,
        "n_bytes": len(softgate.payload),
        "source": str((RD_OUTPUT_DIR / "exp_optim_022" / "tuned_configs.json").relative_to(_REPO_ROOT)),
    })

    wrapper_src = RD_OUTPUT_DIR / "exp_optim_025" / "tuned_config.json"
    wrapper_payload = wrapper_src.read_bytes()
    wrapper_path = OUTPUT_DIR / "tuned_configs" / "transition_wrapper.json"
    _write_file(wrapper_path, wrapper_payload)
    manifest["artifacts"].append({
        "artifact_kind": "wrapper_config",
        "artifact_name": "tpw_v1",
        "training_month": None,
        "filename": str(wrapper_path.relative_to(OUTPUT_DIR)),
        "payload_encoding": "json-utf8",
        "sha256": _sha256(wrapper_payload),
        "n_bytes": len(wrapper_payload),
        "source": str(wrapper_src.relative_to(_REPO_ROOT)),
    })

    # 4) Canonical snapshot (frozen reference data — Hedi 2026-05-20 mandate) --
    snapshot_files: Iterable[tuple[str, Path, str]] = (
        ("pl_contract_data_daily", RD_SNAPSHOT_DIR / "pl_contract_data_daily.parquet", "parquet"),
        ("pl_derived_indicators", RD_SNAPSHOT_DIR / "pl_derived_indicators.parquet", "parquet"),
        ("pl_article_segment", RD_SNAPSHOT_DIR / "pl_article_segment.parquet", "parquet"),
        ("ref_contract", RD_SNAPSHOT_DIR / "ref_contract.parquet", "parquet"),
        ("regime_tags", RD_REGIME_TAGS, "csv-utf8"),
    )
    cutoff_tag = TRAINING_CUTOFF.strftime("%Y-%m-%d")
    for short_name, src, encoding in snapshot_files:
        payload = _read_bytes(src)
        sha = _sha256(payload)
        dst = OUTPUT_DIR / "canonical_snapshot" / src.name
        _write_file(dst, payload)
        manifest["artifacts"].append({
            "artifact_kind": "canonical_snapshot",
            "artifact_name": f"{short_name}_rd_{cutoff_tag}",
            "training_month": None,
            "filename": str(dst.relative_to(OUTPUT_DIR)),
            "payload_encoding": encoding,
            "sha256": sha,
            "n_bytes": len(payload),
            "source": str(src.relative_to(_REPO_ROOT)),
        })

    # 5) Write manifest ---------------------------------------------------------
    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True)
    manifest_path.write_text(manifest_text)
    print(f"[freezer] wrote {manifest_path} ({len(manifest['artifacts'])} artifacts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

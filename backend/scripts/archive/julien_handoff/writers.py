"""Write the handoff bundle: main CSV, auxiliary CSVs, meta.json, dictionary.md.

Output layout (under <out_dir>/):

    cocoa_rd_dataset_YYYYMMDD.csv          — main daily-wide dataset
    cocoa_rd_dataset_YYYYMMDD.meta.json    — provenance + null pct + SHA-256
    cocoa_rd_dataset_YYYYMMDD.dictionary.md — column dictionary

    cocoa_specialist_predictions_YYYYMM.csv
    cocoa_orchestrator_decisions_YYYYMM.csv
    cocoa_signal_components_YYYYMM.csv
    cocoa_article_segments_YYYYMM.csv
    cocoa_fundamental_articles_YYYYMM.csv
    cocoa_weather_observations_YYYYMM.csv
    cocoa_seasonal_scores.csv
    cocoa_sentiment_features_YYYYMM.csv
    compass_algorithm_versions.csv

    README_HANDOFF.md                      — context note for Julien
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Final

import pandas as pd

from .loaders import (
    DERIVED_COLUMNS,
    ENSO_COLUMNS,
    ENSO_LAG_DAYS,
    FX_COLUMNS,
    OHLCV_COLUMNS,
    SENT_FFILL_DAYS,
)


KEY_COLUMNS: Final[list[str]] = ["date", "contract_code", "contract_month"]

COMPASS_SIGNAL_COLUMNS: Final[list[str]] = [
    "compass_composite_score",
    "compass_decision",
    "compass_confidence",
    "compass_direction",
    "compass_momentum",
    "compass_macroeco_bonus",
    "compass_macroeco_score",
]


@dataclass(frozen=True)
class BundlePaths:
    out_dir: Path
    run_stamp: str  # YYYYMMDD
    month_stamp: str  # YYYYMM

    @property
    def main_csv(self) -> Path:
        return self.out_dir / f"cocoa_rd_dataset_{self.run_stamp}.csv"

    @property
    def main_meta(self) -> Path:
        return self.out_dir / f"cocoa_rd_dataset_{self.run_stamp}.meta.json"

    @property
    def main_dict(self) -> Path:
        return self.out_dir / f"cocoa_rd_dataset_{self.run_stamp}.dictionary.md"

    @property
    def readme(self) -> Path:
        return self.out_dir / "README_HANDOFF.md"

    def aux_csv(self, name: str) -> Path:
        return self.out_dir / f"{name}_{self.month_stamp}.csv"

    def aux_csv_static(self, name: str) -> Path:
        return self.out_dir / f"{name}.csv"


# ---------------------------------------------------------------------------
# Validation (mirrors Julien's validate())
# ---------------------------------------------------------------------------


def validate_main_csv(df: pd.DataFrame, *, expected_rows: int | None = None) -> None:
    """Hard checks on the main dataset. Raises AssertionError on violation."""
    assert not df.empty, "main dataset is empty"
    assert df["date"].is_monotonic_increasing, "date not monotonically increasing"
    assert df["date"].is_unique, "duplicate dates"

    if expected_rows is not None:
        assert len(df) == expected_rows, (
            f"row count mismatch: got {len(df)}, expected {expected_rows}"
        )

    # Strict null gates on canonical price/volume columns.
    strict = {"close": 1.0, "high": 2.0, "low": 2.0, "volume": 2.0}
    null_pct = df.isna().mean() * 100
    for col, gate in strict.items():
        pct = null_pct.get(col, 0.0)
        assert pct <= gate, f"{col} null% = {pct:.2f}, exceeds {gate}% gate"


# ---------------------------------------------------------------------------
# Column ordering
# ---------------------------------------------------------------------------


def order_main_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Reorder columns: keys → A → B → C (COT) → D (sent) → bonus → leftovers."""
    a_cols = OHLCV_COLUMNS
    b_cols = DERIVED_COLUMNS
    c_cols = [c for c in df.columns if c.startswith("cot_") or c == "release_date"]
    d_cols = [
        c for c in df.columns if c.startswith("sent_") or c.startswith("n_articles_")
    ]
    bonus_external = [c for c in [*ENSO_COLUMNS, *FX_COLUMNS] if c in df.columns]
    bonus_compass = [c for c in COMPASS_SIGNAL_COLUMNS if c in df.columns]

    used = set(
        KEY_COLUMNS + a_cols + b_cols + c_cols + d_cols + bonus_external + bonus_compass
    )
    leftover = [c for c in df.columns if c not in used]

    ordered = (
        KEY_COLUMNS
        + [c for c in a_cols if c in df.columns]
        + [c for c in b_cols if c in df.columns]
        + c_cols
        + d_cols
        + bonus_external
        + bonus_compass
        + leftover
    )
    seen: set[str] = set()
    deduped = [c for c in ordered if not (c in seen or seen.add(c))]
    return df[deduped]


# ---------------------------------------------------------------------------
# Column dictionary classification
# ---------------------------------------------------------------------------


def _column_source(name: str) -> tuple[str, str]:
    """Return (source, scope) tag matching Julien's dictionary convention."""
    if name in {"date", "contract_code", "contract_month"}:
        return ("key", "[ABSOLUTE]")
    if name.startswith("cot_") or name == "release_date":
        return ("pl_cot_eu_weekly", "[ABSOLUTE]")
    if name.startswith("sent_") or name.startswith("n_articles_"):
        return ("pl_article_segment (pivot)", "[METHOD-TIED]")
    if name in DERIVED_COLUMNS:
        return ("pl_derived_indicators", "[METHOD-TIED]")
    if name in ENSO_COLUMNS:
        return ("pl_external_indicator (ENSO, +14d lag)", "[ABSOLUTE]")
    if name in FX_COLUMNS:
        return ("pl_external_indicator (FX, no lag)", "[ABSOLUTE]")
    if name in COMPASS_SIGNAL_COLUMNS:
        return (
            "pl_indicator_daily (Compass prod-active algo)",
            "[METHOD-TIED]",
        )
    if name in OHLCV_COLUMNS:
        return ("pl_contract_data_daily", "[ABSOLUTE]")
    return ("unknown", "[METHOD-TIED]")


# ---------------------------------------------------------------------------
# File output helpers
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _serialize_csv(df: pd.DataFrame, path: Path) -> None:
    """Write a CSV with deterministic date formatting + JSON-encode dict cols."""
    out = df.copy()
    # Stringify any dict/list (JSONB) columns so to_csv doesn't choke.
    for col in out.columns:
        if (
            out[col].dtype == object
            and out[col].apply(lambda v: isinstance(v, (dict, list))).any()
        ):
            out[col] = out[col].apply(
                lambda v: (
                    json.dumps(v, ensure_ascii=False, sort_keys=True)
                    if isinstance(v, (dict, list))
                    else v
                )
            )
    out.to_csv(path, index=False, date_format="%Y-%m-%d")


def write_main_csv_and_metadata(
    df: pd.DataFrame,
    paths: BundlePaths,
    *,
    window_start: date,
    window_end: date,
    aux_files: list[str],
    algorithm_versions: pd.DataFrame,
) -> str:
    """Write main CSV + meta.json + dictionary.md. Returns the SHA-256."""
    paths.out_dir.mkdir(parents=True, exist_ok=True)
    _serialize_csv(df, paths.main_csv)
    sha = _sha256(paths.main_csv)

    null_pct = (df.isna().mean() * 100).round(2).to_dict()
    null_pct_serializable = {k: float(v) for k, v in null_pct.items()}

    active_algos = (
        algorithm_versions[algorithm_versions["is_active"]][
            ["name", "version", "horizon"]
        ].to_dict(orient="records")
        if not algorithm_versions.empty
        else []
    )

    meta = {
        "dataset": "cocoa_rd_dataset",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_date": paths.run_stamp,
        "delta_window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
        },
        "rows": int(len(df)),
        "cols": int(df.shape[1]),
        "date_min": str(df["date"].min().date()),
        "date_max": str(df["date"].max().date()),
        "sha256": sha,
        "sources": {
            "A_raw_ohlcv": "pl_contract_data_daily (front-month by max volume, tie-break OI)",
            "B_derived_technicals": "pl_derived_indicators (aligned on front-month contract)",
            "C_cot_eu": (
                "pl_cot_eu_weekly (contract_market='cocoa'); "
                "joined on release_date via merge_asof backward (tolerance 14d); "
                "26-week z-scores + percentile computed at write time"
            ),
            "D_sentiment": (
                "pl_article_segment (pivoted long→wide by zone × theme); "
                "filtered on pl_fundamental_article.is_active=TRUE"
            ),
            "BONUS_enso": "pl_external_indicator (NOAA ONI + Niño 3.4, monthly, +14d lag)",
            "BONUS_fx": "pl_external_indicator (ECB DXY proxy + GBPUSD + EURUSD + GBPEUR, daily)",
            "BONUS_compass_signal": (
                "pl_indicator_daily where pl_algorithm_version.is_active=TRUE "
                "(typically the prod-active legacy v1.0.1; C5 ensemble remains "
                "shadow-mode at the time of this snapshot)"
            ),
        },
        "skipped_sources": {
            "E_fundamentals": (
                "Groupe E (Db_Master_Tax + Db_Master_Achats + Bilan_Grainage) "
                "is not in Compass prod DB — already dropped by Julien from "
                "snapshot 20260517. To confirm: rejected R&D signal or oversight?"
            ),
        },
        "lag_policy": {
            "sentiment_ffill_days": SENT_FFILL_DAYS,
            "cot_asof_tolerance_days": 14,
            "enso_lag_days": ENSO_LAG_DAYS,
        },
        "compass_extras": {
            "active_algorithm_versions": active_algos,
            "auxiliary_files": aux_files,
        },
        "null_pct": null_pct_serializable,
    }
    paths.main_meta.write_text(json.dumps(meta, indent=2, sort_keys=True))

    lines = [
        "# Cocoa R&D dataset — column dictionary (Compass handoff)",
        "",
        f"Generated: {meta['generated_at_utc']}",
        f"Rows: {meta['rows']} | Cols: {meta['cols']}",
        f"Date range: {meta['date_min']} → {meta['date_max']}",
        f"SHA-256: `{sha}`",
        "",
        "| Column | Source | Scope | Null % |",
        "|--------|--------|-------|--------|",
    ]
    for col in df.columns:
        src, scope = _column_source(col)
        lines.append(
            f"| `{col}` | {src} | {scope} | {null_pct_serializable.get(col, 0.0):.2f} |"
        )
    paths.main_dict.write_text("\n".join(lines) + "\n")

    return sha


def write_aux_csv(df: pd.DataFrame, path: Path) -> int:
    """Write an auxiliary CSV. Returns the row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _serialize_csv(df, path)
    return len(df)


def write_readme(
    paths: BundlePaths,
    *,
    window_start: date,
    window_end: date,
    main_sha: str,
    aux_summary: dict[str, int],
) -> None:
    """Render the README_HANDOFF.md for Julien."""
    aux_lines = "\n".join(
        f"- `{name}` — {rows} rows" for name, rows in aux_summary.items()
    )
    body = f"""# Compass → Julien R&D handoff — {paths.month_stamp}

Bundle généré le {datetime.now(timezone.utc).isoformat()} depuis la BDD prod
Compass (GCP Cloud SQL via tunnel IAP bastion).

## Périmètre

- **Fenêtre delta**: {window_start.isoformat()} → {window_end.isoformat()}
- **Format**: identique au snapshot `cocoa_rd_dataset_20260512.csv` côté `compass_backtest` (voir `docs/Rnd_Project/JULIEN_DATA_MAP.md`).
- **CSV principal**: `{paths.main_csv.name}` (SHA-256 `{main_sha}`)
- **Métadonnées**: `{paths.main_meta.name}` + `{paths.main_dict.name}`

## Ce qui est inclus

- **Groupe A** (OHLCV + IV + stocks US/EU + COM NET US) — `pl_contract_data_daily`, front-month pické par max-volume.
- **Groupe B** (16 indicateurs techniques) — `pl_derived_indicators`. RSI/ATR en Wilder (corrigé vs Sheets).
- **Groupe C** (COT EU positioning) — `pl_cot_eu_weekly`, jointure `merge_asof backward` sur `release_date` (tolérance 14j). Schéma Compass plus simple que ta référence : pas de `swap_*`, pas de suffixe `_all`. Les z-scores 26w et percentile sont recalculés au write (non persistés en BDD).
- **Groupe D** (Sentiment LLM long→wide par zone × thème) — `pl_article_segment` filtré sur `pl_fundamental_article.is_active=TRUE`. **Zone aujourd'hui = `'all'` uniquement** ; le backfill 10y (segmentation géo) est planifié mais pas exécuté (cf. `P1-press-review-backfill-10y.md`).
- **Bonus ENSO** (ONI + Niño 3.4) — `pl_external_indicator` (NOAA, lag +14j).
- **Bonus FX** (DXY proxy / EURUSD / GBPUSD / GBPEUR) — `pl_external_indicator` (ECB, no lag).
- **Bonus Compass signal** — composite + decision Compass (prod-active algo).

## Ce qui est **skippé**

- **Groupe E** (Db_Master_Tax + Db_Master_Achats + Bilan_Grainage). Pas en BDD prod Compass. Tu l'avais déjà retiré du snapshot 20260517 — peux-tu confirmer : **rejet R&D ou oubli** ? Si c'est rejet, on ferme le sujet ; si oubli, on remonte une migration pour persister les Db_Master_* en prod.

## Couverture historique des nouvelles tables (à savoir)

- `pl_cot_eu_weekly` : live depuis ~mai 2026. Backfill historique 12y est planifié (`P2-scrapers-eu-backfill.md`) mais pas exécuté à ce jour. Pour mai 2026 → ok.
- `pl_article_segment` : accumulation naturelle depuis oct 2025. Sur mai → ok.
- `pl_specialist_prediction` / `pl_orchestrator_decision` : depuis bootstrap C5 mai 2026 (shadow mode, `compute_enabled=FALSE`).
- `pl_external_indicator` : ENSO backfillé 1950+, FX backfillé 2014+.

## Fichiers auxiliaires (long format)

{aux_lines}

## Reproductibilité

- `seed` non utilisé (pas de stochastique dans ce script).
- Re-runs idempotents modulo `generated_at_utc` dans le meta.json. Le SHA-256 du CSV principal doit rester identique pour la même fenêtre.

## Pour réutiliser le script

```bash
# 1. Bastion IAP (lecture seule prod)
gcloud compute ssh cc-bastion --zone europe-west9-a --tunnel-through-iap \\
  --project cacaooo -- -N -L 5434:10.119.160.3:5432

# 2. Run handoff (en local dans le repo Compass)
DATABASE_SYNC_URL='postgresql+psycopg2://cc_app:<pw>@127.0.0.1:5434/commodities_compass' \\
  poetry run julien-handoff --from {window_start.isoformat()} --to {window_end.isoformat()} \\
                            --output ./output/julien_handoff_{paths.month_stamp}
```
"""
    paths.readme.write_text(body)

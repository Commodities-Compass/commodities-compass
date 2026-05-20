"""Ingest NOAA Niño 3.4 SST anomaly + ONI (Oceanic Niño Index) — public free data.

Outputs:
    data/external_data/ENSO/oni_monthly.csv     — date (YYYY-MM-01), oni (3-month mean SST anomaly, °C)
    data/external_data/ENSO/nino34_monthly.csv  — date, sst, anomaly

Source: NOAA PSL (Physical Sciences Laboratory):
    - ONI: https://psl.noaa.gov/data/correlation/oni.data
    - Niño 3.4 monthly anomaly: https://psl.noaa.gov/data/correlation/nina34.anom.data

No authentication required.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd


OUT_DIR = Path("data/external_data/ENSO")
ONI_URL = "https://psl.noaa.gov/data/correlation/oni.data"
NINO34_URL = "https://psl.noaa.gov/data/correlation/nina34.anom.data"


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "compass-research/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


def _parse_psl_text(text: str) -> pd.DataFrame:
    """PSL data format: header line with year range, then rows ``year jan feb ... dec``.
    Trailing rows include a missing-value flag and metadata.
    """
    lines = text.strip().splitlines()
    # Skip the leading header line (first non-empty); collect numeric rows until a non-numeric line.
    rows: list[list[float]] = []
    for ln in lines[1:]:
        toks = ln.split()
        if not toks:
            continue
        # First token should be a 4-digit year
        try:
            year = int(toks[0])
        except ValueError:
            break
        if year < 1900 or year > 2100:
            break
        if len(toks) < 13:
            continue
        try:
            vals = [float(x) for x in toks[1:13]]
        except ValueError:
            continue
        rows.append([year] + vals)
    df = pd.DataFrame(rows, columns=["year"] + [f"m{m:02d}" for m in range(1, 13)])
    # Find missing value flag from the row after data
    missing_val = -99.9
    for ln in lines:
        if "-99.99" in ln or "-99.9" in ln:
            try:
                missing_val = float(ln.split()[0])
                break
            except (ValueError, IndexError):
                pass
    # Reshape to long: year, month, value
    long = df.melt(id_vars=["year"], var_name="month", value_name="value")
    long["month"] = long["month"].str.extract(r"m(\d{2})").astype(int)
    long.loc[np.isclose(long["value"], missing_val), "value"] = np.nan
    long["date"] = pd.to_datetime(
        long["year"].astype(str) + "-" + long["month"].astype(str).str.zfill(2) + "-01"
    )
    return long[["date", "value"]].dropna(subset=["value"]).sort_values("date").reset_index(drop=True)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[ingest_enso] Fetching ONI from {ONI_URL}")
    oni_text = _fetch(ONI_URL)
    oni = _parse_psl_text(oni_text).rename(columns={"value": "oni"})
    oni_path = OUT_DIR / "oni_monthly.csv"
    oni.to_csv(oni_path, index=False)
    print(f"  → {len(oni)} rows ({oni['date'].min().date()} to {oni['date'].max().date()})")

    print(f"[ingest_enso] Fetching Niño 3.4 anomaly from {NINO34_URL}")
    nin_text = _fetch(NINO34_URL)
    nin = _parse_psl_text(nin_text).rename(columns={"value": "nino34_anomaly"})
    nin_path = OUT_DIR / "nino34_monthly.csv"
    nin.to_csv(nin_path, index=False)
    print(f"  → {len(nin)} rows ({nin['date'].min().date()} to {nin['date'].max().date()})")

    print(f"[ingest_enso] DONE. Files in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Merge external time series (ENSO, FX) into the canonical RD dataset.

All series are loaded once and forward-filled with their typical publication lag.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from methodology.config import REPO_ROOT


ENSO_DIR = REPO_ROOT / "data" / "external_data" / "ENSO"
FX_DIR = REPO_ROOT / "data" / "external_data" / "FX"


def load_enso_oni() -> pd.DataFrame:
    """Monthly ONI (Oceanic Niño Index): date (1st of month), oni (°C SST anomaly)."""
    path = ENSO_DIR / "oni_monthly.csv"
    if not path.exists():
        return pd.DataFrame(columns=["date", "oni"])
    return pd.read_csv(path, parse_dates=["date"])


def load_enso_nino34() -> pd.DataFrame:
    """Monthly Niño 3.4 SST anomaly: date (1st of month), nino34_anomaly."""
    path = ENSO_DIR / "nino34_monthly.csv"
    if not path.exists():
        return pd.DataFrame(columns=["date", "nino34_anomaly"])
    return pd.read_csv(path, parse_dates=["date"])


def load_fx_dxy_proxy() -> pd.DataFrame:
    path = FX_DIR / "dxy_proxy_daily.csv"
    if not path.exists():
        return pd.DataFrame(columns=["date", "close"])
    return pd.read_csv(path, parse_dates=["date"]).rename(columns={"close": "fx_dxy_proxy"})


def load_fx_gbpusd() -> pd.DataFrame:
    path = FX_DIR / "gbpusd_daily.csv"
    if not path.exists():
        return pd.DataFrame(columns=["date", "close"])
    return pd.read_csv(path, parse_dates=["date"]).rename(columns={"close": "fx_gbpusd"})


def merge_external(
    df: pd.DataFrame,
    *,
    include_enso: bool = True,
    include_fx: bool = True,
    enso_publication_lag_days: int = 14,
) -> pd.DataFrame:
    """Left-join ENSO + FX onto df on date. Forward-fill within publication lag.

    ENSO is monthly with ~2-week lag (NOAA publishes around mid-month for the
    prior month). We shift monthly values by ``enso_publication_lag_days`` days
    forward before joining, so that the value for January 2024 is available from
    2024-02-15 onward (typical NOAA release timing).
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])

    if include_enso:
        oni = load_enso_oni()
        nin = load_enso_nino34()
        if len(oni) > 0:
            oni["date"] = oni["date"] + pd.Timedelta(days=enso_publication_lag_days)
            df = pd.merge_asof(
                df.sort_values("date"), oni.sort_values("date"), on="date", direction="backward"
            )
        if len(nin) > 0:
            nin["date"] = nin["date"] + pd.Timedelta(days=enso_publication_lag_days)
            df = pd.merge_asof(
                df.sort_values("date"), nin.sort_values("date"), on="date", direction="backward"
            )

    if include_fx:
        dxy = load_fx_dxy_proxy()
        gbp = load_fx_gbpusd()
        if len(dxy) > 0:
            df = pd.merge_asof(
                df.sort_values("date"), dxy.sort_values("date"), on="date", direction="backward"
            )
        if len(gbp) > 0:
            df = pd.merge_asof(
                df.sort_values("date"), gbp.sort_values("date"), on="date", direction="backward"
            )

    return df.reset_index(drop=True)

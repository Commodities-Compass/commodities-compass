"""Ingest USD strength + GBP/USD daily from ECB SDMX (free, no auth).

yfinance / FRED / Stooq all failed for this environment (Cloudflare or API-key
restrictions). ECB Statistical Data Warehouse is the most reliable open source.

We fetch:
    - USD/EUR (USD per 1 EUR): D.USD.EUR.SP00.A   → also used as DXY-strength proxy
    - GBP/EUR (GBP per 1 EUR): D.GBP.EUR.SP00.A
    GBPUSD = (USD per EUR) / (GBP per EUR), i.e. USD per 1 GBP

Outputs:
    data/external_data/FX/dxy_proxy_daily.csv   — date, close (= 1 / USD_per_EUR; rises when USD strengthens)
    data/external_data/FX/gbpusd_daily.csv      — date, close (USD per 1 GBP)
"""

from __future__ import annotations

import io
import urllib.request
from pathlib import Path

import pandas as pd


OUT_DIR = Path("data/external_data/FX")
ECB_BASE = "https://data-api.ecb.europa.eu/service/data/EXR"


def fetch_ecb(series_key: str, start_period: str = "2014-01-01") -> pd.DataFrame:
    url = f"{ECB_BASE}/{series_key}?format=csvdata&startPeriod={start_period}"
    req = urllib.request.Request(url, headers={"User-Agent": "compass-research/1.0", "Accept": "text/csv"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode("utf-8")
    df = pd.read_csv(io.StringIO(raw))
    df = df[["TIME_PERIOD", "OBS_VALUE"]].rename(columns={"TIME_PERIOD": "date", "OBS_VALUE": "value"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)
    return df


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[ingest_fx] Fetching USD/EUR from ECB (D.USD.EUR.SP00.A)…")
    usdeur = fetch_ecb("D.USD.EUR.SP00.A").rename(columns={"value": "usd_per_eur"})

    print("[ingest_fx] Fetching GBP/EUR from ECB (D.GBP.EUR.SP00.A)…")
    gbpeur = fetch_ecb("D.GBP.EUR.SP00.A").rename(columns={"value": "gbp_per_eur"})

    # DXY proxy: USD strength = 1 / (USD per 1 EUR). Higher when USD strengthens.
    dxy = usdeur.copy()
    dxy["close"] = 1.0 / dxy["usd_per_eur"]
    dxy = dxy[["date", "close"]]
    dxy_path = OUT_DIR / "dxy_proxy_daily.csv"
    dxy.to_csv(dxy_path, index=False)
    print(f"  → DXY proxy: {len(dxy)} rows ({dxy['date'].min().date()} to {dxy['date'].max().date()})")

    # GBP/USD: USD per 1 GBP = (USD per EUR) / (GBP per EUR)
    merged = usdeur.merge(gbpeur, on="date", how="inner")
    merged["close"] = merged["usd_per_eur"] / merged["gbp_per_eur"]
    gbpusd = merged[["date", "close"]]
    gbp_path = OUT_DIR / "gbpusd_daily.csv"
    gbpusd.to_csv(gbp_path, index=False)
    print(f"  → GBP/USD: {len(gbpusd)} rows ({gbpusd['date'].min().date()} to {gbpusd['date'].max().date()})")

    print("[ingest_fx] DONE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

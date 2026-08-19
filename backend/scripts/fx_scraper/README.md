# FX Scraper

ECB SDMX → `pl_external_indicator.fx_dxy_proxy / fx_gbpusd / fx_eurusd / fx_gbpeur`. Daily business-days cadence.

## Usage

```bash
poetry run fx-scraper            # full run
poetry run fx-scraper --dry-run  # fetch + parse + log, no DB write
poetry run fx-scraper --verbose  # debug logging
poetry run fx-scraper --force    # bypass non-trading-day skip (manual backfill)
```

## Source

- USD/EUR: `https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?format=csvdata`
- GBP/EUR: `https://data-api.ecb.europa.eu/service/data/EXR/D.GBP.EUR.SP00.A?format=csvdata`

Free, no auth. CSV format — see `parser.py`.

## Cron

`30 18 * * 1-5` — 18:30 UTC business days (ECB publishes ~16:00 CET, before
`cc-regime-shadow` runs at 19:18 UTC).

## Derived values

```
fx_dxy_proxy = 1 / usd_per_eur          rises when USD strengthens (DXY-like)
fx_eurusd    = 1 / usd_per_eur          alias of dxy_proxy, kept for audit
fx_gbpusd    = usd_per_eur / gbp_per_eur USD per 1 GBP
fx_gbpeur    = gbp_per_eur               raw passthrough, audit
```

## Schema target

`pl_external_indicator` (commodity-agnostic, keyed on `date`). Partial UPSERT —
FX scraper writes ONLY the 4 `fx_*` columns. ENSO columns (`enso_oni_month`,
`enso_nino34_anomaly`) are left untouched (written by `cc-enso-scraper`
independently).

## Why ECB and not yfinance / FRED / Stooq

The R&D investigation rejected those alternatives:
- yfinance: Cloudflare blocks unauth requests
- FRED: API key required
- Stooq: rate-limited + unstable

ECB SDMX is free, no auth, and the same source we use elsewhere for FX
(stable + well-documented format).

## Fail-loud

- Network error / HTTP non-200 / empty body → `FxScraperError`, non-zero exit, Sentry alert.
- One of the two series returns zero rows → fail (don't write partial state).
- No auto-retry. No fallback provider.
- Aligned with `.claude/rules/pipeline-error-handling.md`.

## Tests

```bash
poetry run pytest tests/test_fx_scraper.py -v
```

Coverage target: ≥80% on `scripts/fx_scraper/`.

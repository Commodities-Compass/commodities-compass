# ENSO Scraper

NOAA PSL → `pl_external_indicator.enso_oni_month` + `enso_nino34_anomaly`. Monthly cadence.

## Usage

```bash
poetry run enso-scraper            # full run
poetry run enso-scraper --dry-run  # fetch + parse + log, no DB write
poetry run enso-scraper --verbose  # debug logging
poetry run enso-scraper --force    # run on non-trading days (manual backfill)
```

## Source

- ONI: <https://psl.noaa.gov/data/correlation/oni.data>
- Niño 3.4: <https://psl.noaa.gov/data/correlation/nina34.anom.data>

Free, no auth. PSL ASCII format — see `parser.py` for parsing rules.

## Cron

`0 22 20 * 1-5` — 20 du mois 22:00 UTC (NOAA publishes ~mid-month for the previous month).

## Schema target

`pl_external_indicator` (commodity-agnostic, keyed on `date`). Partial UPSERT — ENSO scraper writes
ONLY `enso_oni_month` and `enso_nino34_anomaly`. FX columns are left untouched
(written by `cc-fx-scraper` independently).

## Lag policy

Stored at `date = YYYY-MM-01`. The engine ensemble applies a 14-day publication-lag shift at
compute time via `pd.merge_asof(direction="backward")`. See `external_data.py` in the R&D
snapshot for the canonical merge logic.

## Fail-loud

- Network error / HTTP non-200 / empty body → raise `EnsoScraperError`, non-zero exit, Sentry alert.
- No auto-retry. No fallback source.
- Aligned with `.claude/rules/pipeline-error-handling.md`.

## Tests

```bash
poetry run pytest tests/test_enso_scraper.py -v
```

Coverage target: ≥80% on `scripts/enso_scraper/`.

# Backtest — Seasonal Score / Cocoa Campaign 2024-2025

_Generated: 2026-05-11 16:00 UTC_

## TL;DR

- **Campaign**: `2024-2025` (target date 2025-09-30)
- **Health label** (worst-season-driven, per Copernicus EDO / Climate Central): **2.33 / 5** (saison_seche) — Campagne dégradée. Stress cumulé significatif, sensibilité élevée.
- **Overall average** (secondary stat — diluted by good seasons): 4.03 / 5
- **Per-season averages** (worst → best):
  - `saison_seche`: 2.33/5
  - `transition_pluies`: 3.42/5
  - `grande_saison_pluies`: 4.75/5
  - `petite_saison_seche`: 4.83/5
  - `petite_saison_pluies`: 4.83/5
- **Diagnostic spread**: `stress`=5, `degraded`=4, `normal`=21 (out of 30 season-location pairs)
- **Worst pair**: Daloa / `saison_seche` → 1.5/5
- **Best pair**: San-Pédro / `saison_seche` → 5.0/5
- **Cumulative Harmattan days** (sum across 6 locations, saison_seche only): **72** (critical threshold = 24 d/location)

## Methodology

**Source**: Open-Meteo Archive API (ERA5 reanalysis under the hood).
Endpoint: `https://archive-api.open-meteo.com/v1/archive`
Daily fields fetched: `precipitation_sum`, `et0_fao_evapotranspiration`,
`temperature_2m_max`, `temperature_2m_min`, `sunshine_duration`,
`winddirection_10m_dominant`. For `saison_seche` a second call adds hourly
`relative_humidity_2m` for Harmattan detection.

**Locations** (6 — West Africa cocoa belt):
- **Daloa** (Côte d'Ivoire) — lat 6.877, lon -6.45
- **San-Pédro** (Côte d'Ivoire) — lat 4.748, lon -6.636
- **Soubré** (Côte d'Ivoire) — lat 5.785, lon -6.606
- **Kumasi** (Ghana) — lat 6.688, lon -1.624
- **Takoradi** (Ghana) — lat 4.885, lon -1.745
- **Goaso** (Ghana) — lat 6.8, lon -2.52

**Scoring** (deterministic, code: `scripts.meteo_agent.seasonal_memory.compute_score`):
- Starts at 5.0, applies penalties:
  - **Precipitation deviation** (-2.0 / -1.0) vs season norm scaled to season length
  - **Heat stress ratio** = days above season threshold / total days (-0.5 → -2.0)
  - **Water balance** (precip − ET0) < -5 mm/day average: -0.5
- Clamped to [1.0, 5.0], rounded to 0.5.

**30-day precipitation norms** (currently hardcoded, marked "to be refined"):
- `saison_seche`: 10.0-60.0 mm / 30 days
- `transition_pluies`: 60.0-150.0 mm / 30 days
- `grande_saison_pluies`: 150.0-350.0 mm / 30 days
- `petite_saison_seche`: 40.0-120.0 mm / 30 days
- `petite_saison_pluies`: 100.0-250.0 mm / 30 days

**Diagnostic thresholds** (match `dashboard_service` LocationDiagnostic):
- `normal`: score ≥ 3.5
- `degraded`: 2.5 ≤ score < 3.5
- `stress`: score < 2.5

**Caveats**:
- `_PRECIP_30D_NORMS` are not calibrated against multi-year climatology.
  A single-campaign backtest can validate **direction** (stress vs normal)
  but not absolute level precision.
- Archive API has a ~5-day publication lag — the fetcher caps `end_date` to
  `today − 5 days`; a single-day gap in the most recent season is expected
  near the publication boundary.

## Per-season scores

### Saison Seche — Dec-Mar 2024
_2024-12-01 → 2025-03-31 (121 days)_

| Location | Country | Precip (mm) | ET0 (mm) | Balance | Days rain | Days stress | Avg Tmax | Harmattan d | Score | Diagnostic |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Daloa | Côte d'Ivoire | 136 | 614 | -479 | 25 | 117 | 34.1 | 19 | 1.5/5 | `stress` |
| San-Pédro | Côte d'Ivoire | 228 | 494 | -266 | 70 | 16 | 30.7 | 0 | 5.0/5 | `normal` |
| Soubré | Côte d'Ivoire | 198 | 520 | -322 | 44 | 100 | 33.3 | 14 | 2.0/5 | `stress` |
| Kumasi | Ghana | 146 | 587 | -441 | 28 | 115 | 34.6 | 16 | 2.0/5 | `stress` |
| Takoradi | Ghana | 247 | 506 | -260 | 97 | 86 | 32.4 | 1 | 2.0/5 | `stress` |
| Goaso | Ghana | 200 | 594 | -394 | 26 | 118 | 35.4 | 22 | 1.5/5 | `stress` |

### Transition Pluies — Apr-Apr 2025
_2025-04-01 → 2025-04-30 (30 days)_

| Location | Country | Precip (mm) | ET0 (mm) | Balance | Days rain | Days stress | Avg Tmax | Score | Diagnostic |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| Daloa | Côte d'Ivoire | 72 | 135 | -63 | 16 | 27 | 32.9 | 3.0/5 | `degraded` |
| San-Pédro | Côte d'Ivoire | 82 | 126 | -44 | 20 | 0 | 30.3 | 5.0/5 | `normal` |
| Soubré | Côte d'Ivoire | 85 | 125 | -40 | 22 | 20 | 32.3 | 3.0/5 | `degraded` |
| Kumasi | Ghana | 59 | 137 | -78 | 16 | 21 | 33.0 | 2.5/5 | `degraded` |
| Takoradi | Ghana | 114 | 131 | -17 | 28 | 12 | 31.9 | 4.0/5 | `normal` |
| Goaso | Ghana | 78 | 138 | -60 | 18 | 27 | 33.2 | 3.0/5 | `degraded` |

### Grande Saison Pluies — May-Jul 2025
_2025-05-01 → 2025-07-31 (92 days)_

| Location | Country | Precip (mm) | ET0 (mm) | Balance | Days rain | Days stress | Avg Tmax | Score | Diagnostic |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| Daloa | Côte d'Ivoire | 483 | 334 | +150 | 75 | 18 | 29.7 | 4.5/5 | `normal` |
| San-Pédro | Côte d'Ivoire | 541 | 327 | +214 | 80 | 0 | 27.9 | 5.0/5 | `normal` |
| Soubré | Côte d'Ivoire | 482 | 320 | +162 | 76 | 6 | 29.2 | 5.0/5 | `normal` |
| Kumasi | Ghana | 407 | 360 | +48 | 73 | 18 | 30.1 | 4.5/5 | `normal` |
| Takoradi | Ghana | 604 | 326 | +278 | 85 | 0 | 28.7 | 5.0/5 | `normal` |
| Goaso | Ghana | 364 | 357 | +8 | 68 | 26 | 30.8 | 4.5/5 | `normal` |

### Petite Saison Seche — Aug-Aug 2025
_2025-08-01 → 2025-08-31 (31 days)_

| Location | Country | Precip (mm) | ET0 (mm) | Balance | Days rain | Days stress | Avg Tmax | Score | Diagnostic |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| Daloa | Côte d'Ivoire | 150 | 102 | +48 | 30 | 0 | 27.8 | 4.0/5 | `normal` |
| San-Pédro | Côte d'Ivoire | 48 | 100 | -51 | 26 | 0 | 25.9 | 5.0/5 | `normal` |
| Soubré | Côte d'Ivoire | 122 | 99 | +23 | 26 | 0 | 27.9 | 5.0/5 | `normal` |
| Kumasi | Ghana | 79 | 103 | -24 | 30 | 0 | 27.5 | 5.0/5 | `normal` |
| Takoradi | Ghana | 96 | 92 | +4 | 31 | 0 | 26.5 | 5.0/5 | `normal` |
| Goaso | Ghana | 53 | 104 | -51 | 24 | 0 | 28.6 | 5.0/5 | `normal` |

### Petite Saison Pluies — Sep-Nov 2024
_2024-09-01 → 2024-11-30 (91 days)_

| Location | Country | Precip (mm) | ET0 (mm) | Balance | Days rain | Days stress | Avg Tmax | Score | Diagnostic |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| Daloa | Côte d'Ivoire | 456 | 327 | +129 | 68 | 12 | 30.2 | 5.0/5 | `normal` |
| San-Pédro | Côte d'Ivoire | 287 | 314 | -26 | 82 | 0 | 27.5 | 5.0/5 | `normal` |
| Soubré | Côte d'Ivoire | 491 | 319 | +172 | 80 | 0 | 30.0 | 5.0/5 | `normal` |
| Kumasi | Ghana | 432 | 341 | +92 | 61 | 22 | 30.5 | 4.5/5 | `normal` |
| Takoradi | Ghana | 387 | 343 | +43 | 81 | 6 | 29.7 | 5.0/5 | `normal` |
| Goaso | Ghana | 404 | 341 | +64 | 57 | 20 | 31.0 | 4.5/5 | `normal` |

## Cross-check guide

For each location below, the raw daily series is exported to `raw/<season>_<location>.csv`. Paste your reference figures (other weather provider, national met agency, station data) next to ours and diff. The fields we trust the most for cross-check are `precip_mm`, `tmax_c`, and (for saison_seche) `min_rh_pct` + `harmattan_flag`.

| Location | Country | Total precip (mm) across all seasons | Avg Tmax | Notes |
|---|---|---:|---:|---|
| Daloa | Côte d'Ivoire | 1296 | 31.4 | see `raw/*_Daloa.csv` |
| San-Pédro | Côte d'Ivoire | 1187 | 28.8 | see `raw/*_San-Pédro.csv` |
| Soubré | Côte d'Ivoire | 1378 | 30.9 | see `raw/*_Soubré.csv` |
| Kumasi | Ghana | 1124 | 31.7 | see `raw/*_Kumasi.csv` |
| Takoradi | Ghana | 1448 | 30.3 | see `raw/*_Takoradi.csv` |
| Goaso | Ghana | 1100 | 32.4 | see `raw/*_Goaso.csv` |

## Pipeline integrity

For each (season × location), `expected_days` is the inclusive span of the season range; `fetched_days` is what Open-Meteo returned. A gap of 1-5 days in the most recent season is expected (archive publication lag).

| Season | Location | Expected | Fetched | Δ |
|---|---|---:|---:|---:|
| saison_seche | Daloa | 121 | 121 | +0 |
| saison_seche | San-Pédro | 121 | 121 | +0 |
| saison_seche | Soubré | 121 | 121 | +0 |
| saison_seche | Kumasi | 121 | 121 | +0 |
| saison_seche | Takoradi | 121 | 121 | +0 |
| saison_seche | Goaso | 121 | 121 | +0 |
| transition_pluies | Daloa | 30 | 30 | +0 |
| transition_pluies | San-Pédro | 30 | 30 | +0 |
| transition_pluies | Soubré | 30 | 30 | +0 |
| transition_pluies | Kumasi | 30 | 30 | +0 |
| transition_pluies | Takoradi | 30 | 30 | +0 |
| transition_pluies | Goaso | 30 | 30 | +0 |
| grande_saison_pluies | Daloa | 92 | 92 | +0 |
| grande_saison_pluies | San-Pédro | 92 | 92 | +0 |
| grande_saison_pluies | Soubré | 92 | 92 | +0 |
| grande_saison_pluies | Kumasi | 92 | 92 | +0 |
| grande_saison_pluies | Takoradi | 92 | 92 | +0 |
| grande_saison_pluies | Goaso | 92 | 92 | +0 |
| petite_saison_seche | Daloa | 31 | 31 | +0 |
| petite_saison_seche | San-Pédro | 31 | 31 | +0 |
| petite_saison_seche | Soubré | 31 | 31 | +0 |
| petite_saison_seche | Kumasi | 31 | 31 | +0 |
| petite_saison_seche | Takoradi | 31 | 31 | +0 |
| petite_saison_seche | Goaso | 31 | 31 | +0 |
| petite_saison_pluies | Daloa | 91 | 91 | +0 |
| petite_saison_pluies | San-Pédro | 91 | 91 | +0 |
| petite_saison_pluies | Soubré | 91 | 91 | +0 |
| petite_saison_pluies | Kumasi | 91 | 91 | +0 |
| petite_saison_pluies | Takoradi | 91 | 91 | +0 |
| petite_saison_pluies | Goaso | 91 | 91 | +0 |

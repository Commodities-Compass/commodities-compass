# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 📚 Macro architecture docs (read first if unfamiliar with the codebase)

**START HERE → [docs/architecture/CODE_MAP.md](docs/architecture/CODE_MAP.md)** — the single entry-point map of every backend subsystem (what it does, where it lives, tables read/written, load-bearing invariants) with links to the flow deep-dives. Read it before touching backend code.

These describe the **business logic + data flows** without code details:

- **[docs/architecture/PIPELINE_LEGACY.md](docs/architecture/PIPELINE_LEGACY.md)** — pipeline `cc-daily-analysis` + `cc-compass-brief` (LLM-as-decision-maker, T+1 horizon, operational since 18 months)
- **[docs/architecture/PIPELINE_ENSEMBLE.md](docs/architecture/PIPELINE_ENSEMBLE.md)** — pipeline ensemble v1.0.0 : 14 ML specialists + soft-gate Bayésien + Compass wrapper + ensemble-explainer + compass-brief-ensemble (J+4-J+5 horizon, dashboard already serves this)
- **[docs/architecture/JOBS_AND_SCRAPERS.md](docs/architecture/JOBS_AND_SCRAPERS.md)** — exhaustive catalog of all 20 Cloud Run Jobs + 17 schedulers + dependency graph + shared vs specific data tables

**Flow deep-dives** ([docs/architecture/flows/](docs/architecture/flows/)) — failure-prone cross-cutting paths, esp. anything roll-related: [contract-roll](docs/architecture/flows/contract-roll.md) · [date-semantics](docs/architecture/flows/date-semantics.md) · [algo-contract-resolution](docs/architecture/flows/algo-contract-resolution.md) (the recurring roll-bug path — active-contract vs front-month-by-date) · [daily-pipeline](docs/architecture/flows/daily-pipeline.md) · [dual-track-brief](docs/architecture/flows/dual-track-brief.md). Known doc/comment drift is tracked in [docs/architecture/REMEDIATION_BACKLOG.md](docs/architecture/REMEDIATION_BACKLOG.md).

## Project Overview

Commodities Compass is a Business Intelligence application for commodities trading, providing real-time market insights, technical analysis, and trading signals for cocoa (ICE contracts). This is a monorepo with a FastAPI backend and React frontend, using Auth0 for authentication and PostgreSQL (GCP Cloud SQL) for data storage. Deployed on GCP Cloud Run with 20 automated Cloud Run Jobs (scrapers, agents, compute engine, briefs, intraday alerts). Dashboard reads from `pl_*` tables. Google Sheets is no longer used as a data source — all data flows through PostgreSQL. Google Drive is still used for audio (NotebookLM) and brief uploads.

**Two production tracks coexist** :
- **LEGACY** : `cc-daily-analysis` (LLM) → `pl_indicator_daily` row `legacy` → `cc-compass-brief` → `YYYYMMDD-CompassBrief.txt` → NotebookLM audio (legacy filename)
- **ENSEMBLE** : `cc-ensemble-compute` (ML) → `pl_indicator_daily` row `ensemble_v1_softgate_wrapper` + `pl_orchestrator_decision` + 14 `pl_specialist_prediction` → `cc-ensemble-explainer` (LLM narrative) → `cc-compass-brief-ensemble` → `YYYYMMDD-CompassBrief-Ensemble.txt` → NotebookLM audio (ensemble filename)
- Frontend dashboard serves ensemble via `_resolve_algo_for_date()` (row-existence based). Audio is served from legacy by default ; flip `BRIEF_DEFAULT_VERSION=ensemble` env var or `?version=ensemble` query param to switch.
- Voir [docs/runbooks/brief-dual-track.md](docs/runbooks/brief-dual-track.md) pour les opérations.

## Development Commands

### Monorepo Commands (from root)

- `pnpm install:all` - Install all dependencies (root, backend, frontend)
- `pnpm dev` - Start both backend and frontend in development mode (concurrently)
- `pnpm dev:backend` - Start only backend (<http://localhost:8000>)
- `pnpm dev:frontend` - Start only frontend (<http://localhost:5173>)
- `pnpm db:up` - Start PostgreSQL (port 5433) and Redis (port 6380) containers
- `pnpm db:down` - Stop database containers
- `pnpm db:logs` - View database container logs
- `pnpm lint` - Run linting for both projects
- `pnpm format` - Format code for both projects
- `pnpm test` - Run tests for both projects
- `pnpm build` - Build frontend for production

### Backend Commands (from backend/)

- `poetry run dev` - Start FastAPI development server
- `poetry run lint` - Run pre-commit hooks (ruff, pyright)
- `poetry install` - Install Python dependencies
- `poetry run alembic upgrade head` - Run database migrations
- `poetry run pytest` - Run backend tests
- `poetry run compute-indicators --all-contracts --dry-run` - Compute indicators (dry run)
- `poetry run compute-indicators --all-contracts` - Compute indicators, write only new rows (incremental, default)
- `poetry run compute-indicators --all-contracts --full` - Recompute and upsert all rows (for version switches, backfills)
- `poetry run compute-indicators --all-contracts --full --derived-only` - Correct `pl_derived_indicators` ONLY, leaving `pl_indicator_daily` + `pl_signal_component` frozen (used 2026-07-22 to fix the macroeco corruption without restating historical decisions/gauges)
- `poetry run compute-indicators --all-contracts --algorithm legacy --algorithm-version 1.0.1` - Compute with specific version
- `poetry run compute-indicators --contract CAK26` - Compute for a single contract

### Frontend Commands (from frontend/)

- `pnpm dev` - Start Vite development server
- `pnpm build` - Build for production
- `pnpm lint` - Run ESLint
- `pnpm lint:fix` - Run ESLint with auto-fix
- `pnpm format` - Run Prettier
- `pnpm format:check` - Check formatting without writing
- `pnpm type-check` - Run TypeScript type checking (noEmit)

## Architecture

### Backend (FastAPI)

The backend follows a clean architecture with separation of concerns:

- **`app/main.py`** - FastAPI application entry point with CORS, rate limiting (slowapi), security headers middleware, request logging, exception handling, and OpenAPI/Auth0 schema configuration
- **`app/core/`** - Core functionality:
  - `config.py` - Pydantic settings with environment variable management.
  - `auth.py` - Auth0 JWT token verification with JWKS caching (6-hour TTL) and user extraction
  - `security.py` - Password hashing (bcrypt) and token utilities
  - `database.py` - Async SQLAlchemy setup with dual engines (async for app, sync for Alembic)
  - `rate_limit.py` - Shared slowapi limiter instance (extracted to avoid circular imports)

- **`app/api/api_v1/`** - API endpoints focused on HTTP concerns:
  - `api.py` - Router aggregator combining all endpoint modules
  - `endpoints/auth.py` - Authentication endpoints (me, verify)
  - `endpoints/dashboard.py` - Dashboard data endpoints (position, indicators, recommendations, chart, news, weather, audio)
  - `endpoints/audio.py` - Audio streaming and metadata endpoints (unauthenticated stream for HTML audio element)
- **`app/models/`** - SQLAlchemy database models split by domain:
  - `base.py` - DeclarativeBase class
  - `technicals.py` - Legacy: OHLCV data with 40+ technical indicators (unused, pending drop)
  - `indicator.py` - Legacy: normalized indicators and trading signals (unused, pending drop)
  - `market_research.py` - Legacy: market research articles
  - `weather_data.py` - Legacy: weather impact data
  - `test_range.py` - Indicator color ranges (RED/ORANGE/GREEN)
  - `reference.py` - MVP: ref_commodity, ref_exchange, ref_contract, ref_trading_calendar
  - `pipeline.py` - MVP: pl_contract_data_daily, pl_derived_indicators, pl_indicator_daily, pl_algorithm_version, pl_algorithm_config, pl_fundamental_article (`is_active` flag for multi-provider support), pl_weather_observation, pl_seasonal_score
  - `signal.py` - MVP: pl_signal_component (per-indicator contribution decomposition)
- **`app/schemas/`** - Pydantic request/response models:
  - `dashboard.py` - All dashboard response schemas (PositionStatus, IndicatorsGrid, Recommendations, ChartData, News, Weather, Audio)
- **`app/services/`** - Business logic layer (service-oriented architecture):
  - `dashboard_service.py` - Pure business logic for dashboard operations. All queries read from pl_* tables (contract-centric).
  - `dashboard_transformers.py` - Data transformation between dicts and API responses.
  - `audio_service.py` - Google Drive audio file integration (singleton service). In-memory cache on file lookups (1h TTL for hits, 5min for misses) eliminates redundant Drive API calls.
- **`app/utils/`** - Reusable utility functions:
  - `date_utils.py` - Date parsing, validation, business date conversion (weekend to Friday)
  - `contract_resolver.py` - Active contract and algorithm version resolution from ref_contract/pl_algorithm_version tables. Bridges commodity-centric to contract-centric queries.
- **`app/engine/`** - Indicator computation engine (Phase 3.1). Replaces the Google Sheets formula engine. See `app/engine/README.md` for full docs.
  - `types.py` - AlgorithmConfig (frozen), legacy v1.0.0 params (fallback), column constants
  - `indicators/` - 14 technical indicators (pivots, EMA, MACD, RSI Wilder, Stochastic, ATR Wilder, Bollinger, ratios), each implementing the `Indicator` protocol
  - `registry.py` - Indicator registry with topological sort on dependency graph
  - `smoothing.py` - 5-day SMA scoring layer
  - `normalization.py` - Rolling 252-day z-score (replaces Sheets' full-history z-score which had look-ahead bias)
  - `composite.py` - Power formula (`k + Σ(coeff × sign(x) × |x|^exp)`) with configurable decision thresholds
  - `pipeline.py` - Orchestrator: raw OHLCV → derived indicators → raw scores → z-scores → composite score + decision
  - `db_writer.py` - Upsert results to `pl_derived_indicators`, `pl_indicator_daily`, `pl_signal_component`
  - `runner.py` - CLI entry point (`poetry run compute-indicators`)

### Frontend (React 19 + TypeScript)

The frontend follows the **Compass CC editorial / magazine brand identity** (2026 brand bible — assets in `docs/brand/`). It reads like a daily intelligence briefing rather than a generic dashboard.

- **Brand identity**:
  - Tokens in `src/index.css` (`--ink`, `--ink-dark`, `--ink-mid`, `--ink-light`, `--rule`, `--paper-off`, `--paper`, `--color-signal-{open,monitor,hedge}`).
  - **Typography**: Playfair Display (`--font-display`, italic for editorial voice) + Inter (`--font-sans`, sections + structure) + IBM Plex Mono (`--font-mono`, data, kickers, ticker) + Georgia (`--font-editorial`, article body). All self-hosted via `@fontsource(-variable)`.
  - **Signal palette**: OPEN `#10B981`, MONITOR `#F59E0B`, HEDGE `#EF4444`.
  - Light theme only. Dark mode = P2 follow-up (no toggle currently exposed).
  - **Favicon** — all sizes regenerated from `docs/brand/logo/transparent/compass-icon-1024-transparent.png` via `sips` (16/32/48 + 180 apple-touch + 192/512 android-chrome). OG image at `frontend/public/og-image.png`.
- **Auth0 Integration** - `main.tsx` sets up Auth0Provider with localStorage caching and refresh tokens
- **API Layer** - `src/api/` contains:
  - `client.ts` - Axios client with automatic token injection and 401 interceptor (dispatches `auth:token-expired` event)
  - `dashboard.ts` - Dashboard API service functions for all endpoints
- **State Management** - React Query (TanStack Query) — global default stale time is 5 minutes (`main.tsx`), but all dashboard hooks in `useDashboard.ts` override to 24-hour stale time (no auto-refetch) since trading data updates once daily
- **Routing** - React Router with `ProtectedRoute` wrapper requiring authentication. `DashboardDateProvider` (from `src/contexts/DashboardDateContext.tsx`) wraps the protected routes so the masthead, page, and ticker share `currentDate` without prop-drilling.
  - `/` → `RootRedirect` (waits for Auth0 `isLoading` before redirecting to `/dashboard` — prevents stripping `?code=` callback params)
  - `/login` - Auth0 login page with redirect loop detection and error display
  - `/dashboard` - Main trading dashboard (protected)
  - `/dashboard/historical` - Historical data view (protected)
- **UI Components** - Shadcn/ui (new-york style) with Radix UI primitives in `src/components/ui/`. Calendar popover is restyled editorial (sharp corners, mono uppercase weekdays, Playfair italic month caption).
- **Editorial primitives** (`src/components/editorial/`):
  - `<Eyebrow>` — mono uppercase eyebrow/kicker, three tones (primary/muted/subtle), used everywhere a section subtitle or data label is needed.
  - `<DataValue>` — mono tabular numerals for ticker numbers, scores, prices.
  - `<DotSeparator>` — small `--rule` dot used between ticker cells.
- **Section header / tabs**:
  - `SectionHeader` (`src/components/section-header.tsx`) — roman numeral (Playfair light gray) + Inter sans uppercase title + horizontal rule. Used by all top-level dashboard sections.
  - `EditorialTabs` (`src/components/editorial-tabs.tsx`) — magazine-style tabs (Playfair italic active label, ink underline, optional mono `(n)` badge). Full ARIA + keyboard arrow navigation.
- **Dashboard sections** (in render order I → V):
  - **I — `PodcastPlayer`** (Compass Daily Brief): editorial colophon-style audio block. NotebookLM `.wav/.m4a/.mp4` from Google Drive, click-to-seek SoundCloud-style waveform (56 deterministic bars), pause-on-hover. Spinner until `canplay`.
  - **II — `MarketAnalysis`** (Market Analysis): two sub-blocks under a single section header.
    - 1. `COMPASS GAUGES` row — 5 ruler-style `GaugeIndicator`s (MACD / VOL-OI / RSI / %K / ATR) with HEDGE/MONITOR/OPEN zone labels, colored triangle marker, mono value above.
    - 2. Tabs `Recommandation` / `Supply & Momentum` / `Technical Outlook` (parsed from `useRecommendations().recommendations`) with **drop cap** on first paragraph + `À surveiller` sidebar on the right.
  - **III — `PriceChart`** (Price History & Signal Overlay): monochrome Recharts area, editorial `MetricDropdown` (mono uppercase trigger + ink underline, no rounded shadcn pill) and `DaysPillGroup` (segmented `30J / 90J / 180J / 1Y` button group). Editorial caption `Fig. 1 — ...` below.
  - **IV — `NewsCard`** (Press Review): top row of 4 sentiment thematic ruler gauges (PRODUCTION / CHOCOLAT / TRANSF. / ÉCONOMIE — `useNewsSentiment`), then 3 tabs `Marché — Technique` / `Fondamentaux` / `Sentiment de marché` with Playfair italic body + drop quote `"`. Impact synthesis box + keyword pills below.
  - **V — `WeatherUpdateCard`** (Weather Intelligence) — orchestrator. Sub-components in `src/components/weather/`:
    - `CampaignBlock` — `Campagne YYYY-YY` header + `Santé globale X.X/5` (Playfair colored) + methodology grid (one column per saison, serif numeral + colored score + status badge, `in_progress` highlighted).
    - `StressHistoryBlock` — editorial table (Origin / Pays / Tendance 7j as vertical bars / Streak / Trend arrow / Statut pill).
    - `HarmattanBlock` — risk badge + jours cumulés + affected sites list.
    - `shared.ts` — `STATUS_HEX`, `statusLabel`, `healthColor` helpers.
    - Bulletin du jour rendered at the bottom as Georgia editorial text.
- **`SignalHero`** (above section I): Lead Analysis kicker, Playfair 56px headline `Signal [POSITION] — Cocoa [trend]` with inline colored signal pill, Georgia italic deck (from `useRecommendations`), Compass Intelligence Desk byline. Score panel on right (320px) shows position badge + YTD performance.
- **`DashboardLayout`** (masthead + ticker + colophon):
  - Top-rule (mono uppercase 9px): user dropdown left, compact date picker right. No Vol/No, no pub name (kept the layout breathing).
  - Title block: `COMPASS CC` (Playfair 900 ~44-76px clamp) + `The Cocoa Markets Intelligence Briefing` italic deck. Compass icon (`src/assets/compass-icon.png`) on the right of the title (horizontal lockup).
  - Signal triplet legend (OPEN / MONITOR / HEDGE).
  - `LiveSignalStrip` band below masthead — full-width scrolling marquee (60s linear, pause-on-hover, fade mask, `prefers-reduced-motion` respected) showing signal/price/DoD/Volume/OI/RSI/MACD/%K/ATR/V-OI/YTD/session.
  - Editorial colophon footer with display name + version + © year.
- **`LiveSignalStrip`** (`src/components/live-signal-strip.tsx`): consumes `usePositionStatus` + `useChartData(5)` + `useIndicatorsGrid` via `useDashboardDate`. Compose with `<Eyebrow>` + `<DataValue>` + `<DotSeparator>`.
- **`DateSelector`** (`src/components/date-selector.tsx`) — two variants:
  - `card` (legacy) — old Card-wrapped picker with `< >` chevrons.
  - `compact` (used in masthead) — single mono uppercase button with calendar icon, popover calendar opens on click.
- **`LoadingSpinner`** (`src/components/LoadingSpinner.tsx`) — full-screen centered spinner.
- **Custom Hooks**:
  - `useAuth.ts` - Auth0 token management wrapper
  - `useDashboard.ts` - React Query hooks for all dashboard endpoints (24h stale time, no auto-refetch)
  - `useDashboardDate.ts` - Reads current/session date from `DashboardDateContext`
- **Types** - `src/types/dashboard.ts` for all API response type definitions
- **Data** - `src/data/commodities-data.ts` for chart metric options and mock data
- **Brand asset source** - `docs/brand/` contains the original 2026 brand pack: tokens (`compass-brandbible-2026.html`), magazine reference (`ux-3-magazine.html`), gauge variants (`gauge-styles-editorial.html`), business cards, and the full logo library (favicon/, png/, dark/, transparent/, social/).

### Environment Configuration

Environment variables are organized in two levels:

- **Backend `.env`** - Backend-specific (database, APIs, Google Drive, Auth0, AWS)
- **Frontend `.env`** - Frontend-specific (Auth0, redirect URIs, API base URL)

Frontend code uses Auth0 variables (not VITE_ prefixed) exposed via custom Vite `define` configuration in `vite.config.ts`.

### Database Setup

- PostgreSQL 15 runs on custom port 5433 (not default 5432) via Docker
- Redis 7 runs on custom port 6380 (not default 6379) via Docker
- Database URL: `postgresql+asyncpg://postgres:password@localhost:5433/commodities_compass`
- Async SQLAlchemy with asyncpg driver for app, sync engine for Alembic migrations
- Multiple migrations exist (idempotent with `_has_column()` checks and `if_not_exists=True` for safe re-application on GCP)
- **Legacy tables** (technicals, indicator, market_research, weather_data) still exist in the database but are no longer read by any production code. Dashboard API reads exclusively from `pl_*` tables. Legacy tables will be dropped in a future migration.

### Authentication Flow

1. Frontend uses Auth0 SPA client with React SDK (`cacheLocation: "localstorage"`, refresh tokens enabled)
2. Tokens stored in localStorage (`auth0_token`) and automatically added to API requests via Axios interceptor
3. Backend validates JWT tokens using Auth0's JWKS endpoint (RS256, cached for 6 hours)
4. User claims extracted: sub, email, name, permissions
5. On 401 response: Axios interceptor clears token, sets `auth_401_error` flag in sessionStorage, dispatches `auth:token-expired` event. App.tsx sets `isLoggingOut` state → `ProtectedRoute` shows spinner (prevents component crashes during redirect) → Auth0 `logout()` redirects to `/login`
6. Login page reads `auth_401_error` flag and shows "Session expired" banner. Includes redirect loop detection (max 3 redirects in 5-second window)
7. **Important**: `https://app.com-compass.com/login` must be in Auth0 **Allowed Logout URLs** — otherwise Auth0 shows its own error page instead of redirecting

## Data Pipeline

### Pipeline (GCP Cloud Run Jobs)

Cloud Run Jobs run on Cloud Scheduler (18:30–22:10 UTC, weekday Phase A + eve-gated Phase B). **Only the barchart scraper writes to `pl_contract_data_daily`** (OHLCV+IV); since migration `r2m3n4o5p6q7` (2026-05-27) the other scrapers write dedicated tables — `pl_stock_observation` (ICE US/EU stocks), `pl_cot_us_weekly` / `pl_cot_eu_weekly` (COT), `pl_supply_demand_observation` (ECA/NCA grindings), `pl_external_indicator` (FX/ENSO). See [JOBS_AND_SCRAPERS.md](docs/architecture/JOBS_AND_SCRAPERS.md) for the full job/table map. The indicator computation engine (`app/engine/`) replaced the former Google Sheets formula engine:

```
Scrapers → pl_contract_data_daily (raw OHLCV)
               │
               └→ compute-indicators (app/engine/)
                    ├→ pl_derived_indicators (27 technical indicators)
                    ├→ pl_indicator_daily (scores, z-scores, composite, decision)
                    └→ pl_signal_component (per-indicator contribution)
```

- **Fixes 9 documented bugs** vs Sheets: Wilder's RSI/ATR, symmetric Bollinger, rolling z-scores (no look-ahead bias), correct Stochastic bounds, correct decision labels
- **Contract-centric**: all data keyed on `(date, contract_id)`
- **Algorithm config as data**: Power formula params stored in `pl_algorithm_config`, versioned (legacy v1.0.0, v1.0.1). CLI: `--algorithm legacy --algorithm-version 1.0.1`
- **CLI**: `poetry run compute-indicators --all-contracts [--dry-run]`
- **Full docs**: `app/engine/README.md`

## Scrapers

Multiple automated scrapers run as GCP Cloud Run Jobs (`backend/Dockerfile.jobs`, Playwright where needed). **Only `barchart-scraper` writes `pl_contract_data_daily`** (OHLCV+IV). Since migration `r2m3n4o5p6q7` (2026-05-27) the weekly/quarterly fundamentals write **dedicated tables** with their own `report_date` provenance — they are no longer stamped onto the daily OHLCV row.

### Architecture

```
pl_contract_data_daily row (barchart-scraper only):
  date | display_date | open | high | low | close | volume | oi | implied_volatility

Fundamentals → dedicated cadence tables (own report_date):
  ICE US/EU stocks ............ pl_stock_observation        (ice-stocks, barchart-stocks-eu)
  CFTC US / ICE EU COT ........ pl_cot_us_weekly / pl_cot_eu_weekly   (cftc, ice-cot-eu)
  ECA / NCA grindings ......... pl_supply_demand_observation (eca-, nca-grindings)
  FX (ECB) / ENSO (NOAA) ...... pl_external_indicator        (fx, enso)
```

### Date Semantics (display_date)

`pl_contract_data_daily` has two date columns:
- **`date`** = session date (when trading happened). Immutable truth. Used by the indicator engine for computation (rolling z-scores, momentum).
- **`display_date`** = `next_trading_day(date)`. When users first see this data on the dashboard. Set by the barchart scraper via `get_display_date()`.

All other tables (`pl_indicator_daily`, `pl_derived_indicators`, `pl_signal_component`, `pl_fundamental_article`, `pl_weather_observation`) use `date` = session date only. The dashboard resolves `display_date → session_date` in a single lookup (`_parse_and_validate_date`), then queries all tables by session date.

The frontend calendar shows `display_date` values. Non-trading days (weekends + exchange holidays) are greyed out. The `-1 day` offset that was previously applied in the frontend (`getYesterdayISO`) has been removed — the backend handles the full date resolution.

### Barchart Scraper (`backend/scripts/barchart_scraper/`)

- **Data**: C, H, L, V, OI, IV for London cocoa #7 (ICE Europe, GBP/tonne)
- **Contract selection**: Resolved from DB (`ref_contract.is_active`). `ACTIVE_CONTRACT` env var is a fallback only if DB lookup fails. Delivery months: H(Mar), K(May), N(Jul), U(Sep), Z(Dec). CA\*0 is NOT used because Barchart rolls it on their own schedule (volume-based), which doesn't match our timing. To roll contracts: `poetry run roll-contract CAN26` (deactivates old, activates new — all scrapers auto-detect on next run).
- **Source**: `https://www.barchart.com/futures/quotes/{contract}/overview` (OHLCV+OI) + `/{contract}/volatility-greeks` (IV)
- **Method**: Playwright browser → extracts OHLCV+OI from server-rendered inline JSON raw blocks (max-volume heuristic to pick the correct block among 4+). XHR API response used as backup for C/H/L/V (API omits OI). IV via XHR interception or HTML regex fallback.
- **Volume**: Raw contract count (no conversion)
- **IV conversion**: percentage → decimal (e.g., `55.38` → `0.5538`)
- **Post-write**: Auto-extends CONCLUSION formula in column AS (YTD scoring of INDICATOR decisions vs next-day price moves)
- **Cron**: `0 19 * * 1-5` (7 PM UTC weekdays only)
- **CLI**: `poetry run barchart-scraper [--dry-run] [--verbose] [--headful]`

### ICE Stocks Scraper (`backend/scripts/ice_stocks_scraper/`)

- **Data**: STOCK US (column H) — certified cocoa stocks in ICE US warehouses
- **Source**: `https://www.ice.com/publicdocs/futures_us_reports/cocoa/cocoa_cert_stock_YYYYMMDD.xls`
- **Method**: Pure httpx + pandas (no browser). Downloads public XLS, parses "GRAND TOTAL" row, converts bags → tonnes (`bags × 70 / 1000`).
- **Fallback**: Walks back through business days (up to 60) until a report is found. Handles `a`-suffix variants.
- **Cron**: `5 19 * * 1-5` (7:05 PM UTC weekdays — 5 min after Barchart to ensure row exists)
- **CLI**: `poetry run ice-stocks-scraper [--dry-run] [--date YYYY-MM-DD]`

### CFTC Scraper (`backend/scripts/cftc_scraper/`)

- **Data**: COM NET US (column I) — commercial net position from CFTC COT report
- **Source**: `https://www.cftc.gov/dea/futures/ag_lf.htm`
- **Method**: Pure httpx + regex (no browser). Parses "COCOA - ICE FUTURES U.S." section, extracts Producer/Merchant Long − Short.
- **Cron**: `5 19 * * 1-5` (7:05 PM UTC weekdays — 5 min after Barchart; idempotent, new data only on Fridays after CFTC publishes ~9:30 PM CET)
- **CLI**: `poetry run cftc-scraper [--dry-run]`

### ENSO Scraper (`backend/scripts/enso_scraper/`)

- **Data**: ENSO ONI (`enso_oni_month`) + Niño 3.4 anomaly (`enso_nino34_anomaly`) — climatology features consumed by Campaign 5 ensemble macro panel.
- **Source**: NOAA Physical Sciences Laboratory — `https://psl.noaa.gov/data/correlation/oni.data` + `nina34.anom.data` (free, no auth, plain ASCII).
- **Target table**: `pl_external_indicator` (commodity-agnostic, keyed on `date`, shared with FX scraper via partial UPSERT).
- **Method**: Pure httpx + stdlib parser (no pandas). PSL ASCII format: header + rows `year jan feb ... dec`; missing-value sentinel `-99.9*` filtered.
- **Cron**: `0 22 20 * 1-5` (20th of month, 22:00 UTC — NOAA publishes mid-month for prior month, 5-day buffer).
- **Lag policy**: 14 days, applied at compute-time by the engine (`pd.merge_asof(direction="backward")`), not by the scraper.
- **CLI**: `poetry run enso-scraper [--dry-run] [--force] [--verbose]`
- **Backfill (one-shot)**: `poetry run enso-scraper-backfill [--verify]` — imports `docs/onboarding/ENSO/{oni,nino34}_monthly.csv` (~1830 rows, 1950-2026).
- **US**: [docs/user-stories/P1-scraper-enso.md](docs/user-stories/P1-scraper-enso.md)

### FX Scraper (`backend/scripts/fx_scraper/`)

- **Data**: 4 derived FX columns on `pl_external_indicator`:
  - `fx_dxy_proxy = 1 / usd_per_eur` (rises when USD strengthens)
  - `fx_eurusd = 1 / usd_per_eur` (alias of dxy_proxy, audit)
  - `fx_gbpusd = usd_per_eur / gbp_per_eur` (USD per 1 GBP — directly consumed by C5 specialists)
  - `fx_gbpeur = gbp_per_eur` (raw passthrough, audit)
- **Source**: ECB SDMX 2.1 (free, no auth, CSV format):
  - `https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?format=csvdata`
  - `https://data-api.ecb.europa.eu/service/data/EXR/D.GBP.EUR.SP00.A?format=csvdata`
- **Target table**: `pl_external_indicator` (same table as ENSO, partial UPSERT preserves ENSO columns).
- **Method**: Pure httpx + stdlib csv parser (no pandas). Combines the 2 series by date (union, not inner join).
- **Cron**: `30 18 * * 1-5` (18:30 UTC business days, before `cc-ensemble-compute` at 19:18).
- **Why ECB not yfinance/FRED/Stooq**: R&D rejected those (Cloudflare, API-key, rate limits). ECB is the most reliable open source.
- **CLI**: `poetry run fx-scraper [--dry-run] [--force] [--verbose]`
- **Backfill (one-shot)**: `poetry run fx-scraper-backfill [--verify]` — imports `docs/onboarding/FX/{dxy_proxy,gbpusd}_daily.csv` (~3164 rows, 2014-2026).
- **US**: [docs/user-stories/P1-scraper-fx.md](docs/user-stories/P1-scraper-fx.md)

### ICE COT EU Scraper (`backend/scripts/ice_cot_eu_scraper/`)

- **Data**: ICE Europe COT cocoa weekly positioning — Producer/Merchant (long/short), Managed Money (long/short, the R&D signal), Other Reportables, Non-Reportable, plus Open Interest. Net columns (`prod_merc_net`, `m_money_net`) are Postgres `GENERATED` columns — auto-computed, never written directly.
- **Source**: ICE public CSV at `https://www.theice.com/publicdocs/futures/COTHist{YYYY}.csv` (free, no auth, ~175 columns, UTF-8 BOM). One file per calendar year, ~52 weeks × 5 markets per file. Filter: `Market_and_Exchange_Names == "ICE Cocoa Futures - ICE Futures Europe"` + `FutOnly_or_Combined == "FutOnly"`.
- **Target table**: `pl_cot_eu_weekly` (dedicated weekly snapshot table, schema includes Managed Money decomposition for ensemble R&D features — see [docs/onboarding/HEDI_DATA_MAP.md §3.4](docs/onboarding/HEDI_DATA_MAP.md#34-pl_cot_eu_weekly)).
- **Method**: Pure httpx + stdlib `csv.DictReader` (no pandas, no browser). BOM-stripping + strict header validation (fail-loud on schema drift). `release_date = report_date + 3 days` (ICE/CFTC publication lag).
- **Cron**: `10 22 * * 1-5` (22:10 UTC weekdays). ICE publishes Friday ~21:30 CET for prior Tuesday's snapshot; daily run + idempotent UPSERT on `(release_date, contract_market)` catches late publishes without coupling cron to ICE's exact time.
- **CLI**: `poetry run ice-cot-eu-scraper [--dry-run] [--year YYYY] [--force] [--verbose]` — `--year` for backfill (defaults to current UTC year).
- **US**: [docs/user-stories/P1-scrapers-stock-cot-eu.md](docs/user-stories/P1-scrapers-stock-cot-eu.md)

### Barchart Stocks EU Scraper (`backend/scripts/barchart_stocks_eu_scraper/`)

- **Data**: ICE Europe certified cocoa stocks (in 60kg bags) — updates `pl_contract_data_daily.stock_eu_bags60kg` on the row for the most recent reported date. Never INSERTs (OHLCV row must already exist from `barchart-scraper`).
- **Source**: `https://www.barchart.com/cmdty/data/fundamental/explore/IC345DRW.CS` (Barchart commodity statistics public page, no authentication required). Identifier `IC345DRW.CS` (Barchart convention: `.CS` suffix = Cocoa Stocks). Historical depth: from 2012-02-07 (14+ years).
- **Method**: Pure httpx + BeautifulSoup. HTML server-rendered, two `<table class="cmdty-quote-table">` blocks: (1) metadata (Most Recent Value/Date, Unit, Multiplier, Prior Value), (2) 7-day history. Native unit `60 Kg Bag` + Multiplier `1` are validated in the parser — any drift fails-loud.
- **Cron**: `10 19 * * 1-5` (19:10 UTC weekdays, 10 min after `cc-barchart-scraper` so the OHLCV row exists).
- **Fail-loud**: HTTP non-200, empty body, missing tables, unexpected unit/multiplier, unparseable value/date, **and** missing OHLCV row for target date (`StockEuRowMissingError`).
- **CLI**: `poetry run barchart-stocks-eu-scraper [--dry-run] [--force] [--verbose]`
- **US**: [docs/user-stories/P1-scrapers-stock-cot-eu.md](docs/user-stories/P1-scrapers-stock-cot-eu.md)

### ECA Grindings Scraper (`backend/scripts/eca_grindings_scraper/`)

- **Data**: European Cocoa Association Western Europe grindings — 2 metrics per quarter (`volume_tonnes`, `yoy_pct`) written to `pl_supply_demand_observation` (EAV-style fundamentals table). Covers ~40% of world cocoa grindings (19 reporting companies compiled by Statser).
- **Source**: Listing page `https://www.eurococoa.com/grind-stats/` → discovers PDF URLs (URL pattern is INCONSISTENT: `-1`, `-2`, or no suffix, depending on revision history; the scraper never predicts URLs). ~7 years of archives (2019-Q1 → today) available.
- **Method**: Pure httpx + pdfplumber. Parser extracts publication date from "Date :" header, locates "Quarterly Comparison" (YoY %) and "Quarterly Results" (volumes) sections, reads the FIRST numeric token in the current-year row (= the Q{n} value, since data is left-justified by most recent quarter). Fail-loud on missing anchors, drifted layouts, or out-of-range values.
- **Calendar-gated**: queries `ref_publication_calendar` for ECA grindings rows where `actual_publication_date IS NULL AND today() BETWEEN expected ± 14 days`. Exits 0 if no publication pending (~250 cheap no-ops/year).
- **Cron**: `0 13 * * 1-5` (13:00 UTC weekdays — ECA publishes Thursdays ~14:00 CET on ~16th of month after each quarter end).
- **CLI**: `poetry run eca-grindings-scraper [--dry-run] [--verbose]`
- **Backfill**: `poetry run eca-grindings-scraper-backfill [--dry-run]` (full listing one-shot, skip per-PDF parse errors).
- **US**: [docs/user-stories/P3-fundamental-data-scrapers-grindings.md](docs/user-stories/P3-fundamental-data-scrapers-grindings.md)

### NCA Grindings Scraper (`backend/scripts/nca_grindings_scraper/`)

- **Data**: National Confectioners Association North-American grindings — same 2 metrics per quarter as ECA, also written to `pl_supply_demand_observation` (region = `north_america`). ~13 reporting plants.
- **Source**: Listing page `https://candyusa.com/cocoa-grinds-report/` → discovers PDFs hosted on candyusa.com with INCONSISTENT filenames (`Q1-2026-Cocoa-Grinds.pdf`, `Q1_2025_Cocoa_Grinds_REV0421.pdf`, `Q1_2023_CocoaGrinds_NCA.pdf`, etc.). ~5 years of archives (2021-Q1 → today). **candyusa.com sits behind a SiteGround anti-bot WAF** that serves an HTTP 202 `sgcaptcha` JS-challenge to datacenter/Cloud Run egress IPs (residential IPs pass, Cloud Run does not — Sentry 2026-07-09/10). The former host `chocolatecouncil.org` (now a 302 here) has the same posture — swapping the host does not help (PR #57 tried, regressed). So we fetch through a headless browser (see Method).
- **Method**: Headless Chromium via Playwright (`browser.py` — clears the SiteGround `sgcaptcha` JS-challenge, one browser context reused for listing HTML + PDF downloads; fail-loud if the challenge does not clear) + pdfplumber for parsing. Parser extracts publication date + quarter/year from "Subj: Release of <Ordinal> Quarter Cocoa Grindings for <Year>", then reads the "Cocoa Beans Ground" line for current+prior year tonnages. `yoy_pct` is computed as `current/prior*100` rather than parsing the delta column (robust to multiple formats: `(4,191)`, `-5,028`, etc.). Handles both spaced and kerned ("CocoaBeansGround") variants. Cloud Run job memory bumped 512Mi→1Gi for Chromium.
- **Calendar-gated**: same pattern as ECA against `ref_publication_calendar` (NCA rows).
- **Cron**: `0 14 * * 1-5` (14:00 UTC weekdays — NCA publishes ~mid-day ET, similar window to ECA).
- **CLI**: `poetry run nca-grindings-scraper [--dry-run] [--verbose]`
- **Backfill**: `poetry run nca-grindings-scraper-backfill [--dry-run]` (full listing one-shot).
- **US**: [docs/user-stories/P3-fundamental-data-scrapers-grindings.md](docs/user-stories/P3-fundamental-data-scrapers-grindings.md)

### Publication Calendar Watchdog (`backend/scripts/publication_calendar_watchdog/`)

- **Purpose**: Daily safety net for low-frequency fundamentals scrapers. Queries `ref_publication_calendar` for rows where `actual_publication_date IS NULL AND expected_publication_date < today - 21 days`. Each overdue row is logged at ERROR + sent to Sentry as `capture_message(level=error)`. Non-zero exit on overdue rows so the cron monitor flags it.
- **Why**: ECA/NCA scrapers gate on the calendar and exit 0 cleanly when no publication is pending. That makes "publisher silence" indistinguishable from "no expected publication today" from a Sentry cron-monitor perspective. The watchdog turns silence into a visible alert past the grace window.
- **Cron**: `0 16 * * 1-5` (16:00 UTC weekdays — after both grindings scrapers).
- **CLI**: `poetry run publication-calendar-watchdog [--dry-run] [--grace-days N]`

### Intraday Monitor (`backend/scripts/intraday_monitor/`)

- **Purpose**: intraday early-warning that the day's signal is *challenged*. Every 15 min during the London session, fetches the delayed front-month price and alerts the **first time** it crosses an "À surveiller" level (S1/R1), so the user learns of an invalidation while the market is still open — not the next morning. **Layer 2 only**: it does NOT touch the ensemble prediction (J+4-J+5, frozen at eve); the message says "le signal du jour est remis en cause", not "le modèle a eu tort".
- **Fetch**: pure httpx, no Playwright (spike-validated 2026-07-23) — GET the Barchart overview page for the `XSRF-TOKEN` cookie → `core-api/v1/quotes/get?raw=1` → numeric `raw.lastPrice` + `raw.tradeTime`. Job image stays slim (512Mi). Cloud Run egress confirmed unblocked (shadow 24+27/07).
- **Levels from structured columns, never LLM text**: reads `s1`/`r1` from `pl_derived_indicators` at the **last completed session** (the pivots shown on the dashboard today — static all day). The engine never parses `pl_indicator_daily.conclusion`.
- **Idempotence**: first-cross-only per `(rule, session)` — `aud_alert_event` UNIQUE `(rule_id, session_date, crossing_seq)` + `ON CONFLICT DO NOTHING`. A re-cross or a manual re-run never re-sends (validated 2026-07-27: R1 then S1 fired once each, the S1 re-cross was deduped).
- **Rules (config-as-data)**: `ref_alert_rule` seeded with `close_below_s1` (bearish) + `close_above_r1` (bullish). No RSI intraday (daily value isn't frozen in-session).
- **Delivery**: `AlertSender` abstraction — `TelegramSender` (private broadcast channel, one `sendMessage` = fan-out) / `ConsoleSender` (dev/shadow). Channel selected by `ALERT_CHANNEL` env (`console` default, `telegram` live since 2026-07-28). `TELEGRAM_BOT_TOKEN` (Secret Manager) + `TELEGRAM_CHANNEL_ID` (numeric `-100…`, GitHub var). Transport-swappable (a `WhatsAppSender` could be added without touching the engine).
- **Gates**: `should_skip_non_trading_day()` + `in_london_session()` (09:30-16:55 Europe/London, official ICE hours, DST via zoneinfo). Out-of-session tick = exit 0 (Sentry cron = success).
- **Tables**: `pl_contract_data_intraday` (append-only observations), `ref_alert_rule`, `aud_alert_event`. Never writes `pl_contract_data_daily` (EOD truth = 1 row/day).
- **Cron**: `*/15 8-16 * * 1-5` (wide UTC window; the in-code London gate trims the DST edges) — **CLI**: `poetry run intraday-monitor [--dry-run] [--verbose] [--force]`
- **US**: [docs/user-stories/P1-intraday-threshold-alerts-telegram.md](docs/user-stories/P1-intraday-threshold-alerts-telegram.md)

### Known Issues & Lessons (2026-02-18 debugging sessions)

**Bug 1 — Wrong raw block (old scraper)**: Used `re.search` → picked FIRST of 4+ raw blocks. The first block was often a next-month contract or options data → wrong V and OI. Fix: max-volume heuristic picks the block with highest `volume` (always the main contract).

**Bug 2 — CA\*0 roll mismatch**: Barchart's `CA*0` continuous symbol rolls based on volume shift, not calendar. In Feb 2026, Barchart already rolled CA\*0 to CAK26 (May) while we should track CAH26 (March) until Feb 27. The actual roll to CAK26 happened on March 2 (first trading day of March), based on OI crossover. Fix: replaced auto-roll with explicit `ACTIVE_CONTRACT` env var. The scraper always uses the contract code from this env var. CA\*0 is never used in URLs.

**Forensic proof of prod data errors**: Prod OI=36,333 and Close=2,438 matched CAH26's data exactly (`previousPrice=2438`, `openInterest=36333` on the CAH26 page). The human who filled prod was reading the wrong contract page (March instead of May). Prod V=3,625 was the correct raw contract count for CAH26.

**Barchart page structure**: Angular SPA. XHR API (`/proxies/core-api/v1/quotes/get`) returns C/H/L/V as formatted strings (commas) but **omits OI**. Server-rendered inline JSON contains all 5 fields with raw numeric values. `networkidle` never fires (analytics polling) — use `wait_until="load"` + fixed 5s wait.

### Contract Roll Procedure

When OI shifts to the next delivery month (e.g., `CAK26 → CAN26`), follow [docs/runbooks/contract-roll-procedure.md](docs/runbooks/contract-roll-procedure.md). Quick path: `poetry run roll-contract <NEW>` (against GCP via bastion) then trigger `cc-compute-indicators` with `--full --all-versions`. The runbook covers backfill, rollback, past incidents (CAK26→CAN26 bugs), and the dashboard cross-contract fallback (`resolve_contract_for_date()` in `app/utils/contract_resolver.py`) that ensures historical dates resolve correctly across rolls — no gaps when navigating across a roll boundary.

## AI Agents

Four LLM-powered agents run as GCP Cloud Run Jobs, each generating content for PostgreSQL and/or Google Drive. All share the same `backend/Dockerfile`.

### Pipeline Schedule

```
 7:00 PM UTC  -- Barchart scraper       -> pl_contract_data_daily (OHLCV + IV)
 7:00 PM UTC  -- Meteo agent            -> pl_weather_observation (independent)
 7:05 PM UTC  -- ICE stocks + CFTC      -> pl_contract_data_daily (STOCK US, COM NET US)
 7:05 PM UTC  -- Press review agent     -> pl_fundamental_article (needs CLOSE)
 7:15 PM UTC  -- Compute indicators     -> pl_derived_indicators + pl_indicator_daily
 7:18 PM UTC  -- Ensemble compute       -> pl_specialist_prediction + pl_orchestrator_decision + pl_indicator_daily (LIVE — served by the dashboard)
 7:20 PM UTC  -- Daily analysis          -> pl_indicator_daily (LLM decision + score)
 7:30 PM UTC  -- Compass brief          -> Google Drive (.txt for NotebookLM)
```

### Press Review Agent (`backend/scripts/press_review_agent/`)

- **Purpose**: Generates daily French-language cocoa press review from 6 news sources
- **Provider**: OpenAI `o4-mini` (production). Claude and Gemini available via `--provider claude|gemini|all` for testing only.
- **Active flag**: `pl_fundamental_article.is_active` controls which provider's articles the dashboard reads. Set by `PRODUCTION_PROVIDER` in `config.py`. To switch provider, follow [docs/runbooks/press-review-provider-switch.md](docs/runbooks/press-review-provider-switch.md) (code constant + DB `is_active` backfill must happen together).
- **Contract context**: The prompt injects the active contract code and delivery month (e.g., `CAN26`, `2026-07`) so the LLM references the correct contract — not what news sources mention (which may lag behind a roll).
- **Output**: `pl_fundamental_article` (DB)
- **Cron**: `5 19 * * 1-5` — **CLI**: `poetry run press-review [--dry-run]`

### Meteo Agent (`backend/scripts/meteo_agent/`)

- **Purpose**: Fetches weather data from Open-Meteo for 6 cocoa-growing locations (Ghana + Côte d'Ivoire), calls OpenAI (`gpt-4.1`) for French analysis
- **Output**: `pl_weather_observation` (DB)
- **Cron**: `10 19 * * 1-5` — **CLI**: `poetry run meteo-agent [--dry-run]`

### Daily Analysis (`backend/scripts/daily_analysis/`)

- **Purpose**: Core AI analysis engine replacing Make.com DAILY BOT AI. Reads 42 variables from TECHNICALS + news + weather, runs 2 LLM calls (`gpt-4-turbo`), writes trading decisions
- **Contract resolution**: `--contract` flag defaults to active contract from DB (`resolve_active_code()`). Never hardcoded.
- **Transition fallback**: `_read_technicals()` filters by active contract. If < 2 rows found (first days after a roll), falls back to cross-contract read for continuity.
- **LLM Call #1**: Macro/weather analysis → MACROECO_BONUS + ECO → writes to `pl_indicator_daily`
- **LLM Call #2**: Trading decision → DECISION/CONFIANCE/DIRECTION/CONCLUSION → writes to `pl_indicator_daily`
- **Cron**: `20 19 * * 1-5` — **CLI**: `poetry run daily-analysis [--dry-run]`

### Compass Brief (`backend/scripts/compass_brief/`)

- **Purpose**: Generates structured `.txt` brief from pl_* tables, uploads to Google Drive Shared Drive for NotebookLM audio podcast generation
- **Output**: `YYYYMMDD-CompassBrief.txt` uploaded to Drive (idempotent — updates existing file for same date)
- **Cron**: `30 19 * * 1-5` — **CLI**: `poetry run compass-brief`

### Ensemble Explainer (`backend/scripts/ensemble_explainer/`) — thin wrapper around DBAnalysisEngine

- **Purpose**: enriches the ensemble row of `pl_indicator_daily` with the same long-form LLM narrative (`eco`, `confidence`, `direction`, `conclusion` with `> ... • ... > A SURVEILLER AUJOURD'HUI: ...` structure) that `cc-daily-analysis` writes on the legacy row. The decision is IMMUTABLE (pinned to `decision_wrapped` by the engine's auto-align path).
- **Implementation** (refactored 2026-05-27): the job is a **thin wrapper** that invokes `scripts.daily_analysis.db_analysis_engine.DBAnalysisEngine.run()` **without pinning `algorithm_version_name`**. The engine's built-in auto-alignment (db_analysis_engine.py:187-200) detects the ensemble row in `pl_orchestrator_decision`, injects the 25-field diagnostics block via `CALL_2_PROMPT_ENSEMBLE`, and writes the narrative to the ensemble row. No custom prompt / parser / writer in this module — everything is reused from `scripts/daily_analysis/`.
- **Pre-flight**: fail-loud `EnsembleRowMissingError` if `cc-ensemble-compute` has not populated the ensemble row at `data_date` (prevents silent fallback to legacy).
- **Inputs** (via the engine's `DBReader`): `pl_orchestrator_decision` + 14× `pl_specialist_prediction` + `pl_fundamental_article` + `pl_weather_observation` + `pl_contract_data_daily` (last 2 sessions for the today/yesterday technicals snapshot).
- **LLM**: 2 calls `gpt-4-turbo` (Call#1 macro/weather → `eco` + `macroeco_bonus`; Call#2 ensemble-aware → `decision`/`confidence`/`direction`/`conclusion`). ~$0.13/day, ~$30/year.
- **Cron**: `25 19 * * *` (P2b daily-gated, after `cc-ensemble-compute`) — **CLI**: `poetry run ensemble-explainer [--session-date YYYY-MM-DD] [--dry-run] [--force]`

### Compass Brief Ensemble (`backend/scripts/compass_brief_ensemble/`) 🆕 P4

- **Purpose**: dual-track companion to `cc-compass-brief`. Renders the new 7-section brief (signal + 14 specialists decomposition + macro radar + LLM eco + weather + technicals + recommendations), keyed on J+4-J+5 horizon. Reads the ensemble row enriched by cc-ensemble-explainer.
- **Output**: `YYYYMMDD-CompassBrief-Ensemble.txt` uploaded to the same Drive folder as legacy (filename suffix discriminates). NotebookLM produces `YYYYMMDD-CompassAudio-Ensemble.{wav,m4a,mp4}`.
- **Cron**: `35 19 * * *` (P2b daily-gated) — **CLI**: `poetry run compass-brief-ensemble [--session-date YYYY-MM-DD] [--dry-run]`
- **Frontend audio routing**: env var `BRIEF_DEFAULT_VERSION=legacy|ensemble` on backend service drives which audio is served by `/v1/dashboard/audio`. Per-request override via `?version=` query param. Both audios coexist on Drive.
- **Runbooks**: [brief-dual-track.md](docs/runbooks/brief-dual-track.md), [brief-rollback-procedure.md](docs/runbooks/brief-rollback-procedure.md), [brief-ensemble-evolution.md](docs/runbooks/brief-ensemble-evolution.md)

### Ensemble Compute — Campaign 5 (`backend/scripts/ensemble_compute/`)

- **Purpose**: Daily C5 ensemble decision combining 14 LightGBM/GARCH specialists, a Bayesian soft-gate orchestrator, and a Compass-side transition wrapper. **Today the frontend dashboard serves ensemble decisions directly** via `_resolve_algo_for_date()` (row-existence based). The dual-track brief (cc-compass-brief-ensemble + cc-ensemble-explainer) is the latest piece migrating the NotebookLM audio to ensemble while keeping legacy alive in parallel.
- **Vendored R&D code**: `backend/vendor/campaign5_ensemble_v1.0.0/` — read-only delivery, never patched in-place. Override path is subclassing (see `compass_wrapper.py`).
- **Algorithm version**: `ensemble_v1_softgate_wrapper` **v1.0.0 — the ONE continuous version, LIVE** (served by the dashboard; the `is_active/compute_enabled` flags stay FALSE — the ensemble job doesn't gate on them and `compute_enabled=TRUE` would wrongly route it through the power-formula engine). **⚠️ Never ship an ensemble config change as a NEW `pl_algorithm_version`**: the pipeline assumes one continuous version (YTD, wrapper trailing windows, explainer/brief pin it) — the v1.1.0 attempt of 2026-07-22 broke those in cascade and was collapsed (PRs #75→#77). Config changes are versioned via **temporal config** instead (see Compass levers below).
- **Inputs**: `v_contract_data_chained` VIEW (front-month-by-OI chain for GARCH lookback) × `pl_derived_indicators` for market_history; `pl_orchestrator_decision` + `pl_specialist_prediction` for the wrapper trailing window; `pl_article_segment` (confidence ≥ 0.70 segments, 90d window) for the macro signal via `MacroEventLayer`.
- **Outputs**: 14 rows in `pl_specialist_prediction` + 1 row in `pl_orchestrator_decision` (soft-gate + wrapper diagnostics) + 1 row UPSERT in `pl_indicator_daily` (decision = wrapped_decision).
- **Compass wrapper override** (`compass_wrapper.py`): the vendor OR-combines its 4 detectors → every fire becomes MONITOR. Empirically this vetoed 73% of soft-gate commits when `running_acc_5d=0.981`. The Compass subclass adds an AND-gated release: dispersion-only veto is released when `running_acc_5d ≥ threshold` (or NaN bootstrap). Threshold stored in `pl_algorithm_config.compass_wrapper_dispersion_with_acc_threshold` = 0.60 (config-as-data, migration `o9j0k1l2m3n4`). On 2026 backfill: WR coverage 17% → 49% (beats R&D 46.1%), WR accuracy 100% → 76% (target ≥ 80%; gap is cold-start NaN, accepted).
- **Compass levers — TEMPORAL config-as-data (retune C5-full 2026-07-22, migration `g2b3c4d5e6f7`)**: `pl_algorithm_config` is **append-only** (`effective_from DATE` + `active BOOLEAN`, unique on `(version, param, effective_from)`) — a config change INSERTs a new row (old value preserved = provenance), a removal INSERTs an `active=false` tombstone; the runtime reads the VIEW **`v_algorithm_config_current`** (latest active row per param, all loaders go through it). Current levers (effective 2026-07-22, tuned on corrected indicators — dir-acc 75→88% full / 57→87.5% recent, actionable 14→35%): **alpha_macro cap 0.9→`0.3`** (dominant lever — the LLM press macro signal is noisy, over-weighted it hurts), **`commit_threshold=0.15`** (soft-gate band, now wired from config in `ensemble_compute/main.py`), **trend-conflict on with `wrapper_tau_trend=0.05`** (0.03 over-vetoed), **regime-MONITOR OFF** (tombstone — veto-precision 0.14 on corrected data, its premise was a corruption artifact; code path remains config-gated). Published decision = `soft-gate(capped 0.3) → wrapper → [regime-MONITOR if configured]`; `pl_indicator_daily.decision` carries the final. Tuning/rollback (append pattern, never UPDATE/DELETE): [docs/runbooks/wrapper-levers-tuning.md](docs/runbooks/wrapper-levers-tuning.md).
- **Bootstrap**: `cc-ensemble-bootstrap-artifacts` (deployed without scheduler, manual trigger) seeds 38 BYTEA rows in `pl_model_artifact` from the frozen R&D pack. Re-run only when R&D ships v1.1.0+.
- **Cron**: `18 19 * * *` (P2b daily, eve-of-trading gate — fires Mon-Thu eve and Sunday eve; skips Friday + Saturday eves). Writes for `data_date = previous_session(next_session(today))` (= today mid-week, = Friday on Sunday eve). This is the move that lets the MacroSignal incorporate weekend news: Sunday 19:05 press-review writes article_segments with `article_date = Friday`, Sunday 19:18 ensemble-compute reads them before deciding Friday's row. — **CLI**: `poetry run ensemble-compute [--session-date YYYY-MM-DD] [--historical] [--dry-run]`
- **Failure recovery**: [docs/runbooks/ensemble-failure-recovery.md](docs/runbooks/ensemble-failure-recovery.md).

## Code Quality

- **Backend**: Ruff for linting/formatting, Pyright for type checking
- **Frontend**: ESLint + Prettier for code quality, TypeScript strict mode
- **Pre-commit**: Husky runs backend pre-commit hooks (ruff, pyright) + frontend lint:fix
- **Backend pre-commit**: Hooks scoped to `^backend/` files (trailing whitespace, EOF fixer, YAML/TOML validation, ruff, pyright)
- **Poetry**: Python 3.11+ dependency management with application mode (`package-mode = false`)

## API Structure

All API endpoints are prefixed with `/v1` and include:

- `/auth/*` - Authentication endpoints:
  - `GET /auth/me` - Get current user info from token
  - `GET /auth/verify` - Verify token validity
- `/dashboard/*` - Trading dashboard data (all require auth):
  - `GET /dashboard/position-status` - Position (OPEN/HEDGE/MONITOR) and YTD performance (server-side scoring)
  - `GET /dashboard/indicators-grid` - All indicators with color ranges for gauges
  - `GET /dashboard/recommendations` - Parsed trading recommendations from technicals.score
  - `GET /dashboard/chart-data` - Historical data for charting (1-365 days)
  - `GET /dashboard/news` - Latest market research article
  - `GET /dashboard/weather` - Latest weather update and market impact
  - `GET /dashboard/farmgate-price` - Official/guaranteed farmgate price (CIV/CCC + Ghana/COCOBOD), latest effective ≤ date per region. Append-only `pl_official_farmgate_price`; ops entry via `poetry run set-farmgate-price`. Distinct from the real terrain price (Programme Fondateur).
  - `GET /dashboard/audio` - Audio file metadata with backend streaming URL
  - `GET /dashboard/latest-indicator` - Legacy stub (use `/indicators-grid` instead)
  - `GET /dashboard/dashboard-data` - Legacy stub (use specific endpoints instead)
  - `GET /dashboard/summary` - Legacy stub (returns mock summary)
- `/audio/*` - Audio streaming:
  - `GET /audio/stream` - Stream audio from Google Drive (no auth, for HTML audio element)
  - `GET /audio/info` - Audio metadata (requires auth)
- `/data/*` - Data series export (requires auth, CSV only):
  - `GET /data/export?series=…&from=YYYY-MM-DD&to=YYYY-MM-DD&format=csv` - Streams a `pl_*` series as a CSV attachment over an inclusive date range. Series: `ohlcv`, `indicators`, `fx`, `cot_eu`, `cot_us`, `stocks`, `weather`. `ohlcv`/`indicators` read the roll-safe `v_contract_data_chained` view (front-month by OI/volume). Any valid Auth0 user (single shared-view model — no keys/quotas/metering; that's the co-construct Enterprise API). Rate-limited 30/min. Service: `app/services/export_service.py`.
- `/dashboard/non-trading-days` - Exchange holidays + latest display_date for calendar:
  - `GET /dashboard/non-trading-days?year=2026` - Returns non-trading weekday dates and `latest_trading_day` (= `MAX(display_date)` from actual data)

## Google Drive Audio Integration

The application integrates with Google Drive to fetch daily audio bulletins for the position status component.

### Audio File Requirements

- **File naming pattern**: `YYYYMMDD-CompassAudio.{wav|m4a|mp4}`
  - Example: `20250109-CompassAudio.wav`, `20250109-CompassAudio.m4a`, or `20250109-CompassAudio.mp4`
- **Supported formats**: `.wav`, `.m4a`, and `.mp4` files
- **Location**: Must be stored in a specific Google Drive folder
- **Business date handling**: Weekend dates automatically convert to previous Friday

### Setting Up Google Drive Integration

1. **Find your Google Drive folder ID**:
   - Open Google Drive in your browser
   - Navigate to the folder containing your audio files
   - Look at the URL in your browser's address bar
   - The URL will look like: `https://drive.google.com/drive/folders/1A2B3C4D5E6F7G8H9I0J`
   - Copy the folder ID (the part after `/folders/`) - in this example: `1A2B3C4D5E6F7G8H9I0J`

2. **Configure environment variables**:

   ```bash
   # Required: Google Drive folder ID containing audio files
   GOOGLE_DRIVE_AUDIO_FOLDER_ID="1A2B3C4D5E6F7G8H9I0J"

   # Google Drive credentials (service account with Drive API access)
   GOOGLE_DRIVE_CREDENTIALS_JSON='{...}'
   ```

3. **Google Drive API permissions**:
   - The service account must have read access to the specified folder
   - Requires `https://www.googleapis.com/auth/drive.readonly` scope

### Audio Endpoints

- **GET `/v1/audio/stream`** - Streams audio through backend proxy (no auth required for HTML audio element compatibility)
  - Supports Accept-Ranges, Content-Disposition, Cache-Control (1 hour)
- **GET `/v1/audio/info`** - Returns metadata with backend streaming URL (requires auth)
- **GET `/v1/dashboard/audio`** - Returns audio metadata for dashboard (requires auth)

### Frontend Integration

The `PositionStatus` component automatically fetches and plays the audio file:

- Loads audio URL dynamically from the API
- Audio player with play/pause, progress slider, time display
- Shows loading state while fetching
- Displays error messages if file not found
- Supports .wav, .m4a, and .mp4 formats seamlessly

## Deployment

- **Custom domain**: `app.com-compass.com` (frontend), `api.com-compass.com` (backend). Routed via Global HTTPS Load Balancer (static IP `34.36.87.103`) with Google-managed SSL certificates. Old `*.run.app` URLs still work in parallel.
- **Platform**: GCP Cloud Run (region `europe-west9`).
- **Load Balancer**: Global HTTPS LB with serverless NEGs. Required because Cloud Run domain mappings are not supported in `europe-west9`. Terraform-managed in `infra/terraform/loadbalancer.tf`. HTTP→HTTPS redirect included.
- **CI/CD**: `.github/workflows/deploy.yml` — push to `main` triggers CI (lint + test) → Deploy (backend + frontend + all Cloud Run Jobs).
- **Backend**: `backend/Dockerfile` (Python 3.11-slim, no Playwright, ~200MB). Alembic migrations on startup via `start.sh`. Cloud Run: 512Mi, 1 CPU, max 2 instances, VPC connector for Cloud SQL.
- **Frontend**: `frontend/Dockerfile` (Node 18-alpine, serve static). Auth0 vars baked at build time via `--build-arg` from GitHub vars. Cloud Run: 256Mi, 1 CPU, max 2 instances. CSP in `index.html` whitelists `*.com-compass.com`, `*.auth0.com`, `*.sentry.io`.
- **Cloud Run Jobs**: `backend/Dockerfile.jobs` (with Playwright, ~1GB). All jobs deployed via deploy.yml (~20 catalogued + backfill/bootstrap utilities). `ENTRYPOINT ["poetry", "run"]`, command passed via job args. No retries (--max-retries=0). `cc-intraday-monitor` is httpx-only (512Mi, no Playwright).
- **Cloud Scheduler**: cron jobs in `europe-west1` (scheduler doesn't support `europe-west9`). Triggers Cloud Run Job execution via HTTP + OAuth. Schedules span the day: FX 18:30 → evening pipeline 19:00-19:35 → publish-gate 20:00-09:30 → daytime fundamentals 13:00-16:00 → intraday alerts 08:00-16:00 (*/15) → monthly ENSO. No retries (retryCount=0).
- **Secrets**: GCP Secret Manager (13 secrets). Non-sensitive env vars via GitHub Vars → deploy.yml `--set-env-vars`.
- **Auth**: Workload Identity Federation (keyless GitHub → GCP auth). No SA key files in CI/CD.
- **Infra as code**: `infra/terraform/` — Cloud SQL, VPC connector, service accounts, schedulers, load balancer.
- **DNS**: Managed via Squarespace Domains (registered under Google Workspace). A records for `app` and `api` subdomains point to LB static IP. Domain root (`com-compass.com`) unchanged (Squarespace site).

### Nightly Pipeline Schedule (UTC, weekdays)

P2b — the pipeline is split into two phases:

**Phase A — Market close** (T 19:00 UTC, Mon-Fri): scrapers + indicator computation. `date` field on every row = session date T.

**Phase B — Next-session refresh** (daily cron, agent-gated on `is_eve_of_trading_day()`): meteo, press review, **ensemble compute**, daily analysis, ensemble explainer, compass brief(s). All 7 jobs share one date helper — `scripts/db.py:resolve_phase_b_dates(session_date)` returns the immutable `PhaseBDates(target_date, data_date)` pair, and `phase_b_should_skip()` owns the gate; no main re-derives dates. The operator flag is uniform **`--session-date T`** (= the row date to regenerate = `data_date`); `target_date = next_session(T)` is derived internally for prompt framing / filename / Sentry context only. Every Phase B DB write is keyed to `data_date = T`, keeping `pl_indicator_daily`, `pl_fundamental_article`, `pl_weather_observation`, `pl_orchestrator_decision` all consistent on a single `session_date = T`, which is what the dashboard's `_parse_and_validate_date()` resolves from `display_date = next_trading_day(T)`. Past P2b drift on this convention manifests as empty dashboard sections the morning after — see PR #15 (consumers), PR #16 (press/meteo producers), PR #17 (ensemble_explainer = wrapper), PR #35 (ensemble_compute migration). **Critical for the weekend**: ensemble-compute fires Sunday eve (eve of Monday=trading), reading the just-written pl_article_segment from Sunday 19:05 press-review with `article_date = Friday`. This is how the ensemble decision for Friday's session incorporates news that broke during the weekend.

```
# Phase A — weekday-only, keyed to session date T:
18:30  cc-fx-scraper                  → pl_external_indicator (FX, ECB)
19:00  cc-barchart-scraper            → pl_contract_data_daily (OHLCV + IV)
19:05  cc-ice-stocks-scraper          → pl_contract_data_daily (STOCK US)
19:05  cc-cftc-scraper                → pl_contract_data_daily (COM NET US)
19:10  cc-barchart-stocks-eu-scraper  → pl_contract_data_daily (stock_eu_bags60kg)
19:15  cc-compute-indicators          → pl_derived_indicators + pl_indicator_daily
22:10  cc-ice-cot-eu-scraper          → pl_cot_eu_weekly (ICE EU COT positioning)

# Phase B — daily cron, agent-gated on eve-of-trading-day, keyed to T+next:
19:00  cc-meteo-agent                 → pl_weather_observation (row date = data_date = T)
19:05  cc-press-review-agent          → pl_fundamental_article + pl_article_segment (row date = data_date = T)
19:18  cc-ensemble-compute            → pl_orchestrator_decision + 14 specialist_prediction + ensemble row (date = T)
19:20  cc-daily-analysis --algorithm-version legacy → UPDATE pl_indicator_daily LEGACY row at date=T
19:25  cc-ensemble-explainer          → invokes DBAnalysisEngine (auto-align) → UPDATE ENSEMBLE row at date=T
19:30  cc-compass-brief               → Drive: YYYYMMDD-CompassBrief.txt (legacy)
19:35  cc-compass-brief-ensemble      → Drive: YYYYMMDD-CompassBrief-Ensemble.txt

# Publication gate — every 30 min, evening → 09:30 UTC next morning:
20:00-09:30  cc-publish-session      → pl_session_release (atomic dashboard flip once data+audio ready)

# Intraday alerts — every 15 min DURING the London session (in-code gate):
08:00-16:00 (*/15)  cc-intraday-monitor → pl_contract_data_intraday + aud_alert_event + Telegram

# Daytime fundamentals — calendar-gated against ref_publication_calendar:
13:00  cc-eca-grindings-scraper      → pl_supply_demand_observation (ECA)
14:00  cc-nca-grindings-scraper      → pl_supply_demand_observation (NCA)
16:00  cc-publication-calendar-watchdog → Sentry alert if overdue ≥ 21d

# Monthly:
22:00 on the 20th  cc-enso-scraper    → pl_external_indicator (ENSO ONI + Niño 3.4)
```

Notes:
- Phase B daily cron + in-agent gate eliminates the Sun→Mon ~60h freshness gap that Phase B used to have when it was weekday-only. On Sun eve at 19:20 UTC the agents fire and tag their writes to Mon's session date.
- The ECA + NCA scrapers gate against `ref_publication_calendar` (not the trading calendar) and exit 0 cleanly on the ~250 weekdays per year when no quarterly publication is pending. Watchdog escalates "expected but not ingested" rows past a 21-day grace window.
- Sentry cron monitors interpret Phase B "skip on non-eve-of-trading-day" as success (exit 0) — no false-positive alerts on weekends + holidays.
- **Dual-track brief** (legacy + ensemble) : `cc-compass-brief` (LEGACY) et `cc-compass-brief-ensemble` (NEW P4) tournent en parallèle chaque jour de session. 2 audios NotebookLM produits par jour. Audio servi par le frontend dépend de `BRIEF_DEFAULT_VERSION` env var (default `legacy`) — flip via `gcloud run services update backend --update-env-vars BRIEF_DEFAULT_VERSION=ensemble`. Per-request override `?version=ensemble`. Voir [docs/runbooks/brief-dual-track.md](docs/runbooks/brief-dual-track.md).
- **Publication gate** (`cc-publish-session`) : the dashboard's "latest session" is gated on `pl_session_release`. The job runs every 30 min (evening → 09:30 UTC next morning) and stamps a session once its data is complete AND the NotebookLM audio is present → the dashboard flips **atomically the same evening** (all sections + audio), not the next-morning `display_date`. Morning fallback (past `display_date(T)` 09:00 UTC) releases data-only so a late audio never freezes the dashboard. Endpoint gate has a safe fallback to the legacy `MAX(display_date) <= today()` while the table is empty (non-breaking). Voir [docs/runbooks/session-publish-gate.md](docs/runbooks/session-publish-gate.md).

When a job fails, follow [docs/runbooks/pipeline-failure-recovery.md](docs/runbooks/pipeline-failure-recovery.md) — covers diagnosis, root-cause categories, and the cascade of jobs to re-run based on the dependency graph. Pipeline jobs are configured fail-loud, no auto-retry (see `.claude/rules/pipeline-error-handling.md`).

## Sentry Triage

For terminal-first error triage (Claude or human): see [docs/runbooks/sentry-triage.md](docs/runbooks/sentry-triage.md). Covers the `curl` + `jq` query patterns, tag conventions (`service`, `release`, `environment`), and the Claude triage loop pseudocode. **Hard rule**: the local `SENTRY_AUTH_TOKEN` is a user token with strictly read-only scopes (`event:read`, `project:read`, `org:read`) — never grant write scopes for local use. The CI uses a separate org token (`org:ci` scope) stored as a GitHub Actions Secret, never in `~/.zshrc`.

## Development Notes

- Backend uses Poetry scripts: `poetry run dev`, `poetry run lint`, `poetry run daily-analysis`, `poetry run meteo-agent`, `poetry run compass-brief`, `poetry run press-review`, `poetry run barchart-scraper`, `poetry run ice-stocks-scraper`, `poetry run cftc-scraper`, `poetry run compute-indicators`, `poetry run set-farmgate-price`, `poetry run seed-gcp`, `poetry run seed-trading-calendar`
- Frontend environment variables exposed via custom Vite `define` config (no VITE_ prefix needed)
- Database migrations managed via Alembic (migrations are idempotent for safe GCP re-application)
- Pre-commit hooks run via Husky (backend: ruff + pyright, frontend: eslint fix)
- Development setup script available at `scripts/setup-dev.sh`
- Node.js 18+ and pnpm required (see root `package.json` engines)
- **Always use pnpm** instead of npm for all JavaScript/TypeScript dependency management and script execution
- **GCP env var gotcha**: `gcloud run services update --set-env-vars` REPLACES all env vars. Use `--update-env-vars` to add/update without wiping existing vars.
- **Auth0 + React Router gotcha**: Never use bare `<Navigate>` on the Auth0 callback route. `Navigate` runs in `useLayoutEffect` and strips `?code=` params before Auth0Provider's `useEffect` can read them. Use a wrapper that waits for `isLoading=false`.
- **DB access (GCP prod)**: Cloud SQL is private IP only, reached via an **ephemeral IAP bastion**. Use `.local/db-prod.sh` (gitignored, holds the prod password): `up` CREATES the VM on demand — trying europe-west9 zones a→b→c until one has capacity (that zone is intermittently full) — and opens the tunnel on `:5434`; `psql`/`exec`/`csv` run queries; `down` closes the tunnel and DELETES the VM (~1m30 cold create, acceptable). The bastion is NOT Terraform-managed (only its SA + IAM + IAP-SSH firewall are — see `infra/terraform/bastion.tf`). For a raw manual tunnel: `gcloud compute ssh cc-bastion --zone <zone> --tunnel-through-iap --project cacaooo -- -N -L 5434:10.119.160.3:5432` then `psql -h 127.0.0.1 -p 5434 -U cc_app -d commodities_compass`.
- **DB sync from GCP**: `poetry run python scripts/sync_from_gcp.py` copies all `pl_*` / `ref_*` / `aud_*` tables from GCP Cloud SQL to local (use before generating Alembic autogenerate migrations). Full procedure including bastion tunnel setup and troubleshooting: [docs/runbooks/db-sync-from-gcp.md](docs/runbooks/db-sync-from-gcp.md).

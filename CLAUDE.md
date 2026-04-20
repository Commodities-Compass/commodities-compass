# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Commodities Compass is a Business Intelligence application for commodities trading, providing real-time market insights, technical analysis, and trading signals for cocoa (ICE contracts). This is a monorepo with a FastAPI backend and React frontend, using Auth0 for authentication and PostgreSQL (GCP Cloud SQL) for data storage. Deployed on GCP Cloud Run with 8 automated Cloud Run Jobs (scrapers, agents, compute engine). Dashboard reads from `pl_*` tables. Google Sheets is no longer used as a data source — all data flows through PostgreSQL. Google Drive is still used for audio (NotebookLM) and brief uploads.

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
  - `endpoints/commodities.py` - Commodity information (stub/mock data, TODO)
  - `endpoints/historical.py` - Historical data endpoints (stub/mock data, TODO)
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

The frontend uses modern React patterns:

- **Auth0 Integration** - `main.tsx` sets up Auth0Provider with localStorage caching and refresh tokens
- **API Layer** - `src/api/` contains:
  - `client.ts` - Axios client with automatic token injection and 401 interceptor (dispatches `auth:token-expired` event)
  - `dashboard.ts` - Dashboard API service functions for all endpoints
- **State Management** - React Query (TanStack Query) — global default stale time is 5 minutes (`main.tsx`), but all dashboard hooks in `useDashboard.ts` override to 24-hour stale time (no auto-refetch) since trading data updates once daily
- **Routing** - React Router with `ProtectedRoute` wrapper requiring authentication
  - `/` → `RootRedirect` (waits for Auth0 `isLoading` before redirecting to `/dashboard` — prevents stripping `?code=` callback params)
  - `/login` - Auth0 login page with redirect loop detection and error display
  - `/dashboard` - Main trading dashboard (protected)
  - `/dashboard/historical` - Historical data view (protected)
- **Favicon** - `frontend/public/favicon-32x32.png` (transparent background, circle only) + `frontend/public/apple-touch-icon.png` (180x180, white background for mobile dark mode). Generated from `src/assets/compass-icon.png`.
- **UI Components** - Shadcn/ui (new-york style) with Radix UI primitives in `src/components/ui/`
- **Dashboard Components**:
  - `SignalHero` - Hero panel for trading signal (OPEN/HEDGE/MONITOR) as a pill badge with colored ring + dot, plus YTD performance. Replaces the old `PositionStatus` component.
  - `PodcastPlayer` - Audio player with SoundCloud-style waveform bars (48 bars, click-to-seek, progress coloring). Uses `<audio preload="auto">` to buffer audio on page load — play is near-instant. Shows a loading spinner until `canplay` fires, then during mid-playback buffering stalls. Waveform is cosmetic (deterministic pseudo-random bars), not computed from audio data. Replaces the old audio player from `PositionStatus`.
  - `MarketAnalysis` - Unified card: 6 gauge indicators (MACROECO/MACD/VOL-OI/RSI/%K/ATR) + analysis bullets with direction dots + "À surveiller" watchlist box
  - `GaugeIndicator` - SVG semi-circular gauge with color zones (RED/ORANGE/GREEN), tooltip with indicator metadata
  - `PriceChart` - Recharts area chart with metric/days selector and zoom controls
  - `NewsCard` - Tabbed press review (Technique/Fondamentaux/Synthèse) with inline formatting for financial text
  - `WeatherUpdateCard` - Campaign health bars, location diagnostics grid, market impact bar
  - `DashboardLayout` - Desktop: collapsible sidebar with logo, nav, user profile dropdown. Mobile (<768px): sidebar hidden, replaced by slim top bar with hamburger menu (theme toggle, logout). User profile shows derived display name (Auth0 name or capitalized email prefix) with 2-letter initials avatar and email subtitle.
  - `DateSelector` - Trading day navigation with calendar picker (disables weekends, exchange holidays, and future dates via `/non-trading-days` API)
  - `DatePickerWithRange` - Date range picker with two-month calendar view
  - `LoadingSpinner` - Full-screen centered spinner
- **Dashboard Layout**:
  - Hero row: 50/50 grid (`grid-cols-2`) — `SignalHero` (left) + `PodcastPlayer` (right). Stacks vertically on mobile.
  - Below: `MarketAnalysis` → `PriceChart` → `NewsCard` → `WeatherUpdateCard` in vertical stack
- **Custom Hooks**:
  - `useAuth.ts` - Auth0 token management wrapper
  - `useDashboard.ts` - React Query hooks for all dashboard endpoints (24h stale time, no auto-refetch)
  - `use-mobile.tsx` - Mobile breakpoint detection
- **Types** - `src/types/dashboard.ts` for all API response type definitions
- **Data** - `src/data/commodities-data.ts` for chart metric options and mock data

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

8 Cloud Run Jobs run on Cloud Scheduler (19:00-20:15 UTC weekdays). All scrapers write to `pl_contract_data_daily` (GCP Cloud SQL). The indicator computation engine (`app/engine/`) replaces the former Google Sheets formula engine:

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

Three automated scrapers feed `pl_contract_data_daily`. Each runs as a GCP Cloud Run Job using `backend/Dockerfile.jobs` (with Playwright).

### Architecture

```
pl_contract_data_daily row:
  date | display_date | close | high | low | volume | oi | iv | stock_us | com_net_us
  ──── barchart-scraper (inserts OHLCV+IV+display_date) ─  ──ice──   ──cftc──
                                                          (update)  (update)
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

### Known Issues & Lessons (2026-02-18 debugging sessions)

**Bug 1 — Wrong raw block (old scraper)**: Used `re.search` → picked FIRST of 4+ raw blocks. The first block was often a next-month contract or options data → wrong V and OI. Fix: max-volume heuristic picks the block with highest `volume` (always the main contract).

**Bug 2 — CA\*0 roll mismatch**: Barchart's `CA*0` continuous symbol rolls based on volume shift, not calendar. In Feb 2026, Barchart already rolled CA\*0 to CAK26 (May) while we should track CAH26 (March) until Feb 27. The actual roll to CAK26 happened on March 2 (first trading day of March), based on OI crossover. Fix: replaced auto-roll with explicit `ACTIVE_CONTRACT` env var. The scraper always uses the contract code from this env var. CA\*0 is never used in URLs.

**Forensic proof of prod data errors**: Prod OI=36,333 and Close=2,438 matched CAH26's data exactly (`previousPrice=2438`, `openInterest=36333` on the CAH26 page). The human who filled prod was reading the wrong contract page (March instead of May). Prod V=3,625 was the correct raw contract count for CAH26.

**Barchart page structure**: Angular SPA. XHR API (`/proxies/core-api/v1/quotes/get`) returns C/H/L/V as formatted strings (commas) but **omits OI**. Server-rendered inline JSON contains all 5 fields with raw numeric values. `networkidle` never fires (analytics polling) — use `wait_until="load"` + fixed 5s wait.

### Contract Roll Procedure

Rolling the active contract (e.g., CAK26 → CAN26) when OI shifts to the next delivery month:

1. **Backfill** (optional but recommended): Insert 5-10 days of the new contract's OHLCV+OI into `pl_contract_data_daily` from Barchart charts. Copy `stock_us`/`com_net_us` from the old contract's rows (commodity-level, same values). This smooths the price transition — the compute engine's `DISTINCT ON (date) ORDER BY oi DESC` picks the front-month automatically at the OI crossover.
2. **Roll**: `poetry run roll-contract CAN26` (or direct SQL: `UPDATE ref_contract SET is_active = false WHERE is_active = true; UPDATE ref_contract SET is_active = true WHERE code = 'CAN26';`). Run against GCP prod via bastion — the CLI uses the local `.env` DATABASE_URL.
3. **Deploy** code if any fixes were made, then **recompute**: `gcloud run jobs execute cc-compute-indicators --args="compute-indicators,--all-contracts,--all-versions,--full" --region=europe-west9 --project=cacaooo`
4. **Verify**: Check `pl_indicator_daily` has rows for the new contract, check dashboard shows new contract data.

**Bugs fixed during CAK26→CAN26 roll (2026-04-14):**
- Daily analysis had hardcoded `--contract CAK26` default — now resolves from DB via `resolve_active_code()`
- Daily analysis `_read_technicals()` SQL had no contract filter — now filters by active contract with cross-contract fallback for transition days
- Compass brief queries had no contract filter — now all queries filter by `ref_contract.is_active = true`
- Compute engine `load_all_market_data()` could interleave overlapping contract data — now uses `DISTINCT ON (date) ORDER BY oi DESC` to pick front-month per date
- Press review prompt didn't include active contract info — LLM guessed "mai" from news sources instead of "juillet". Now injects `contract_code` and `contract_month` into the prompt template

**Dashboard cross-contract fallback (2026-04-20):**
After the roll, navigating to historical dates (before the roll) showed empty gauges, no recommendations, and broken YTD — because all dashboard queries filtered by `contract_id = active_contract` (CAN26), but pre-roll data lives on CAK26. During transition days (April 10-13), both contracts have rows but only the old one (CAK26) has complete data (conclusion from daily analysis).

Fix: `_resolve_contract_for_date()` in `dashboard_service.py` resolves the best contract for any historical date, with priority:
1. Active contract with complete data (conclusion IS NOT NULL)
2. Any contract with complete data for that date (cross-contract fallback)
3. Active contract with any row (indicators without conclusion)
4. Any contract with market data (highest OI = front-month heuristic)

YTD performance uses a separate cross-contract query (`DISTINCT ON (date) ORDER BY oi DESC`) to span contract rolls seamlessly over the full year.

This ensures the dashboard always shows the best available data regardless of which contract was active at that historical date. The fallback is transparent to the user — no gaps when navigating across a roll boundary.

## AI Agents

Four LLM-powered agents run as GCP Cloud Run Jobs, each generating content for PostgreSQL and/or Google Drive. All share the same `backend/Dockerfile`.

### Pipeline Schedule

```
 7:00 PM UTC  -- Barchart scraper       -> pl_contract_data_daily (OHLCV + IV)
 7:00 PM UTC  -- Meteo agent            -> pl_weather_observation (independent)
 7:05 PM UTC  -- ICE stocks + CFTC      -> pl_contract_data_daily (STOCK US, COM NET US)
 7:05 PM UTC  -- Press review agent     -> pl_fundamental_article (needs CLOSE)
 7:15 PM UTC  -- Compute indicators     -> pl_derived_indicators + pl_indicator_daily
 7:20 PM UTC  -- Daily analysis          -> pl_indicator_daily (LLM decision + score)
 7:30 PM UTC  -- Compass brief          -> Google Drive (.txt for NotebookLM)
```

### Press Review Agent (`backend/scripts/press_review_agent/`)

- **Purpose**: Generates daily French-language cocoa press review from 6 news sources
- **Provider**: OpenAI `o4-mini` (production). Claude and Gemini available via `--provider claude|gemini|all` for testing only.
- **Active flag**: `pl_fundamental_article.is_active` controls which provider's articles the dashboard reads. Set by `PRODUCTION_PROVIDER` in `config.py`. To switch provider: update `PRODUCTION_PROVIDER` + backfill `UPDATE pl_fundamental_article SET is_active = true WHERE llm_provider = '<new>'`.
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
  - `GET /dashboard/audio` - Audio file metadata with backend streaming URL
  - `GET /dashboard/latest-indicator` - Legacy stub (use `/indicators-grid` instead)
  - `GET /dashboard/dashboard-data` - Legacy stub (use specific endpoints instead)
  - `GET /dashboard/summary` - Legacy stub (returns mock summary)
- `/audio/*` - Audio streaming:
  - `GET /audio/stream` - Stream audio from Google Drive (no auth, for HTML audio element)
  - `GET /audio/info` - Audio metadata (requires auth)
- `/dashboard/non-trading-days` - Exchange holidays + latest display_date for calendar:
  - `GET /dashboard/non-trading-days?year=2026` - Returns non-trading weekday dates and `latest_trading_day` (= `MAX(display_date)` from actual data)
- `/commodities/*` - Commodity information (stub/mock data, TODO)
- `/historical/*` - Historical data and indicators (stub/mock data, TODO)

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
- **CI/CD**: `.github/workflows/deploy.yml` — push to `main` triggers CI (lint + test) → Deploy (backend + frontend + 8 Cloud Run Jobs).
- **Backend**: `backend/Dockerfile` (Python 3.11-slim, no Playwright, ~200MB). Alembic migrations on startup via `start.sh`. Cloud Run: 512Mi, 1 CPU, max 2 instances, VPC connector for Cloud SQL.
- **Frontend**: `frontend/Dockerfile` (Node 18-alpine, serve static). Auth0 vars baked at build time via `--build-arg` from GitHub vars. Cloud Run: 256Mi, 1 CPU, max 2 instances. CSP in `index.html` whitelists `*.com-compass.com`, `*.auth0.com`, `*.sentry.io`.
- **Cloud Run Jobs**: `backend/Dockerfile.jobs` (with Playwright, ~1GB). 8 jobs deployed via deploy.yml. `ENTRYPOINT ["poetry", "run"]`, command passed via job args. No retries (--max-retries=0).
- **Cloud Scheduler**: 8 cron jobs in `europe-west1` (scheduler doesn't support `europe-west9`). Triggers Cloud Run Job execution via HTTP + OAuth. Schedule: 19:00-20:15 UTC weekdays. No retries (retryCount=0).
- **Secrets**: GCP Secret Manager (13 secrets). Non-sensitive env vars via GitHub Vars → deploy.yml `--set-env-vars`.
- **Auth**: Workload Identity Federation (keyless GitHub → GCP auth). No SA key files in CI/CD.
- **Infra as code**: `infra/terraform/` — Cloud SQL, VPC connector, service accounts, schedulers, load balancer.
- **DNS**: Managed via Squarespace Domains (registered under Google Workspace). A records for `app` and `api` subdomains point to LB static IP. Domain root (`com-compass.com`) unchanged (Squarespace site).

### Nightly Pipeline Schedule (UTC, weekdays)

```
19:00  cc-barchart-scraper      → pl_contract_data_daily (OHLCV + IV)
19:00  cc-meteo-agent           → pl_weather_observation
19:05  cc-ice-stocks-scraper    → pl_contract_data_daily (STOCK US)
19:05  cc-cftc-scraper          → pl_contract_data_daily (COM NET US)
19:05  cc-press-review-agent    → pl_fundamental_article
19:15  cc-compute-indicators    → pl_derived_indicators + pl_indicator_daily
19:20  cc-daily-analysis        → pl_indicator_daily (LLM decision + score)
19:30  cc-compass-brief         → Google Drive (.txt for NotebookLM)
```

## Development Notes

- Backend uses Poetry scripts: `poetry run dev`, `poetry run lint`, `poetry run daily-analysis`, `poetry run meteo-agent`, `poetry run compass-brief`, `poetry run press-review`, `poetry run barchart-scraper`, `poetry run ice-stocks-scraper`, `poetry run cftc-scraper`, `poetry run compute-indicators`, `poetry run seed-gcp`, `poetry run seed-trading-calendar`
- Frontend environment variables exposed via custom Vite `define` config (no VITE_ prefix needed)
- Database migrations managed via Alembic (migrations are idempotent for safe GCP re-application)
- Pre-commit hooks run via Husky (backend: ruff + pyright, frontend: eslint fix)
- Development setup script available at `scripts/setup-dev.sh`
- `commodities` and `historical` API endpoints return mock data (TODO: implement database queries)
- Node.js 18+ and pnpm required (see root `package.json` engines)
- **Always use pnpm** instead of npm for all JavaScript/TypeScript dependency management and script execution
- **GCP env var gotcha**: `gcloud run services update --set-env-vars` REPLACES all env vars. Use `--update-env-vars` to add/update without wiping existing vars.
- **Auth0 + React Router gotcha**: Never use bare `<Navigate>` on the Auth0 callback route. `Navigate` runs in `useLayoutEffect` and strips `?code=` params before Auth0Provider's `useEffect` can read them. Use a wrapper that waits for `isLoading=false`.
- **DB access (GCP prod)**: Cloud SQL is private IP only. Use the IAP bastion tunnel: `gcloud compute ssh cc-bastion --zone europe-west9-a --tunnel-through-iap --project cacaooo -- -N -L 5434:10.119.160.3:5432`, then connect via `psql -h 127.0.0.1 -p 5434 -U cc_app -d commodities_compass`. Works with DBeaver and any PostgreSQL client. See `infra/INFRASTRUCTURE.md` for full details.
- **DB sync from GCP**: `poetry run python scripts/sync_from_gcp.py` copies all pl_*/ref_*/aud_* tables from GCP Cloud SQL to local. Requires the IAP bastion tunnel running (see above) and `GCP_DATABASE_URL=postgresql+psycopg2://cc_app:<pass>@localhost:5434/commodities_compass`. Use before generating Alembic autogenerate migrations.

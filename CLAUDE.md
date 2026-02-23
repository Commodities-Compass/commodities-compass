# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Commodities Compass is a Business Intelligence application for commodities trading, providing real-time market insights, technical analysis, and trading signals for cocoa (ICE contracts). This is a monorepo with a FastAPI backend and React frontend, using Auth0 for authentication and PostgreSQL for data storage. Data is imported from Google Sheets via an ETL pipeline and updated daily via Make.com automations.

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
- `poetry run import` - Run Google Sheets data import
- `poetry install` - Install Python dependencies
- `poetry run alembic upgrade head` - Run database migrations
- `poetry run pytest` - Run backend tests

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

- **`app/main.py`** - FastAPI application entry point with CORS, request logging middleware, exception handling, and OpenAPI/Auth0 schema configuration
- **`app/core/`** - Core functionality:
  - `config.py` - Pydantic settings with environment variable management
  - `auth.py` - Auth0 JWT token verification with JWKS caching (6-hour TTL) and user extraction
  - `security.py` - Password hashing (bcrypt) and token utilities
  - `database.py` - Async SQLAlchemy setup with dual engines (async for app, sync for Alembic)
  - `excel_mappings.py` - Excel/Google Sheets column to database mapping configuration (5 sheets, 100+ column mappings)
- **`app/api/api_v1/`** - API endpoints focused on HTTP concerns:
  - `api.py` - Router aggregator combining all endpoint modules
  - `endpoints/auth.py` - Authentication endpoints (me, verify)
  - `endpoints/dashboard.py` - Dashboard data endpoints (position, indicators, recommendations, chart, news, weather, audio)
  - `endpoints/audio.py` - Audio streaming and metadata endpoints (unauthenticated stream for HTML audio element)
  - `endpoints/commodities.py` - Commodity information (stub/mock data, TODO)
  - `endpoints/historical.py` - Historical data endpoints (stub/mock data, TODO)
- **`app/models/`** - SQLAlchemy database models split by domain:
  - `base.py` - DeclarativeBase class
  - `technicals.py` - OHLCV data with 40+ technical indicators
  - `indicator.py` - Normalized indicators and trading signals
  - `market_research.py` - Market research articles
  - `weather_data.py` - Weather impact data
  - `test_range.py` - Indicator color ranges (RED/ORANGE/GREEN)
- **`app/schemas/`** - Pydantic request/response models:
  - `dashboard.py` - All dashboard response schemas (PositionStatus, IndicatorsGrid, Recommendations, ChartData, News, Weather, Audio)
- **`app/services/`** - Business logic layer (service-oriented architecture):
  - `data_import.py` - Google Sheets to PostgreSQL ETL pipeline
  - `dashboard_service.py` - Pure business logic for dashboard operations
  - `dashboard_transformers.py` - Data transformation between models and API responses
  - `audio_service.py` - Google Drive audio file integration (singleton service)
- **`app/utils/`** - Reusable utility functions:
  - `date_utils.py` - Date parsing, validation, business date conversion (weekend to Friday)

### Frontend (React 19 + TypeScript)

The frontend uses modern React patterns:

- **Auth0 Integration** - `main.tsx` sets up Auth0Provider with localStorage caching and refresh tokens
- **API Layer** - `src/api/` contains:
  - `client.ts` - Axios client with automatic token injection and 401 interceptor (dispatches `auth:token-expired` event)
  - `dashboard.ts` - Dashboard API service functions for all endpoints
- **State Management** - React Query (TanStack Query) with 24-hour stale time for daily trading data
- **Routing** - React Router with `ProtectedRoute` wrapper requiring authentication
  - `/` redirects to `/dashboard`
  - `/login` - Auth0 login page with redirect loop detection
  - `/dashboard` - Main trading dashboard (protected)
  - `/dashboard/historical` - Historical data view (protected)
- **UI Components** - Shadcn/ui (new-york style) with Radix UI primitives in `src/components/ui/`
- **Dashboard Components**:
  - `PositionStatus` - Position badge (OPEN/HEDGE/MONITOR), audio player, YTD performance
  - `IndicatorsGrid` - Grouped gauge indicators (Tendances: Macroeco/MACD/Vol-OI, Volatilité: RSI/%K/ATR)
  - `GaugeIndicator` - SVG semi-circular gauge with color ranges
  - `RecommendationsList` - Scrollable trading recommendations
  - `PriceChart` - Recharts area chart with metric/days selector and zoom controls
  - `NewsCard` - Latest market research display
  - `WeatherUpdateCard` - Weather conditions and market impact
  - `DashboardLayout` - Sidebar navigation, theme toggle, user profile dropdown
  - `DateSelector` - Business day navigation with Ant Design DatePicker (disables weekends/future)
  - `DatePickerWithRange` - Date range picker with two-month calendar view
  - `LoadingSpinner` - Full-screen centered spinner
- **Custom Hooks**:
  - `useAuth.ts` - Auth0 token management wrapper
  - `useDashboard.ts` - React Query hooks for all dashboard endpoints (24h stale time, no auto-refetch)
  - `use-mobile.tsx` - Mobile breakpoint detection
- **Types** - `src/types/dashboard.ts` for all API response type definitions
- **Data** - `src/data/commodities-data.ts` for chart metric options and mock data

### Environment Configuration

Environment variables are organized in two levels:

- **Backend `.env`** - Backend-specific (database, APIs, Google Sheets/Drive, Auth0, AWS)
- **Frontend `.env`** - Frontend-specific (Auth0, redirect URIs, API base URL)

Frontend code uses Auth0 variables (not VITE_ prefixed) exposed via custom Vite `define` configuration in `vite.config.ts`.

### Database Setup

- PostgreSQL 15 runs on custom port 5433 (not default 5432) via Docker
- Redis 7 runs on custom port 6380 (not default 6379) via Docker
- Database URL: `postgresql+asyncpg://postgres:password@localhost:5433/commodities_compass`
- Async SQLAlchemy with asyncpg driver for app, sync engine for Alembic migrations
- 4 migrations exist: initial schema, score field precision update, unused table cleanup, test_range table

### Authentication Flow

1. Frontend uses Auth0 SPA client with React SDK (`cacheLocation: "localstorage"`, refresh tokens enabled)
2. Tokens stored in localStorage (`auth0_token`) and automatically added to API requests via Axios interceptor
3. Backend validates JWT tokens using Auth0's JWKS endpoint (RS256, cached for 6 hours)
4. User claims extracted: sub, email, name, permissions
5. On 401 response: Axios interceptor clears token, dispatches `auth:token-expired` event, App.tsx triggers logout
6. Login page includes redirect loop detection (max 3 redirects in 5-second window)

## Data Pipeline

Data flows from Google Sheets to PostgreSQL via ETL, updated daily by Make.com automations:

1. **Google Sheets ETL** implemented in `app/services/data_import.py` (run with `poetry run import`)
2. **Full refresh strategy**: Each import clears existing table data and re-inserts all rows
3. **5 sheets imported** with column mappings defined in `app/core/excel_mappings.py`:
   - **TECHNICALS** → `technicals` table: OHLCV data with 40+ technical indicators (RSI, MACD, ATR, Bollinger Bands, pivot points, etc.), trading signals (OPEN/HEDGE/MONITOR), updated daily at 8:30 PM
   - **INDICATOR** → `indicator` table: Normalized indicators (0-1 scale), composite scores, macroeconomic analysis (OpenAI-generated), updated daily at 11 PM
   - **BIBLIO_ALL** → `market_research` table: Research articles with OpenAI impact synthesis, updated daily at 10:30 PM
   - **METEO_ALL** → `weather_data` table: Agricultural weather from Ghana & Côte d'Ivoire (10 locations), updated daily at 10:30 PM
   - **TEST RANGE** → `test_range` table: Color zone thresholds (RED/ORANGE/GREEN) for gauge indicators
4. **Data transformations**: `parse_datetime`, `parse_decimal`, `parse_decimal_from_string`, `parse_integer` for handling US number formats, percentages, and formulas

## Scrapers

Three automated scrapers feed columns A–I of the TECHNICALS Google Sheet. Each is a standalone Railway cron service sharing the same `backend/Dockerfile`.

### Architecture

```
Google Sheets TECHNICALS row:
  A: Date | B: Close | C: High | D: Low | E: Volume | F: OI | G: IV | H: Stock US | I: Com NET US
  ──────── barchart-scraper (appends row A-G) ────────  ──ice──  ──cftc──
                                                        (update H) (update I)
```

### Barchart Scraper (`backend/scripts/barchart_scraper/`)

- **Data**: C, H, L, V, OI, IV for London cocoa #7 (ICE Europe, GBP/tonne)
- **Contract selection**: Uses specific contract code (e.g., `CAH26`), never Barchart's `CA*0` alias. Both prices and IV URLs use our roll logic.
- **Contract roll**: Rolls to next contract **15 days before expiry** (last business day of delivery month). Delivery months: H(Mar), K(May), N(Jul), U(Sep), Z(Dec). CA\*0 is NOT used because Barchart rolls it on their own schedule (volume-based), which doesn't match our 15-day rule.
- **Source**: `https://www.barchart.com/futures/quotes/{contract}/overview` (OHLCV+OI) + `/{contract}/volatility-greeks` (IV)
- **Method**: Playwright browser → extracts OHLCV+OI from server-rendered inline JSON raw blocks (max-volume heuristic to pick the correct block among 4+). XHR API response used as backup for C/H/L/V (API omits OI). IV via XHR interception or HTML regex fallback.
- **Volume**: Raw contract count (no conversion)
- **IV conversion**: percentage → decimal (e.g., `55.38` → `0.5538` in Sheets)
- **Cron**: `0 21 * * 1-5` (9 PM UTC weekdays only)
- **CLI**: `python -m scripts.barchart_scraper.main --sheet production [--dry-run] [--verbose] [--headful]`

### ICE Stocks Scraper (`backend/scripts/ice_stocks_scraper/`)

- **Data**: STOCK US (column H) — certified cocoa stocks in ICE US warehouses
- **Source**: `https://www.ice.com/publicdocs/futures_us_reports/cocoa/cocoa_cert_stock_YYYYMMDD.xls`
- **Method**: Pure httpx + pandas (no browser). Downloads public XLS, parses "GRAND TOTAL" row, converts bags → tonnes (`bags × 70 / 1000`).
- **Fallback**: Walks back through business days (up to 60) until a report is found. Handles `a`-suffix variants.
- **Cron**: `10 21 * * 1-5` (9:10 PM UTC weekdays)
- **CLI**: `python -m scripts.ice_stocks_scraper.main --sheet production [--dry-run] [--date YYYY-MM-DD]`

### CFTC Scraper (`backend/scripts/cftc_scraper/`)

- **Data**: COM NET US (column I) — commercial net position from CFTC COT report
- **Source**: `https://www.cftc.gov/dea/futures/ag_lf.htm`
- **Method**: Pure httpx + regex (no browser). Parses "COCOA - ICE FUTURES U.S." section, extracts Producer/Merchant Long − Short.
- **Cron**: `10 21 * * 1-5` (9:10 PM UTC weekdays — idempotent, new data only on Fridays after CFTC publishes ~9:30 PM CET)
- **CLI**: `python -m scripts.cftc_scraper.main --sheet production [--dry-run]`

### Known Issues & Lessons (2026-02-18 debugging sessions)

**Bug 1 — Wrong raw block (old scraper)**: Used `re.search` → picked FIRST of 4+ raw blocks. The first block was often a next-month contract or options data → wrong V and OI. Fix: max-volume heuristic picks the block with highest `volume` (always the main contract).

**Bug 2 — CA\*0 roll mismatch**: Barchart's `CA*0` continuous symbol rolls based on volume shift, not calendar. In Feb 2026, Barchart already rolled CA\*0 to CAK26 (May) while we should track CAH26 (March) until March 16. Fix: both prices and IV URLs now use `get_current_contract_code()` which applies our 15-day-before-expiry roll rule. CA\*0 is never used in URLs.

**Forensic proof of prod data errors**: Prod OI=36,333 and Close=2,438 matched CAH26's data exactly (`previousPrice=2438`, `openInterest=36333` on the CAH26 page). The human who filled prod was reading the wrong contract page (March instead of May). Prod V=3,625 was the correct raw contract count for CAH26.

**Barchart page structure**: Angular SPA. XHR API (`/proxies/core-api/v1/quotes/get`) returns C/H/L/V as formatted strings (commas) but **omits OI**. Server-rendered inline JSON contains all 5 fields with raw numeric values. `networkidle` never fires (analytics polling) — use `wait_until="load"` + fixed 5s wait.

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
  - `GET /dashboard/position-status` - Position (OPEN/HEDGE/MONITOR) and YTD performance
  - `GET /dashboard/indicators-grid` - All indicators with color ranges for gauges
  - `GET /dashboard/recommendations` - Parsed trading recommendations from technicals.score
  - `GET /dashboard/chart-data` - Historical data for charting (1-365 days)
  - `GET /dashboard/news` - Latest market research article
  - `GET /dashboard/weather` - Latest weather update and market impact
  - `GET /dashboard/audio` - Audio file metadata with backend streaming URL
- `/audio/*` - Audio streaming:
  - `GET /audio/stream` - Stream audio from Google Drive (no auth, for HTML audio element)
  - `GET /audio/info` - Audio metadata (requires auth)
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

   # Optional: Separate Google Drive credentials (defaults to Google Sheets credentials)
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

- **Platform**: Railway (primary deployment target)
- **Backend**: Dockerfile-based (`backend/Dockerfile`, Python 3.11-slim), `start.sh` runs Alembic migrations then uvicorn. Health check: `/health` (300s timeout).
- **Frontend**: Dockerfile-based (`frontend/Dockerfile`, Node 18-alpine), pnpm build + serve static. Health check: `/` (300s timeout).
- **Daily Import**: Railway cron job, runs `poetry run import` at 10:15 PM UTC nightly. Full-refresh ETL (Sheets → PostgreSQL).
- **Auto-deploy**: Push to `main` triggers rebuild of all services.

## Development Notes

- Backend uses Poetry scripts: `poetry run dev`, `poetry run lint`, and `poetry run import`
- Frontend environment variables exposed via custom Vite `define` config (no VITE_ prefix needed)
- Database migrations managed via Alembic with 4 existing migrations
- Pre-commit hooks run via Husky (backend: ruff + pyright, frontend: eslint fix)
- Development setup script available at `scripts/setup-dev.sh`
- No test files exist yet - test infrastructure needs to be created
- `commodities` and `historical` API endpoints return mock data (TODO: implement database queries)
- Node.js 18+ and pnpm required (see root `package.json` engines)
- **Always use pnpm** instead of npm for all JavaScript/TypeScript dependency management and script execution

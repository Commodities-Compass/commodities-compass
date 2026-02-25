# Commodities Compass

A Business Intelligence application for commodities trading, providing real-time market insights, technical analysis, and trading signals.

## Architecture

This is a monorepo containing:

- **Backend**: FastAPI application with PostgreSQL database
- **Frontend**: React + TypeScript application with Vite
- **Authentication**: Auth0 integration
- **Data Source**: Google Sheets integration with migration to PostgreSQL

## Quick Start

### Prerequisites

- Node.js 18+ and pnpm 9+
- Python 3.11+
- Poetry (for Python dependency management)
- PostgreSQL 14+
- Auth0 account

### Installation

1. Install all dependencies:

```bash
pnpm run install:all
```

2. Set up environment files:

```bash
# Backend
cp backend/.env.example backend/.env
# Edit backend/.env with your configuration

# Frontend
cp frontend/.env.example frontend/.env
# Edit frontend/.env with your configuration
```

3. Start PostgreSQL and Redis:

```bash
pnpm run db:up
```

4. Run database migrations (once available):

```bash
cd backend && poetry run alembic upgrade head
```

### Development

Start both frontend and backend in development mode:

```bash
pnpm run dev
```

Or run them separately:

```bash
# Backend only (http://localhost:8000)
pnpm run dev:backend

# Frontend only (http://localhost:5173)
pnpm run dev:frontend
```

### Available Scripts

- `pnpm run dev` - Start both frontend and backend in development mode
- `pnpm run db:up` - Start PostgreSQL and Redis containers
- `pnpm run db:down` - Stop database containers
- `pnpm run db:logs` - View database container logs
- `pnpm run lint` - Run linting for both frontend and backend
- `pnpm run format` - Format code for both frontend and backend
- `pnpm run test` - Run tests for both frontend and backend
- `pnpm run build` - Build the frontend for production
- `pnpm run clean` - Remove frontend + backend build artifacts
- `pnpm run clean:all` - Full clean including node_modules
- `pnpm run reinstall` - Clean all + reinstall all dependencies

## Project Structure

```
commodities-compass/
├── backend/                # FastAPI backend with clean architecture
│   ├── app/               # Application code
│   │   ├── api/           # API endpoints (HTTP layer only)
│   │   │   └── api_v1/endpoints/dashboard.py # Streamlined endpoints (390 lines)
│   │   ├── core/          # Core functionality & mappings
│   │   ├── models/        # SQLAlchemy database models
│   │   │   ├── trading.py # Core trading models
│   │   │   ├── indicator.py # Indicator model
│   │   │   └── ... # Other domain models
│   │   ├── services/      # Business logic layer
│   │   │   ├── dashboard_service.py # Dashboard business logic (326 lines)
│   │   │   ├── dashboard_transformers.py # Data transformers (192 lines)
│   │   │   └── data_import.py # Excel ETL service
│   │   ├── schemas/       # Pydantic API schemas
│   │   └── utils/         # Utility functions
│   │       └── date_utils.py # Date utilities (99 lines)
│   ├── tests/             # Backend tests
│   ├── scripts/           # Data import and utility scripts
│   │   ├── barchart_scraper/  # Daily Barchart scraper (Playwright)
│   │   ├── ice_stocks_scraper/ # ICE certified stocks scraper (httpx)
│   │   ├── cftc_scraper/      # Weekly CFTC COT scraper (httpx)
│   │   └── daily_analysis/    # Daily AI analysis pipeline (replaces Make.com)
│   ├── alembic/           # Database migrations
│   └── pyproject.toml     # Python dependencies and config
├── frontend/              # React frontend
│   ├── src/               # Source code
│   │   ├── components/    # Reusable UI components
│   │   ├── pages/         # Page components
│   │   ├── api/           # API client layer
│   │   └── hooks/         # Custom React hooks
│   ├── public/            # Static assets
│   └── package.json       # Frontend dependencies
├── static-react-app/      # Original static prototype (reference)
├── excel-sheet/           # Excel data files
├── scripts/               # Analysis and migration scripts
└── package.json           # Monorepo configuration
```

## Tech Stack

### Backend

- **FastAPI** - Modern Python web framework with clean architecture
- **SQLAlchemy** - Async ORM with custom trading data models
- **PostgreSQL** - Primary database (port 5433) with comprehensive trading schema
- **Auth0** - JWT authentication and authorization
- **Pandas** - Data processing and ETL pipeline
- **Google Sheets API** - Data ingestion (transitioning to PostgreSQL)
- **Alembic** - Database migrations and schema management
- **Service Layer** - Separation of business logic from API concerns

### Frontend

- **React** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool
- **Tailwind CSS** - Styling
- **React Query** - API state management
- **Auth0 React** - Authentication
- **Recharts** - Data visualization

### Observability

- **Sentry** - Error tracking, performance monitoring, cron monitoring (Python + React)
- **Slack** - `#dev-monitoring` channel receives all Sentry alerts

### Development

- **Poetry** - Python dependency management
- **ESLint/Prettier** - Code linting and formatting
- **Pre-commit** - Git hooks for code quality
- **Husky** - Git hooks management

## API Documentation

Once the backend is running, visit:

- Swagger UI: <http://localhost:8000/v1/docs>
- ReDoc: <http://localhost:8000/v1/redoc>

## Authentication Setup

1. Create an Auth0 application and API
2. Configure the environment variables in both backend and frontend `.env` files
3. Set up the appropriate callback URLs in Auth0

## Architecture Highlights

### Clean Architecture Implementation

The backend follows a clean architecture pattern for maintainability:

- **API Layer** (`dashboard.py`): HTTP concerns only - validation, error handling, delegation
- **Service Layer** (`dashboard_service.py`): Pure business logic, database-agnostic
- **Data Layer** (`models/`): SQLAlchemy models for trading data
- **Transformers** (`dashboard_transformers.py`): Data mapping between layers
- **Utilities** (`utils/`): Reusable functions (date handling, formatting)

### Refactoring Results

- Dashboard endpoints reduced from **668 to 390 lines** (42% reduction)
- Business logic extracted to **326-line service module**
- Data transformations isolated in **192-line transformer module**
- Date utilities centralized in **99-line utility module**
- Improved testability and code reusability

## Automated Data Scrapers

Three independent scrapers run on Railway cron jobs to keep market data updated:

### Barchart Scraper
- **Schedule**: Daily at 21:00 UTC
- **Source**: Barchart.com (London cocoa front-month)
- **Method**: Playwright (browser automation)
- **Data**: Close, High, Low, Volume, Open Interest, Implied Volatility
- **Update**: Appends new row to TECHNICALS sheet (columns A-G)
- **Location**: `backend/scripts/barchart_scraper/`

### ICE Stocks Scraper
- **Schedule**: Daily at 21:30 UTC
- **Source**: ICE public cocoa certified stock reports (XLS)
- **Method**: httpx + pandas (no browser)
- **Data**: STOCK US — certified cocoa stocks in ICE US warehouses (bags to tonnes)
- **Update**: Updates column H of last row in TECHNICALS sheet
- **Location**: `backend/scripts/ice_stocks_scraper/`

### CFTC Scraper
- **Schedule**: Daily at 21:30 UTC
- **Source**: CFTC.gov (Agriculture Disaggregated Futures)
- **Method**: httpx + regex (no browser)
- **Data**: COM NET US (Producer/Merchant Long - Short positions)
- **Update**: Updates column I of last row in TECHNICALS sheet
- **Location**: `backend/scripts/cftc_scraper/`

All scrapers:
- Use centralized `config.py` for configuration
- Support `--dry-run` for testing
- Support `--sheet=staging|production` for environment selection
- Log to stdout (Railway captures automatically)
- Monitored by Sentry Crons (missed run detection)
- Deploy independently on Railway

## Daily Analysis Pipeline

The core AI analysis engine, replacing the Make.com DAILY BOT AI scenario. Reads market data, calls OpenAI twice, writes trading decisions back to Google Sheets.

- **Schedule**: `00 23 * * 1-5` (11:00 PM UTC, weekdays)
- **Location**: `backend/scripts/daily_analysis/`
- **CLI**: `poetry run daily-analysis --sheet production [--dry-run] [--date YYYY-MM-DD] [--force]`

### Pipeline Steps

1. **Read** TECHNICALS (last 2 rows, 42 variables), BIBLIO_ALL (macronews), METEO_ALL (weather)
2. **LLM Call #1** (gpt-4-turbo, T=1.0) — Macro/weather analysis → MACROECO_BONUS + ECO
3. **Write to INDICATOR** — Copy formulas A-O (CopyPasteRequest), set date, write P/S/T, write Q/R HISTORIQUE refs
4. **Read back** FINAL INDICATOR + CONCLUSION (retry with exponential backoff)
5. **LLM Call #2** (gpt-4-turbo, T=0.7) — Trading decision → DECISION/CONFIANCE/DIRECTION/CONCLUSION
6. **Write to TECHNICALS** — Update AO-AR on existing row

### Key Features

- **Idempotency**: Checks for existing data before writing, `--force` to overwrite
- **Backfill**: `--date YYYY-MM-DD` to run for a past date
- **HISTORIQUE row-shift**: Automated 2-slot circular buffer (freeze/demote/new)
- **Formula management**: Copies A-O formulas via Google Sheets batchUpdate API (CopyPasteRequest)
- **Multi-provider LLM**: `--llm-provider openai|anthropic` with configurable model
- **Structured output**: Pydantic models replace fragile regex parsing

## Monitoring & Observability

All services are monitored via [Sentry](https://commodities-compass.sentry.io/) with alerts routed to `#dev-monitoring` on Slack.

### What's Tracked

| Service | What Sentry captures |
|---------|---------------------|
| **FastAPI backend** | Unhandled exceptions, 500 errors, slow queries, request traces, user context |
| **React frontend** | JS errors, render crashes (ErrorBoundary), API errors, page load performance, session replay on error |
| **Daily ETL import** | Per-sheet import success/failure, row counts, cron check-ins |
| **Barchart scraper** | Scrape results (contract, price, volume, OI, IV), cron check-ins |
| **ICE Stocks scraper** | Stock data (tonnes, bags), cron check-ins |
| **CFTC scraper** | Commercial net position, cron check-ins |
| **Daily analysis** | LLM token usage, sheet writes (INDICATOR + TECHNICALS), pipeline timing, cron check-ins |

### Service Tags

Every event is tagged with `service` for filtering in the Sentry dashboard:

```
frontend | fastapi | daily-import | barchart-scraper | ice-stocks-scraper | cftc-scraper | daily-analysis
```

### Environment Variables (Production)

**Backend + scrapers + daily import + daily analysis (6 Railway services):**

| Variable | Required | Notes |
|----------|----------|-------|
| `SENTRY_DSN` | Yes | Single DSN shared across all Python services |
| `ENVIRONMENT` | No | Defaults to `production` |

**Frontend (1 Railway service):**

| Variable | Required | Notes |
|----------|----------|-------|
| `SENTRY_DSN` | Yes | Same DSN as backend (platform auto-detected by SDK) |
| `SENTRY_AUTH_TOKEN` | Yes | Org token with `org:ci` scope — enables sourcemap upload at build time |

### Key Files

| File | Purpose |
|------|---------|
| `backend/app/core/sentry.py` | Shared `init_sentry()` used by all Python services |
| `frontend/src/sentry.ts` | Frontend Sentry init (production-only) |
| `frontend/src/components/ErrorFallback.tsx` | Crash fallback UI for Sentry ErrorBoundary |

## Contributing

1. Install pre-commit hooks: `cd backend && poetry run pre-commit install`
2. Make sure all tests pass: `pnpm run test`
3. Ensure code is properly formatted: `pnpm run format`
4. Run linting: `pnpm run lint`
5. Follow clean architecture principles when adding new features

## License

Private project - All rights reserved.

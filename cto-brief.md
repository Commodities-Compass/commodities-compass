# Commodities Compass - CTO Technical Brief

## What is this product?

A **Business Intelligence platform for cocoa commodities trading** that provides real-time market insights, technical analysis (40+ indicators), and daily trading signals. The system ingests data from Google Sheets (updated daily via Make.com automation), stores it in PostgreSQL, and serves it through a dashboard with gauges, charts, and recommendations.

---

## Tech Stack Overview

| Layer | Technology | Version |
|-------|-----------|---------|
| **Frontend** | React + TypeScript | React 19, TS 5.7 |
| **Build Tool** | Vite | 6.2 |
| **UI Framework** | Shadcn/ui + Tailwind CSS + Radix UI | Latest |
| **State Management** | TanStack React Query | 5.x |
| **Charts** | Recharts + custom SVG gauges | 2.15 |
| **Backend** | FastAPI (Python) | 0.110 |
| **ORM** | SQLAlchemy (async) | 2.0 |
| **Database** | PostgreSQL (port 5433) | 15 |
| **Cache/Queue** | Redis (port 6380) | 7 |
| **Auth** | Auth0 (JWT/RS256) | SPA + API |
| **Package Mgmt** | Poetry (backend), npm workspaces (frontend) | - |
| **Deployment** | Railway (Docker) | - |
| **CI** | GitHub Actions (frontend build only) | - |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  React 19 SPA (Vite)                                        │
│  Auth0 SDK → localStorage token → Axios interceptor         │
│  TanStack Query (24h stale) → Dashboard Components          │
├─────────────────────────────────────────────────────────────┤
│  FastAPI REST API (/v1/dashboard/*)                          │
│  Auth0 JWT validation (JWKS cached 6h)                      │
│  Endpoints → Services → Transformers → Pydantic schemas     │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL (asyncpg) │ Redis │ Google Sheets │ Google Drive │
└─────────────────────────────────────────────────────────────┘
```

**Key design pattern**: Clean layered architecture with strict separation:
- **Endpoints** handle HTTP only
- **Services** contain pure business logic (no FastAPI deps)
- **Transformers** convert DB models to API response DTOs

---

## Project Structure

```
commodities-compass/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI entry point, CORS, middleware
│   │   ├── api/api_v1/endpoints/      # REST endpoints (dashboard, auth, audio)
│   │   ├── core/                      # Config, auth, database, excel mappings
│   │   ├── models/                    # SQLAlchemy models (5 tables)
│   │   ├── schemas/                   # Pydantic request/response DTOs
│   │   ├── services/                  # Business logic + ETL + audio
│   │   └── utils/                     # Date utilities
│   ├── alembic/                       # Database migrations (4 versions)
│   ├── pyproject.toml                 # Poetry dependencies
│   ├── Dockerfile                     # Python 3.11-slim + Poetry
│   └── start.sh                       # Runs migrations then starts server
├── frontend/
│   ├── src/
│   │   ├── main.tsx                   # Auth0Provider + QueryClient setup
│   │   ├── App.tsx                    # Router + ProtectedRoute
│   │   ├── api/                       # Axios client + API methods
│   │   ├── hooks/                     # useDashboard, useAuth
│   │   ├── components/                # Dashboard components + Shadcn/ui
│   │   ├── pages/                     # DashboardPage, LoginPage
│   │   └── types/                     # TypeScript interfaces
│   ├── vite.config.ts                 # Path aliases, env var injection
│   ├── Dockerfile                     # Multi-stage Node 18 build
│   └── railway.toml                   # Railway deployment config
├── docker-compose.yml                 # PostgreSQL (5433) + Redis (6380)
├── package.json                       # Monorepo scripts (concurrently)
├── .github/workflows/                 # Frontend build CI
└── .husky/                            # Pre-commit hooks
```

---

## Data Pipeline

Data flows daily via **Make.com automation** from Google Sheets to PostgreSQL:

| Time | Sheet | Model | Content |
|------|-------|-------|---------|
| 8:30 PM | TECHNICALS | Technicals | 40+ OHLCV/indicators per day |
| 10:30 PM | BIBLIO_ALL | MarketResearch | Research articles with OpenAI impact synthesis |
| 10:30 PM | METEO_ALL | WeatherData | Weather from Ghana/Cote d'Ivoire (10 locations) |
| 11:00 PM | INDICATOR | Indicator | Normalized scores + OpenAI macro analysis |

The ETL service (`backend/app/services/data_import.py`) does a **full table refresh** on each import (truncate + insert). Column mappings are defined in `backend/app/core/excel_mappings.py`.

---

## API Endpoints

### Active Dashboard Endpoints (all require Auth0 JWT)

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/dashboard/position-status` | Trading position (OPEN/HEDGE/MONITOR) + YTD % |
| `GET /v1/dashboard/indicators-grid` | 6 gauge indicators with color zones |
| `GET /v1/dashboard/recommendations` | Parsed trading recommendations |
| `GET /v1/dashboard/chart-data` | Historical OHLCV + indicators (1-365 days) |
| `GET /v1/dashboard/news` | Latest market research |
| `GET /v1/dashboard/weather` | Agricultural weather impact |
| `GET /v1/dashboard/audio` | Daily audio bulletin from Google Drive |

### Supporting Endpoints

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `GET /v1/audio/stream` | No | Proxy streams audio from Google Drive (for HTML5 audio) |
| `GET /v1/audio/info` | No | Audio file metadata |
| `GET /v1/auth/me` | Yes | Current user info from token |
| `GET /v1/auth/verify` | Yes | Token validation |
| `GET /health` | No | Health check |
| `GET /v1/commodities/*` | Yes | **Mock data** (not implemented) |
| `GET /v1/historical/*` | Yes | **Mock data** (not implemented) |

---

## Database Models (5 tables)

1. **Technicals** (245 lines) - Raw OHLCV + 40+ technical indicators (RSI, MACD, ATR, Bollinger, pivot points, stochastic, etc.). Indexed on `timestamp` and `commodity_symbol`.
2. **Indicator** (169 lines) - Normalized scores (0-1 scale), composite scores, OpenAI macro analysis. Stores both current and previous period values for trend analysis.
3. **MarketResearch** (61 lines) - Research articles with author, summary, keywords, and OpenAI-generated impact synthesis.
4. **WeatherData** (55 lines) - Agricultural weather from cocoa-producing regions with market impact assessment.
5. **TestRange** (83 lines) - Color zone thresholds (RED/ORANGE/GREEN) for gauge visualization. Unique constraint on (indicator, range_low, range_high).

Migrations managed via **Alembic** (4 versions applied). Models are in `backend/app/models/`.

---

## Authentication & Security

### How it works

1. Frontend uses **Auth0 SPA SDK** with RS256 JWT tokens
2. Tokens stored in `localStorage`, auto-injected via Axios request interceptor
3. Backend validates JWT using **JWKS** (cached 6 hours) from Auth0
4. User claims extracted: `sub`, `email`, `name`, `permissions`
5. `get_current_user` FastAPI dependency protects all dashboard endpoints

### Auth resilience features

- Redirect loop detection (3+ redirects in 5 seconds triggers forced logout)
- 401 response interceptor dispatches `auth:token-expired` custom event
- Token refresh attempted once per auth state change via `useRef` flag
- Refresh tokens enabled for seamless session continuity

### Security gaps to address

| Issue | Severity | Details |
|-------|----------|---------|
| No RBAC enforcement | High | Permissions extracted from tokens but never checked on endpoints |
| No rate limiting | High | No protection against API abuse |
| Auth header in logs | Medium | Request logging middleware logs full headers including Bearer token |
| Broad CORS headers | Medium | `allow_headers: "*"` is overly permissive |
| No HTTPS enforcement | Medium | Not configured for production |
| Unauthenticated audio | Medium | `/v1/audio/stream` has no auth (intentional for HTML5 audio but exposes files) |
| No security headers | Low | Missing HSTS, X-Frame-Options, CSP |

---

## Frontend Dashboard

### Main Components

| Component | Purpose |
|-----------|---------|
| **PositionStatus** | Position of the day badge (OPEN/HEDGE/MONITOR) + YTD % + audio player |
| **IndicatorsGrid** | 6 SVG gauges in 2 categories: Tendances (MACROECO, MACD, VOL/OI) and Volatilite (RSI, %K, ATR) |
| **PriceChart** | Recharts area chart with metric selection (close, volume, RSI, etc.) and time period selector |
| **RecommendationsList** | Scrollable list of trading recommendations parsed from technicals score field |
| **NewsCard** | Latest market research article (title from impact_synthesis, content from summary) |
| **WeatherUpdateCard** | Weather conditions and market impact from cocoa-producing regions |
| **DateSelector** | Ant Design date picker with business day navigation (skips weekends) |
| **DashboardLayout** | Collapsible sidebar, dark mode toggle, user dropdown with logout |

### State management

- **Server state**: TanStack React Query with 24-hour stale time, no auto-refetch
- **Client state**: Local `useState` only (date selection, metric selection, theme)
- **No global state**: No Redux/Zustand/Context - each component manages its own state

---

## DevOps & Infrastructure

### Local development

```bash
npm run install:all          # Install everything (root + backend + frontend)
npm run db:up                # Start PostgreSQL (5433) + Redis (6380) via Docker
npm run dev                  # Run both backend (8000) + frontend (5173) concurrently
```

### Docker services

- **PostgreSQL 15** on port 5433 (custom, avoids conflicts with local installs)
- **Redis 7** on port 6380 (custom, same reason)
- Both have health checks configured
- Persistent volume for PostgreSQL data

### Deployment (Railway)

- Separate Dockerfiles for backend (Python 3.11-slim) and frontend (Node 18-alpine, multi-stage)
- Backend `start.sh` runs Alembic migrations before starting uvicorn
- Frontend built with env vars injected as build args, served via `serve` package
- Health checks: backend `/health`, frontend `/`
- Restart policy: ON_FAILURE, max 10 retries
- Nixpacks configs available as fallback build method

### CI/CD

- **GitHub Actions**: Frontend build workflow only (on push/PR to main)
- **Pre-commit hooks** (Husky): Ruff lint + format, Pyright type check (backend), ESLint auto-fix (frontend)
- **No backend CI pipeline exists**

### Environment variables

Three levels of `.env` files (all gitignored):
- **Root**: Shared Auth0 config
- **Backend**: Database URLs, Google credentials, API keys
- **Frontend**: Redirect URI, API base URL

Required secrets: Auth0 domain/client/audience, database URL, Google Sheets credentials JSON, Google Drive folder ID.

---

## Commodities Domain Knowledge

### Currently tracked: Cocoa (CC) on ICE exchange

The system collects and analyzes:
- **OHLCV data**: Daily close, high, low, volume, open interest
- **40+ technical indicators**: RSI (14d), MACD (12/26/9), Stochastic %K/%D, ATR, Bollinger Bands, pivot points, EMAs, etc.
- **US stock levels**: ICE-regulated warehouse stocks
- **COT data**: Commercial net positions (com_net_us) from CFTC reports
- **Macroeconomic analysis**: OpenAI-generated scores and text analysis

### Scoring system

```
Raw indicators (-6 to +6) → Normalized (0-1) → Composite score → Macro adjustment → Final indicator
```

### Trading signals

- **Position**: OPEN (initiate trade), HEDGE (protect position), MONITOR (watch only)
- **Direction**: BULLISH or BEARISH
- **Confidence**: 0-100%
- **YTD Performance**: Mean of daily conclusion scores, displayed as percentage

---

## Known Technical Debt

| Area | Issue | Impact |
|------|-------|--------|
| **Testing** | No test suite (empty `tests/` dir, frontend reports "No tests yet") | High - no regression safety |
| **Backend CI** | No automated pipeline for backend linting/testing | High - manual quality checks only |
| **Mock endpoints** | `/v1/commodities/*` and `/v1/historical/*` return hardcoded data | Medium - incomplete API |
| **Unused dependencies** | Frontend has D3, Three.js, Highcharts, Plotly, Formik, Yup, Zod, ethers, Leaflet, Mapbox all installed but unused | Medium - bloated bundle |
| **ETL strategy** | Full table truncate + insert on each import (no incremental) | Medium - data loss risk during import |
| **Logging** | Basic print-style logging, no structured JSON logs | Medium - poor observability |
| **Error monitoring** | No Sentry or equivalent | Medium - blind to production errors |
| **Caching** | Only JWKS cached; no query or response caching | Low - unnecessary DB load |
| **Legacy code** | Old login page, commented-out historical route still in codebase | Low - code clutter |
| **Transformer mismatch** | `create_indicator_for_gauge()` references non-existent Technicals fields | Low - function appears unused |

---

## Recommended Priorities

1. **Add test suites** - pytest (backend) + Vitest (frontend) with CI integration
2. **Set up backend CI/CD** - GitHub Actions for linting, type checking, and tests
3. **Implement rate limiting** - FastAPI-SlowAPI or similar
4. **Enable RBAC enforcement** - Check permissions on endpoints, not just extract them
5. **Add error monitoring** - Sentry or equivalent for production
6. **Clean up frontend deps** - Remove unused libraries to reduce bundle size
7. **Sanitize request logging** - Strip auth headers before logging
8. **Add security headers** - HSTS, X-Frame-Options, CSP, X-Content-Type-Options
9. **Implement incremental ETL** - Upsert instead of truncate + insert
10. **Add structured logging** - JSON format for log aggregation in production

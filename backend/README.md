# Commodities Compass Backend

FastAPI backend for the Commodities Compass trading analysis platform.

## Setup

### Prerequisites

- Python 3.11+
- Poetry (for dependency management)
- Docker (for PostgreSQL)
- Auth0 account for authentication

### Installation

1. Install Poetry if you haven't already:

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

2. Install dependencies:

```bash
poetry install
```

3. Activate the virtual environment:

```bash
poetry shell
```

4. Set up environment variables:

```bash
cp .env.example .env
# Edit .env with your configuration
```

5. Start PostgreSQL:

```bash
# From project root
pnpm run db:up
```

6. Run database migrations:

```bash
poetry run alembic upgrade head
```

### Auth0 Setup

1. Create an Auth0 application (Single Page Application)
2. Create an API in Auth0
3. Update `.env` with:
   - AUTH0_DOMAIN
   - AUTH0_API_AUDIENCE
   - AUTH0_ISSUER

### Running the Application

Development mode:

```bash
poetry run dev
```

Production mode:

```bash
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### API Documentation

Once running, visit:

- Swagger UI: <http://localhost:8000/v1/docs>
- ReDoc: <http://localhost:8000/v1/redoc>

## Project Structure

```
backend/
├── app/
│   ├── api/           # API endpoints (HTTP layer only)
│   │   └── api_v1/endpoints/
│   ├── core/          # Core functionality (auth, config, db, sentry, rate_limit)
│   ├── engine/        # Indicator computation engine
│   │   ├── indicators/    # 14 indicator classes across 8 modules (pivots, EMA, MACD, RSI, etc.)
│   │   ├── types.py       # AlgorithmConfig (frozen), column constants
│   │   ├── registry.py    # Indicator registry with topological sort
│   │   ├── smoothing.py   # 5-day SMA scoring layer
│   │   ├── normalization.py # Rolling 252-day z-score normalization
│   │   ├── pipeline.py    # Orchestrator: raw → derived → scores → normalized → signals
│   │   ├── composite.py   # Power formula composite scoring
│   │   ├── db_writer.py   # Upsert results to pl_* tables
│   │   └── runner.py      # CLI: poetry run compute-indicators
│   ├── models/        # SQLAlchemy models (legacy + MVP)
│   │   ├── base.py           # DeclarativeBase class
│   │   ├── technicals.py     # Legacy: OHLCV + 40+ indicators (unused, pending drop)
│   │   ├── indicator.py      # Legacy: normalized indicators (unused, pending drop)
│   │   ├── market_research.py # Legacy: market research articles
│   │   ├── weather_data.py   # Legacy: weather impact data
│   │   ├── test_range.py     # Gauge color ranges (RED/ORANGE/GREEN)
│   │   ├── reference.py      # MVP: ref_commodity, ref_exchange, ref_contract, ref_trading_calendar
│   │   ├── pipeline.py       # MVP: pl_contract_data_daily, pl_derived_indicators, pl_indicator_daily, pl_algorithm_*, pl_fundamental_article, pl_weather_observation, pl_seasonal_score, pl_article_segment
│   │   ├── signal.py         # MVP: pl_signal_component
│   │   └── audit.py          # Audit: aud_pipeline_run, aud_llm_call, aud_data_quality_check
│   ├── schemas/       # Pydantic schemas (dashboard.py)
│   ├── services/      # Business logic layer
│   │   ├── dashboard_service.py       # Dashboard business logic
│   │   ├── dashboard_transformers.py  # Data transformation
│   │   ├── audio_service.py           # Google Drive audio integration
│   │   └── weather_service.py         # Weather data service
│   └── utils/         # Utilities
│       ├── date_utils.py          # Date parsing, validation, business date conversion
│       ├── contract_resolver.py   # Active contract and algorithm version resolution
│       ├── converters.py          # Data format converters
│       └── trading_calendar.py    # Trading calendar utilities
├── scripts/           # Scrapers, AI agents, data migration
│   ├── barchart_scraper/    # OHLCV + IV scraper (Playwright)
│   ├── ice_stocks_scraper/  # ICE warehouse stocks (httpx)
│   ├── cftc_scraper/        # CFTC COT positions (httpx)
│   ├── press_review_agent/  # LLM press review (OpenAI/Claude/Gemini)
│   ├── meteo_agent/         # Weather analysis (OpenAI)
│   ├── daily_analysis/      # Trading decision pipeline (OpenAI)
│   ├── compass_brief/       # Daily brief generator for NotebookLM
│   ├── seed_gcp.py          # Clean data migration to GCP
│   ├── seed_trading_calendar.py  # Trading calendar seeder
│   ├── seed_historical_csv.py   # Historical CSV import
│   ├── roll_contract.py     # Contract roll CLI
│   └── sync_from_gcp.py     # Sync GCP tables to local
├── tests/             # Test files (198 tests)
└── alembic/           # Database migrations (20 migrations)
```

## Testing

Run tests:

```bash
poetry run pytest
```

Engine tests only:

```bash
poetry run pytest tests/engine/ -v
```

With coverage:

```bash
poetry run pytest --cov=app tests/
```

## Indicator Engine

The indicator computation engine (`app/engine/`) replaces the Google Sheets formula engine (21,468 formulas). See `app/engine/README.md` for full documentation.

```bash
# Dry run (compute + print, no DB write)
poetry run compute-indicators --all-contracts --dry-run

# Incremental run (compute + write only new rows, default)
poetry run compute-indicators --all-contracts

# Full recompute (upsert all rows — for version switches, backfills)
poetry run compute-indicators --all-contracts --full

# Specific algorithm version
poetry run compute-indicators --all-contracts --algorithm legacy --algorithm-version 1.0.1

# Single contract
poetry run compute-indicators --contract CAN26
```

## Code Quality

Run linting and pre-commit hooks:

```bash
poetry run lint
```

Formatting is handled automatically by Ruff via pre-commit hooks (`poetry run lint`).

## Architecture

The backend follows a clean architecture pattern with separation of concerns:

### Service Layer
- **`dashboard_service.py`** — Dashboard business logic (reads from pl_* tables)
- **`dashboard_transformers.py`** — Data transformation between models and API responses
- **`weather_service.py`** — Weather data service

### Indicator Engine (`app/engine/`)
- **14 technical indicators** with dependency-based topological sort
- **Rolling 252-day z-score normalization** (fixes Sheets' look-ahead bias)
- **Power formula** composite scoring with configurable params from DB
- **Signal decomposition** — per-indicator contributions stored in `pl_signal_component`

### API Layer
- **`dashboard.py`** — HTTP concerns only (validation, error handling, delegation to services)
- No business logic — delegates to service layer

### Data Models

**Legacy (unused, pending drop):**
- **`Technicals`** — OHLCV data with 40+ technical indicators
- **`Indicator`** — Normalized indicators and trading signals
- **`MarketResearch`** / **`WeatherData`** — Market news and weather

**MVP (GCP, written by scrapers + engine):**
- **`PlContractDataDaily`** — Raw OHLCV keyed on `(date, contract_id)`
- **`PlDerivedIndicators`** — 27 computed indicator columns
- **`PlIndicatorDaily`** — Scores, z-scores, composite, decision keyed on `(date, contract_id, algorithm_version_id)`
- **`PlSignalComponent`** — Per-indicator contribution decomposition
- **`PlAlgorithmVersion`** / **`PlAlgorithmConfig`** — Config as data, not code
- **`PlFundamentalArticle`** — Press review articles (multi-provider, `is_active` flag)
- **`PlWeatherObservation`** — Weather data per location
- **`PlSeasonalScore`** — Seasonal scoring data
- **`PlArticleSegment`** — Article section decomposition
- **`RefContract`** / **`RefCommodity`** / **`RefExchange`** / **`RefTradingCalendar`** — Reference data

**Audit:**
- **`AudPipelineRun`** / **`AudLlmCall`** / **`AudDataQualityCheck`** — Observability and lineage tracking

# Commodities Compass Backend

FastAPI backend for the Commodities Compass trading analysis platform.

## Setup

### Prerequisites

- Python 3.11+
- Poetry (for dependency management)
- Docker (for PostgreSQL and Redis)
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

5. Start PostgreSQL and Redis:

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
│   ├── core/          # Core functionality (auth, config, db, sentry, excel_mappings)
│   ├── engine/        # Indicator computation engine (Phase 3.1)
│   │   ├── indicators/  # 14 technical indicators (pivots, EMA, MACD, RSI, etc.)
│   │   ├── pipeline.py  # Orchestrator: raw → derived → scores → normalized → signals
│   │   ├── composite.py # NEW CHAMPION power formula
│   │   ├── db_writer.py # Upsert results to pl_* tables
│   │   └── runner.py    # CLI: poetry run compute-indicators
│   ├── models/        # SQLAlchemy models (legacy + MVP)
│   │   ├── technicals.py     # Legacy: OHLCV + 40+ indicators (Railway)
│   │   ├── indicator.py      # Legacy: normalized indicators (Railway)
│   │   ├── market_research.py # Legacy: market research articles
│   │   ├── weather_data.py   # Legacy: weather impact data
│   │   ├── test_range.py     # Gauge color ranges (RED/ORANGE/GREEN)
│   │   ├── reference.py      # MVP: ref_commodity, ref_exchange, ref_contract, ref_trading_calendar
│   │   ├── pipeline.py       # MVP: pl_contract_data_daily, pl_derived_indicators, pl_indicator_daily, pl_algorithm_*
│   │   └── signal.py         # MVP: pl_signal_component
│   ├── schemas/       # Pydantic schemas
│   ├── services/      # Business logic layer
│   │   ├── dashboard_service.py       # Dashboard business logic
│   │   ├── dashboard_transformers.py  # Data transformation
│   │   ├── audio_service.py           # Google Drive audio integration
│   │   └── data_import.py            # Google Sheets → PostgreSQL ETL
│   └── utils/         # Utilities (date_utils.py)
├── scripts/           # Scrapers, AI agents, data migration
│   ├── barchart_scraper/    # OHLCV + IV scraper (Playwright)
│   ├── ice_stocks_scraper/  # ICE warehouse stocks (httpx)
│   ├── cftc_scraper/        # CFTC COT positions (httpx)
│   ├── press_review_agent/  # LLM press review (Claude/OpenAI/Gemini)
│   ├── meteo_agent/         # Weather analysis (OpenAI)
│   ├── daily_analysis/      # Trading decision pipeline (OpenAI)
│   ├── compass_brief/       # Daily brief generator for NotebookLM
│   └── seed_gcp.py          # Clean data migration to GCP
├── tests/             # Test files (75+ engine tests)
└── alembic/           # Database migrations (6 migrations)
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

# Full run (compute + write to GCP DB)
poetry run compute-indicators --all-contracts

# Single contract
poetry run compute-indicators --contract CAK26
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
- **`dashboard_service.py`** — Dashboard business logic (reads from legacy tables)
- **`dashboard_transformers.py`** — Data transformation between models and API responses
- **`data_import.py`** — Google Sheets → PostgreSQL ETL (legacy pipeline)

### Indicator Engine (`app/engine/`)
- **14 technical indicators** with dependency-based topological sort
- **Rolling 252-day z-score normalization** (fixes Sheets' look-ahead bias)
- **NEW CHAMPION power formula** composite scoring with configurable params from DB
- **Signal decomposition** — per-indicator contributions stored in `pl_signal_component`

### API Layer
- **`dashboard.py`** — HTTP concerns only (validation, error handling, delegation to services)
- No business logic — delegates to service layer

### Data Models

**Legacy (Railway, read by dashboard API — dies in Phase 5):**
- **`Technicals`** — OHLCV data with 40+ technical indicators
- **`Indicator`** — Normalized indicators and trading signals
- **`MarketResearch`** / **`WeatherData`** — Market news and weather

**MVP (GCP, written by scrapers + engine):**
- **`PlContractDataDaily`** — Raw OHLCV keyed on `(date, contract_id)`
- **`PlDerivedIndicators`** — 27 computed indicator columns
- **`PlIndicatorDaily`** — Scores, z-scores, composite, decision keyed on `(date, contract_id, algorithm_version_id)`
- **`PlSignalComponent`** — Per-indicator contribution decomposition
- **`PlAlgorithmVersion`** / **`PlAlgorithmConfig`** — Config as data, not code
- **`RefContract`** / **`RefCommodity`** / **`RefExchange`** — Reference data

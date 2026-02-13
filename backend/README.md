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

6. Run database migrations (once we create them):

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
│   ├── api/           # API endpoints (streamlined, HTTP layer only)
│   │   └── api_v1/endpoints/dashboard.py # Dashboard endpoints (390 lines)
│   ├── core/          # Core functionality (auth, config, db, excel_mappings)
│   ├── models/        # SQLAlchemy models
│   │   ├── trading.py # Trading data models (Technicals, Indicator, etc.)
│   │   ├── indicator.py # Indicator model
│   │   ├── test_range.py # Test range model
│   │   ├── market_research.py # Market research model
│   │   └── weather_data.py # Weather data model
│   ├── schemas/       # Pydantic schemas
│   │   └── dashboard.py # Dashboard API schemas
│   ├── services/      # Business logic layer
│   │   ├── dashboard_service.py # Dashboard business logic (326 lines)
│   │   ├── dashboard_transformers.py # Data transformation (192 lines)
│   │   └── data_import.py # Excel to PostgreSQL ETL service
│   └── utils/         # Utilities
│       └── date_utils.py # Date utility functions (99 lines)
├── scripts/           # Data import and maintenance scripts
├── tests/             # Test files
└── alembic/           # Database migrations
```

## Testing

Run tests:

```bash
poetry run pytest
```

With coverage:

```bash
poetry run pytest --cov=app tests/
```

## Code Quality

Run linting and pre-commit hooks:

```bash
poetry run lint
```

Formatting is handled automatically by Ruff via pre-commit hooks (`poetry run lint`).

## Architecture

The backend follows a clean architecture pattern with clear separation of concerns:

### Service Layer
- **`dashboard_service.py`** - Pure business logic functions for dashboard operations
- **`dashboard_transformers.py`** - Data transformation between database models and API responses
- **`date_utils.py`** - Reusable date utilities (business date conversion, formatting)

### API Layer
- **`dashboard.py`** - HTTP concerns only (validation, error handling, delegation to services)
- Reduced from 668 to 390 lines through refactoring
- No business logic - delegates to service layer

### Data Models
- **`Technicals`** - OHLCV data with 40+ technical indicators
- **`Indicator`** - Normalized indicators and trading signals
- **`TestRange`** - Color ranges for gauge indicators
- **`MarketResearch`** - Market news and analysis
- **`WeatherData`** - Agricultural weather impact data

This architecture ensures:
- Better testability (business logic isolated from FastAPI dependencies)
- Code reusability across endpoints
- Clear responsibility boundaries
- Easier maintenance and debugging

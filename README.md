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
│   │   └── cftc_scraper/      # Daily CFTC scraper (httpx)
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

Two independent scrapers run on Railway cron jobs to keep market data updated:

### Barchart Scraper
- **Schedule**: Daily at 19:00 UTC (8:00 PM CET)
- **Source**: Barchart.com (London cocoa front-month)
- **Method**: Playwright (browser automation)
- **Data**: Close, High, Low, Volume, Open Interest, Implied Volatility
- **Update**: Appends new row to TECHNICALS sheet
- **Location**: `backend/scripts/barchart_scraper/`

### CFTC Scraper
- **Schedule**: Daily at 19:00 UTC (8:00 PM CET)
- **Source**: CFTC.gov (Agriculture Disaggregated Futures)
- **Method**: httpx (HTTP requests + regex parsing)
- **Data**: COM NET US (Producer/Merchant Long - Short positions)
- **Update**: Updates column I of last row in TECHNICALS sheet
- **Location**: `backend/scripts/cftc_scraper/`

Both scrapers:
- Use centralized `config.py` for configuration
- Support `--dry-run` for testing
- Support `--sheet=staging|production` for environment selection
- Log to console and file
- Deploy independently on Railway

## Contributing

1. Install pre-commit hooks: `cd backend && poetry run pre-commit install`
2. Make sure all tests pass: `pnpm run test`
3. Ensure code is properly formatted: `pnpm run format`
4. Run linting: `pnpm run lint`
5. Follow clean architecture principles when adding new features

## License

Private project - All rights reserved.

# Commodities Compass Frontend

React + TypeScript frontend for the Commodities Compass BI application, providing real-time market insights and trading signals for commodities trading.

## Features

- **Real-time Dashboard** - Live commodity prices, technical indicators, and trading signals
- **Historical Analysis** - Interactive charts and historical data visualization
- **Technical Indicators** - RSI, MACD, ATR, Bollinger Bands, and 40+ indicators
- **Market Research** - Aggregated news and market impact analysis
- **Weather Data** - Agricultural weather insights affecting commodity prices
- **Authentication** - Secure Auth0 integration with JWT tokens

## Tech Stack

- **React 19** - UI framework
- **TypeScript** - Type safety
- **Vite** - Fast build tool and dev server
- **Tailwind CSS** - Utility-first styling
- **shadcn/ui** - Modern React components
- **TanStack Query** - Server state management
- **Auth0 React** - Authentication
- **Recharts** - Data visualization
- **Axios** - HTTP client

## Project Structure

```
frontend/
├── src/
│   ├── api/               # API client and endpoints
│   ├── components/        # Shared components
│   │   └── ui/           # shadcn/ui components
│   ├── contexts/         # React contexts
│   ├── hooks/            # Custom React hooks
│   ├── pages/            # Page components
│   ├── polymet/          # Legacy components (being migrated)
│   │   ├── components/   # Trading-specific components
│   │   └── data/        # Mock data for development
│   ├── types/            # TypeScript types
│   └── utils/            # Utility functions
├── public/               # Static assets
└── package.json         # Dependencies and scripts
```

## Getting Started

### Prerequisites

- Node.js 18+
- pnpm 9+
- Auth0 account configured

### Installation

1. Install dependencies:

```bash
pnpm install
```

2. Set up environment variables:

```bash
# Copy example env file (if exists) or create .env
cp .env.example .env

# Configure the following variables:
# API_BASE_URL=http://localhost:8000/v1
# (Auth0 variables are inherited from root .env)
```

### Development

```bash
# Start development server (http://localhost:5173)
pnpm run dev

# Run type checking
pnpm run type-check

# Run linting
pnpm run lint

# Format code
pnpm run format
```

### Building

```bash
# Build for production
pnpm run build

# Preview production build
pnpm run preview
```

## Key Components

### Dashboard Components

- **IndicatorsGrid** - Displays technical indicators with gauge visualizations
- **PriceChart** - Interactive price charts with multiple metrics
- **PositionStatus** - Current trading position and performance
- **RecommendationsList** - AI-generated trading recommendations
- **NewsCard** - Latest market news and analysis
- **WeatherUpdateCard** - Weather data affecting commodities

### Authentication

The app uses Auth0 for authentication with:

- Automatic token management
- Protected routes requiring login
- Token injection in API requests
- Silent token refresh

### API Integration

- Axios client with interceptors for auth
- Automatic token attachment to requests
- Error handling and 401 redirects
- React Query for caching and synchronization

## Environment Variables

Frontend uses shared Auth0 variables from root `.env`:

- `AUTH0_DOMAIN` - Auth0 domain
- `AUTH0_CLIENT_ID` - Auth0 client ID
- `AUTH0_AUDIENCE` - Auth0 API audience

Frontend-specific variables:

- `API_BASE_URL` - Backend API URL (default: <http://localhost:8000/v1>)

## Available Scripts

- `pnpm run dev` - Start development server
- `pnpm run build` - Build for production
- `pnpm run preview` - Preview production build
- `pnpm run lint` - Run ESLint
- `pnpm run lint:fix` - Fix ESLint issues
- `pnpm run format` - Format code with Prettier
- `pnpm run format:check` - Check code formatting
- `pnpm run type-check` - Run TypeScript type checking
- `pnpm run test` - Run tests (to be implemented)

## Migration Status

The frontend is currently using mock data from `src/polymet/data/commodities-data.ts` while the backend API endpoints are being implemented. Components in the `polymet/` directory are being gradually migrated to use real API data.

## Contributing

1. Follow the existing code style (Prettier + ESLint)
2. Use TypeScript for all new components
3. Place new UI components in `src/components/ui/`
4. Use shadcn/ui components where possible
5. Write meaningful component and prop names
6. Add proper TypeScript types for all props and API responses

## Performance Considerations

- Components use React.memo where appropriate
- Large lists use virtualization (ag-grid for tables)
- Images are lazy loaded
- Code splitting is implemented via React Router
- Bundle size monitored (currently includes many visualization libraries)

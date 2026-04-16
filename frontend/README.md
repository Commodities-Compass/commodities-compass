# Commodities Compass Frontend

React + TypeScript frontend for the Commodities Compass BI application, providing real-time market insights and trading signals for cocoa (ICE contracts).

## Features

- **Trading Dashboard** - Daily trading signal (OPEN/HEDGE/MONITOR), 6 technical indicator gauges, AI-generated analysis
- **Audio Bulletins** - Compass Bulletin podcast player with waveform visualization
- **Technical Indicators** - MACROECO, MACD, VOL/OI, RSI, %K, ATR with color-coded gauges (RED/ORANGE/GREEN)
- **Price Charts** - Interactive area charts with metric and time period selectors
- **Press Review** - AI-generated market news (Marche/Fondamentaux/Sentiment tabs)
- **Weather Intelligence** - Campaign health, location diagnostics, stress history, Harmattan tracking
- **Authentication** - Auth0 integration with JWT tokens and silent refresh
- **Error Tracking** - Sentry integration with error boundaries

## Tech Stack

- **React 19** - UI framework
- **TypeScript** - Type safety (strict mode)
- **Vite** - Build tool and dev server
- **Tailwind CSS** - Utility-first styling
- **shadcn/ui** - Radix UI primitives + Tailwind components
- **TanStack Query** - Server state management (24h stale time for dashboard data)
- **React Router v7** - Client-side routing with lazy-loaded routes
- **Auth0 React** - Authentication
- **Recharts** - Data visualization
- **Axios** - HTTP client with token interceptor
- **Sentry** - Error tracking and monitoring
- **Vitest** - Unit testing
- **Lucide React** - Icons

## Project Structure

```
frontend/
├── src/
│   ├── api/               # Axios client + dashboard API service
│   ├── assets/            # Logo and static images
│   ├── components/        # Feature components
│   │   └── ui/           # shadcn/ui primitives (button, card, tabs, etc.)
│   ├── data/             # Chart metric options and mock data
│   ├── hooks/            # Custom React hooks (useAuth, useDashboard, use-mobile, use-toast)
│   ├── pages/            # Page components (dashboard, historical, login)
│   ├── test/             # Test setup and utilities
│   ├── types/            # TypeScript type definitions
│   └── utils/            # Utilities (cn, format-financial-text)
├── public/               # Static assets
└── package.json
```

## Getting Started

### Prerequisites

- Node.js 18+
- pnpm 9+
- Auth0 account configured

### Installation

```bash
pnpm install
```

### Environment Variables

```bash
# Auth0 (shared from root .env, exposed via Vite define config — no VITE_ prefix)
AUTH0_DOMAIN=your-domain.auth0.com
AUTH0_CLIENT_ID=your-client-id
AUTH0_AUDIENCE=your-api-audience

# API
API_BASE_URL=http://localhost:8000/v1

# Error tracking (optional for local dev)
SENTRY_DSN=your-sentry-dsn
```

### Development

```bash
pnpm dev              # Start dev server (http://localhost:5173)
pnpm type-check       # TypeScript type checking
pnpm lint             # ESLint
pnpm lint:fix         # ESLint with auto-fix
pnpm format           # Prettier format
pnpm format:check     # Prettier check
```

### Testing

```bash
pnpm test             # Run tests (vitest)
pnpm test:watch       # Watch mode
pnpm test:coverage    # Coverage report
```

### Building

```bash
pnpm build            # Production build
pnpm preview          # Preview production build
```

## Dashboard Components

### Layout

- **DashboardLayout** - Desktop: collapsible sidebar with logo, nav, user profile dropdown. Mobile (<768px): slim top bar with hamburger menu, theme toggle, logout.
- **DateSelector** - Trading day navigation with calendar picker. Disables weekends, exchange holidays, and future dates via `/non-trading-days` API.

### Hero Row (50/50 grid, stacks on mobile)

- **SignalHero** - Trading signal pill (OPEN/HEDGE/MONITOR) with colored ring + dot, plus YTD performance percentage.
- **PodcastPlayer** - Audio player with SoundCloud-style waveform bars (48 bars, click-to-seek, progress coloring). Uses `<audio preload="metadata">` for instant load.

### Content Stack

- **MarketAnalysis** - 6 gauge indicators (MACROECO/MACD/VOL-OI/RSI/%K/ATR) + analysis bullets with direction dots + watchlist box.
- **GaugeIndicator** - SVG semi-circular gauge with color zones (RED/ORANGE/GREEN) and tooltip with indicator metadata.
- **PriceChart** - Recharts area chart with metric selector (close, volume, RSI, stock_us, open_interest, MACD, com_net_us) and days selector.
- **NewsCard** - Tabbed press review (Marche/Fondamentaux/Sentiment) with inline formatting for financial text (percentages, prices, contract codes highlighted).
- **WeatherUpdateCard** - Campaign health bars, location diagnostics grid (6 cocoa-growing zones), stress history, Harmattan tracking.

### Error Handling

- **DashboardErrorBoundary** - Sentry-powered error boundary wrapping each dashboard section independently.
- **ErrorFallback** - User-friendly fallback UI with refresh button.

## Authentication

- Auth0 SPA client with `cacheLocation: "localstorage"` and refresh tokens
- Axios interceptor auto-attaches bearer token to API requests
- 401 responses trigger token clear + `auth:token-expired` event + logout
- Login page includes redirect loop detection (max 3 redirects in 5s window)
- Protected routes via `ProtectedRoute` wrapper

## Routing

| Path | Component | Auth |
|------|-----------|------|
| `/` | `RootRedirect` → `/dashboard` | - |
| `/login` | Login page (Auth0) | Public |
| `/dashboard` | Main trading dashboard | Protected |
| `/dashboard/historical` | Historical data view | Protected |

All routes are lazy-loaded via `React.lazy()` with `Suspense` fallback.

## Performance

- **Code splitting** - React.lazy() for all route-level components
- **Vendor chunking** - Vite splits: vendor, auth, charts, query bundles
- **24h stale time** - Dashboard hooks override React Query default (trading data updates once daily)
- **Sentry** - Browser tracing and session replay in production
- **Hidden source maps** - Production builds generate hidden source maps for Sentry

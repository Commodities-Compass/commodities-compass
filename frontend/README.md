# Commodities Compass Frontend

React + TypeScript frontend for the Commodities Compass BI application, providing real-time market insights and trading signals for cocoa (ICE contracts).

## Features

- **Editorial magazine UI** — Compass CC brand bible 2026 (Playfair Display + Inter + IBM Plex Mono, ink-on-paper palette, light theme only). Layout reads like a daily intelligence briefing.
- **Trading Dashboard** — Daily trading signal (OPEN/HEDGE/MONITOR), 5 technical indicator ruler gauges, AI-generated 3-tab analysis with drop caps.
- **Audio Bulletins** — `Compass Daily Brief` (section I) with waveform visualization.
- **Technical Indicators** — MACD, VOL/OI, RSI, %K, ATR rendered as ruler-scale gauges (HEDGE / MONITOR / OPEN zones).
- **Price Charts** — Monochrome Recharts area with editorial metric dropdown + segmented days pill group.
- **Press Review** — Editorial 3-tab layout (Marché–Technique / Fondamentaux / Sentiment de marché) + 4 sentiment thematic ruler gauges.
- **Weather Intelligence** — Campaign methodology grid (5 saisons), editorial stress-history table, Harmattan tracking.
- **Live ticker** — Full-width scrolling marquee under the masthead (signal/price/DoD/volume/OI/indicators/YTD), pause-on-hover, `prefers-reduced-motion` aware.
- **Authentication** — Auth0 integration with JWT tokens and silent refresh.
- **Error Tracking** — Sentry integration with error boundaries.

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
│   ├── components/
│   │   ├── editorial/    # Editorial primitives: <Eyebrow>, <DataValue>, <DotSeparator>
│   │   ├── weather/      # Weather sub-components: CampaignBlock, StressHistoryBlock, HarmattanBlock, shared
│   │   ├── ui/           # shadcn/ui primitives (button, card, tabs, calendar editorial-restyled)
│   │   ├── dashboard-layout.tsx       # Masthead + ticker + colophon shell
│   │   ├── live-signal-strip.tsx      # Scrolling marquee ticker (mounted in masthead)
│   │   ├── signal-hero.tsx            # Hero headline + composite signal panel
│   │   ├── market-analysis.tsx        # Section II — gauges + tabs + watchlist
│   │   ├── gauge-indicator.tsx        # Ruler-scale gauge (Style 4 from brand bible)
│   │   ├── price-chart.tsx            # Section III — chart + editorial selectors
│   │   ├── news-card.tsx              # Section IV — press review tabs
│   │   ├── weather-update-card.tsx    # Section V — orchestrator
│   │   ├── podcast-player.tsx         # Section I — Compass Daily Brief
│   │   ├── sentiment-gauges.tsx       # 4 thematic sentiment ruler gauges
│   │   ├── section-header.tsx         # Roman numeral + title + rule
│   │   ├── editorial-tabs.tsx         # Magazine-style tabs (Playfair italic active)
│   │   ├── market-analysis/           # Sub-files: technicals/macro/positioning-gauges, editorial-analysis, helpers
│   │   └── date-selector.tsx          # Calendar picker (compact masthead variant)
│   ├── contexts/         # DashboardDateContext (Provider)
│   ├── data/             # Chart metric options, indicator metadata (extracted from gauge-indicator)
│   ├── hooks/            # useAuth, useDashboard, useDashboardDate, use-mobile
│   ├── pages/            # Page components (dashboard, historical, login)
│   ├── test/             # Test setup and utilities
│   ├── types/            # TypeScript type definitions
│   └── utils/            # Utilities (cn, date-utils, ensemble-explanation, format-financial-text, recommendation-parser)
├── public/               # Static assets (favicons regenerated from brand bible 1024 transparent)
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

## Dashboard Composition

The dashboard is structured as a 5-section editorial flow under a magazine masthead. Sections are numbered with Roman numerals (I → V) and separated by full-width ink rules.

### Masthead (DashboardLayout)

- **Top-rule** (mono uppercase 9px) — user dropdown left, compact date picker right.
- **Title block** — `COMPASS CC` (Playfair 900, clamp 44–76px) + `The Cocoa Markets Intelligence Briefing` italic deck + compass icon lockup on the right.
- **Signal triplet legend** — OPEN / MONITOR / HEDGE colored dots.
- **LiveSignalStrip** — scrolling marquee band (60s linear, pause-on-hover, fade mask, respects `prefers-reduced-motion`) showing signal, ICE LDN price, DoD%, volume, OI, RSI, MACD, %K, ATR, V/OI, YTD, session date.
- **Colophon footer** — user info + version.

### Hero (SignalHero, above section I)

Lead Analysis kicker + Playfair 56px headline `Signal [POSITION] — Cocoa [trend]` with inline colored signal pill, Georgia italic deck from `useRecommendations`, Compass Intelligence Desk byline. 320px score panel on the right with position badge + YTD performance.

### Section I — `PodcastPlayer` (Compass Daily Brief)

NotebookLM audio player with click-to-seek waveform (56 deterministic bars), pause-on-hover ink play button.

### Section II — `MarketAnalysis`

Two sub-blocks under a single section header:

1. **Compass Gauges** — 5 ruler-style `GaugeIndicator`s (MACD / VOL-OI / RSI / %K / ATR) with HEDGE/MONITOR/OPEN zone labels, colored triangle marker, mono value above. Tick marks at zone boundaries.
2. **Editorial body** — `EditorialTabs` (Playfair italic active) with three tabs (`Recommandation` / `Supply & Momentum` / `Technical Outlook`) on the left, parsed from `useRecommendations()`, first paragraph gets a Playfair drop cap. `À surveiller` sidebar on the right (`paper-off` bg, ink left border).

### Section III — `PriceChart` (Price History & Signal Overlay)

Monochrome Recharts area, `MetricDropdown` (mono uppercase trigger + ink underline) + `DaysPillGroup` (segmented `30J / 90J / 180J / 1Y`). Editorial caption `Fig. 1 — ...` below.

### Section IV — `NewsCard` (Press Review)

Top: 4 sentiment thematic ruler gauges (PRODUCTION / CHOCOLAT / TRANSF. / ÉCONOMIE) from `useNewsSentiment`. Then `EditorialTabs` (`Marché — Technique` / `Fondamentaux` / `Sentiment de marché`) with Playfair italic body + drop quote `"`. Impact synthesis box + keyword pills below.

### Section V — `WeatherUpdateCard` (Weather Intelligence)

Orchestrator wiring sub-components from `src/components/weather/`:

- **CampaignBlock** — `Campagne YYYY-YY` header + `Santé globale X.X/5` (Playfair colored) + 5-column methodology grid (one column per saison with serif numeral + colored score + status badge).
- **StressHistoryBlock** — editorial table (Origin / Pays / Tendance 7j as vertical bars / Streak / Trend arrow / Statut pill).
- **HarmattanBlock** — risk badge + jours cumulés + affected sites list.
- **Bulletin du jour** at the bottom in Georgia editorial text.

### Date selector (DateSelector)

Two variants:
- `compact` (used in masthead) — single mono uppercase button with calendar icon, popover calendar opens on click.
- `card` (legacy) — Card-wrapped picker with chevrons.

Disables weekends, exchange holidays, and future dates via `/non-trading-days` API.

### Editorial primitives (`src/components/editorial/`)

- `<Eyebrow>` — mono uppercase eyebrow/kicker (three tones).
- `<DataValue>` — mono tabular numerals for ticker numbers, scores, prices.
- `<DotSeparator>` — small `--rule` dot between ticker cells.

### Error handling

- **DashboardErrorBoundary** — wraps each dashboard section independently.
- **ErrorFallback** — User-friendly fallback UI with refresh button.

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

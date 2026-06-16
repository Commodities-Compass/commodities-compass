# Compass CC — Landing (com-compass.com)

Marketing landing for [com-compass.com](https://com-compass.com). Built with **Astro 5** (static, 0 JS by default) + **Tailwind v4** + **i18n FR/EN**.

Separate from the dashboard SPA (`frontend/`) on purpose — see [docs/landing/COMPASS_LANDING_V2_PRESENTATION.html](../docs/landing/COMPASS_LANDING_V2_PRESENTATION.html) for the rationale.

## Domain split

| Domain | What | Codebase |
|---|---|---|
| `com-compass.com` | Marketing landing (this) | `landing/` |
| `app.com-compass.com` | Dashboard SPA (auth required) | `frontend/` |
| `auth.com-compass.com` | Auth0 universal login (later) | Auth0 tenant config |
| `api.com-compass.com` | FastAPI backend | `backend/` |

## Stack

- **Astro 5** — static site generator, 0 JS by default
- **Tailwind v4** (via `@tailwindcss/vite`) — utility CSS
- **i18n built-in** — `/` = FR (default), `/en/` = EN
- **MDX** — for future content pages (sample brief, blog, legal)
- **Self-hosted fonts** via `@fontsource(-variable)` — Inter + Playfair Display + IBM Plex Mono (Georgia is system serif)
- **TypeScript strict** — type-safe content + i18n strings

## Commands

```bash
pnpm install        # install deps
pnpm dev            # http://localhost:4321
pnpm build          # output to dist/
pnpm preview        # serve built dist/
pnpm check          # type-check (astro check)
```

## Architecture

```
landing/
├── astro.config.mjs       # i18n config, sitemap, mdx, tailwind vite plugin
├── tsconfig.json          # strict + @/* path aliases
├── public/
│   ├── compass-icon.png   # brand mark (copied from frontend/public/)
│   ├── favicon-*.png      # favicons
│   ├── og-image.png       # social share
│   └── robots.txt
└── src/
    ├── styles/global.css  # @theme tokens (ink/paper, font stack) + base
    ├── i18n/strings.ts    # FR + EN copy registry (single source of truth)
    ├── layouts/
    │   └── BaseLayout.astro  # html shell + meta/OG + hreflang
    ├── components/
    │   ├── Masthead.astro    # sticky brand bar + lang switch + CTA
    │   ├── Footer.astro      # colophon + disclaimer
    │   └── sections/
    │       ├── Hero.astro            # H1 + lede + dual CTA
    │       └── PhasePlaceholder.astro # Phase-1 placeholder for Sections II→V
    └── pages/
        ├── index.astro     # / (FR default)
        └── en/index.astro  # /en/ (EN)
```

## Brand tokens

Mirrored from [`frontend/src/index.css`](../frontend/src/index.css) so visual continuity between `com-compass.com` and `app.com-compass.com` is exact.

| Token | Value | Use |
|---|---|---|
| `--color-paper` | `#FFFFFF` | Page background |
| `--color-paper-off` | `#F5F5F5` | Section alt-bg, footer |
| `--color-ink` | `#1A1A1A` | Body copy, CTAs |
| `--color-ink-mid` | `#4A4A4A` | Secondary text |
| `--color-ink-light` | `#8A8A8A` | Tertiary text, ghosted numerals |
| `--color-rule` | `#E5E5E5` | Hairlines, borders |
| `--color-signal-open` | `#10B981` | OPEN signal badge only |
| `--color-signal-monitor` | `#F59E0B` | MONITOR signal badge only |
| `--color-signal-hedge` | `#EF4444` | HEDGE signal badge only |

| Font role | Family | Use |
|---|---|---|
| `--font-display` | Playfair Display Variable | H1/H2, italic for editorial voice |
| `--font-sans` | Inter Variable | Body, nav, buttons |
| `--font-mono` | IBM Plex Mono | Eyebrows, data labels, dates |
| `--font-editorial` | Georgia (system) | Editorial paragraph body, deck |

## i18n

- Default locale = `fr` (no prefix → `/`)
- Other locale = `en` (prefixed → `/en`)
- Copy is centralised in [`src/i18n/strings.ts`](src/i18n/strings.ts) — pure TS object, no runtime cost
- The Masthead language switcher exposes `EN` ↔ `FR` toggle
- `hreflang` tags emitted on every page via `BaseLayout`

**Hero H1 stays universal English** (`"Decide before the bell."`) per brand decision — only the lede swaps FR/EN.

## Phase status

- [x] **Phase 1 — Bootstrap** *(this commit)*: Astro + Tailwind v4 + i18n FR/EN + brand fonts + brand tokens + minimal Hero + masthead/footer + favicons + sitemap. Verification slice: dev server starts, both `/` and `/en` render, build is clean.
- [ ] **Phase 2 — Design system components**: port sections II→V from `mockup/landing/option-D-editorial-glass.html`.
- [ ] **Phase 3 — Content + copy MDX**: full FR + EN content, sample brief page.
- [ ] **Phase 4 — SEO + perf pass**: meta/OG audit, JSON-LD, Lighthouse ≥95.
- [ ] **Phase 5 — DNS switch**: backup Squarespace → `legacy.com-compass.com`, swap apex DNS to Vercel.

See [docs/user-stories/P1-landing-page-v2-redesign.md](../docs/user-stories/P1-landing-page-v2-redesign.md) for the full plan.

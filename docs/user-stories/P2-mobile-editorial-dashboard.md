# User Story: Mobile Editorial Dashboard

## Epic

As the **CTO/sole operator**, I want the Compass CC editorial dashboard to render cleanly on phones (375–428 px) and tablets (768–1024 px), so I can check the daily signal, the live ticker, the gauges, and the press review on the go without zooming, scrolling horizontally, or losing the editorial identity that ships on desktop today.

Companion story to the desktop-first editorial redesign (merged as `feat/brand-bible-redesign`). The desktop build is locked; this story is the responsive layer on top.

---

## Context

**Current state** (post brand-bible-redesign, light theme, desktop-first):

- The masthead places `COMPASS CC` (Playfair clamp 44–76px) + italic deck + the compass logo in a horizontal lockup, with the live scrolling ticker as a full-width band below.
- Section II `MarketAnalysis` uses a `2fr / 1fr` grid: tabs panel left, `À surveiller` sidebar right.
- Section III chart uses a `MetricDropdown` + `DaysPillGroup` toolbar.
- Section V weather has a 5-column `CampaignBlock` (one column per saison) and a 6-column `StressHistoryBlock` table.
- The masthead top-rule lays out as `flex justify-between` with the user dropdown left and the compact date picker right.
- A few components already ship inline `@media (max-width: …)` rules in scoped `<style>` blocks (e.g. `market-analysis.tsx` collapses the gauges grid at 1024 px; `campaign-grid` collapses at 900 px; `sentiment-row` collapses at 720 px). These were spot fixes, not a coherent responsive system.

**Target state**: every section reflows gracefully from 375 px upward, with no horizontal scroll, no overlapping text, and no broken touch targets, while preserving the Playfair / Inter / IBM Plex Mono hierarchy and the ink-on-paper palette.

Mobile is not the primary use case (the user is a CTO consulting a daily desktop dashboard), so we accept reduced density on phones — for example folded sections, drawer navigation, or accordion gauges — as long as the editorial voice is intact.

---

## Out of scope

- Dark mode (separate P2 follow-up).
- Native app / PWA install prompt (separate epic if ever).
- Touch-first reordering of sections (the existing I → V flow stays).
- Backend changes — the data contract is stable.

---

## User Stories

### US-1: Phone-first masthead

**As** a user opening the dashboard on a phone (375–428 px),
**I want** the masthead to remain legible and tappable,
**so that** I can see the publication identity and pick a session date in one screen.

**Acceptance criteria**:

- At 375 px:
  - The compass icon stacks above the `COMPASS CC` wordmark (vertical lockup) instead of horizontal.
  - `COMPASS CC` shrinks to ~36 px max so the wordmark fits in one line.
  - Italic deck `The Cocoa Markets Intelligence Briefing` wraps to 2 lines max, centered.
  - Signal triplet legend (OPEN / MONITOR / HEDGE) collapses to one item per row OR a 2-column grid.
  - The compact date picker remains tappable (≥ 44 × 44 px hit area).
  - The user avatar dropdown stays in the top-rule but the displayed name is hidden (avatar only) under `sm`.
- The live ticker continues to scroll, with the fade mask and pause-on-tap behavior (replaces pause-on-hover on touch devices).
- No horizontal scroll anywhere.

### US-2: Section II — stacked editorial layout

**As** a user reading the daily analysis on mobile,
**I want** the gauges row and the tabs panel + sidebar to stack vertically without losing data,
**so that** I can scroll through the content like a magazine article.

**Acceptance criteria**:

- **Gauges row** (Compass Gauges sub-block):
  - At ≤ 600 px: 2 columns. At ≤ 400 px: 1 column.
  - Each ruler gauge keeps the value above, the triangle marker, the ruler line with ticks, and the `HEDGE / MONITOR / OPEN` labels below.
  - At 1 column the ruler stretches to the full content width.
- **Editorial body**:
  - At ≤ 1024 px (already partly handled): `market-grid` collapses to a single column. `À surveiller` moves below the tabs panel as a closing block.
  - Tabs strip wraps to a second row if needed (`flex-wrap` already on).
  - Drop cap in the active tab’s first paragraph stays.
- No row overflow even when a recommendation paragraph is long (justify text + hyphens).

### US-3: Section III — touch chart toolbar

**As** a user on a phone,
**I want** to swap chart metric and time range with one-handed taps,
**so that** I don't fight a desktop dropdown UI.

**Acceptance criteria**:

- `MetricDropdown` trigger area is ≥ 44 px tall.
- `DaysPillGroup` `30J / 90J / 180J / 1Y` segmented control: each pill is ≥ 40 × 40 px, no wrap below 360 px (drop to abbreviations `30 · 90 · 180 · 1Y` if needed).
- Chart container keeps a `360 px` height on phones; X-axis tick labels skip every other gap to avoid overlap.
- Recharts tooltip uses a tappable cursor mode on touch devices.

### US-4: Section IV — readable press tabs

**As** a user scrolling the press review on mobile,
**I want** the 3 tabs to remain visible and the tab content to read like a phone article,
**so that** the editorial voice survives a small screen.

**Acceptance criteria**:

- Tab strip wraps to 2 rows if labels can’t fit horizontally; the active tab’s underline remains the only ink rule under the strip.
- Article body keeps the leading `"` drop quote at a reduced size (~ 36 px instead of 64 px).
- Attribution line wraps; no truncation.
- Sentiment thematic gauges row uses the same 2-col / 1-col responsive rule as US-2 gauges.

### US-5: Section V — weather table → cards

**As** a user reading weather intel on mobile,
**I want** the `StressHistoryBlock` table to convert into a list of cards,
**so that** I don't have to scroll a 6-column table sideways.

**Acceptance criteria**:

- At ≤ 720 px the editorial table is replaced by a vertical list. Each card shows:
  - Origin name (Playfair italic, ink) + country (subtitle).
  - Tendance 7j bars (full width, slightly taller — 18 px max).
  - Streak + trend arrow on one row.
  - Status pill on the right.
- `CampaignBlock` already collapses to 2-col at 900 px; add a 1-col stack at ≤ 480 px with the seasons becoming a vertical list (still with serif numeral + colored score).
- `HarmattanBlock` already mobile-friendly (single column flex); keep as-is.
- `Bulletin du jour` body shrinks to 13 px / 1.6 line-height; no other change.

### US-6: Section I — podcast on phones

**As** a user on a phone,
**I want** the Compass Daily Brief audio player to work cleanly,
**so that** I can play the bulletin while doing something else.

**Acceptance criteria**:

- Play button stays 56 px circle.
- Waveform fills full width; bars scale down to min `2 px` width.
- Time labels stay visible (current / total) on either side.
- Buffering spinner replaces the play icon mid-stream as today.

### US-7: Live ticker on touch

**As** a user on a touch device,
**I want** to read the ticker without it scrolling away,
**so that** I can grab the numbers.

**Acceptance criteria**:

- Pause-on-hover is replaced by pause-on-touch: tapping the ticker pauses the animation; tapping outside resumes.
- Fade-mask edges adjust to 16 px instead of 32 px on phones.
- The ticker remains a single line — no wrap, no second row.

### US-8: Auth0 + redirects untouched

**As** a user logging in from mobile Safari / Chrome,
**I want** the existing Auth0 flow to keep working,
**so that** the redesign doesn't introduce mobile-specific auth bugs.

**Acceptance criteria**:

- `RootRedirect`, `ProtectedRoute`, and the 401 → `auth:token-expired` event still behave the same.
- No layout shifts during Auth0 callback that could strip `?code=` params (pre-existing bug class, already documented in `CLAUDE.md`).

---

## Definition of Done

- Each section verified at **375 px** (iPhone SE), **414 px** (iPhone 14 Pro Max), **768 px** (iPad portrait), **1024 px** (iPad landscape) using Chrome DevTools device emulation, then on a real iPhone for the published preview URL.
- No horizontal scroll at any breakpoint.
- All interactive elements have ≥ 40 × 40 px hit areas.
- Lighthouse mobile score ≥ 90 on accessibility.
- `pnpm type-check && pnpm lint && pnpm build` green.
- Smoke flow: login → land on `/dashboard` → navigate date picker to `2026-05-01` → scroll through sections I → V → play audio → switch press review tabs → all OK.

---

## Implementation hints (non-binding)

The current desktop layout is built mostly with inline `style={{}}` + a few scoped `<style>` media queries. The most painful conversions are:

| Component | Hint |
|---|---|
| `dashboard-layout.tsx` | Add `<style>` block with media queries that flip the title block from `flex-row` to `flex-col`, collapse the legend, hide the user display name under `sm`. |
| `live-signal-strip.tsx` | Add a `touchstart` handler that toggles `animation-play-state: paused` on `.ticker-track`. Alternative: CSS `@media (hover: none) and (pointer: coarse)` → no auto-pause, only manual via tap. |
| `market-analysis.tsx` | The grid breakpoint at 1024 px already stacks; just verify the `À surveiller` sidebar lands below the tabs panel and doesn't lose its border-left treatment. |
| `price-chart.tsx` | Days pill group already handles narrow widths via `flex-wrap`. The metric dropdown popover needs `sideOffset` adjusted on mobile so it doesn't clip. |
| `weather/StressHistoryBlock.tsx` | Conditional render: at ≤ 720 px return a `<ul>` of `<li>` cards instead of the `<table>`. Reuse the same status pill + bars sub-components. |
| `weather/CampaignBlock.tsx` | Extend the existing `@media (max-width: 900px)` rule with a `@media (max-width: 480px)` that goes to `repeat(1, 1fr)`. |
| `news-card.tsx` | The press article body already has `text-align: justify` + Georgia editorial; just verify line-length stays comfortable below 480 px (consider `hyphens: auto`). |
| `editorial-tabs.tsx` | Already supports `flex-wrap` in the tab strip — verify the underline tracking stays aligned when a tab wraps to row 2. |

---

## Verification plan

1. `pnpm dev` with Chrome DevTools device emulation: walk through iPhone SE, iPhone 14 Pro Max, iPad portrait, iPad landscape.
2. Lighthouse mobile audit on the production preview URL — accessibility ≥ 90.
3. Real-device QA on iPhone (iOS Safari) + Android (Chrome).
4. Verify the live ticker pause-on-touch flow.
5. Confirm Auth0 login + protected-route + 401 → logout flow still works on mobile.
6. Confirm calendar picker opens above content with proper `sideOffset` (no clipping on phones).
7. `pnpm build && pnpm preview` and re-test the production build on the same devices.

---

## Risks & open questions

- **Drawer navigation**: do we need a hamburger / drawer for navigation, or does the single-page `/dashboard` flow make this unnecessary? Current answer: not needed for v1 mobile.
- **Section anchor links**: would a sticky "Go to section X" bar help on long phone scrolls? Probably yes but out of scope for this story.
- **Performance**: Recharts is heavy on phones. Consider lazy-loading the chart section below the fold (`React.lazy` is already used for routes — extend to sections).
- **Test devices**: I (CTO) own iPhone + iPad. Android coverage will be Chrome DevTools emulation unless we have a tester.

---

## Estimated effort

- 1–2 dev days (no backend, no data layer changes, no new components — only responsive rules + StressHistory card conversion).
- Reviewer pass + real-device QA: half a day.

---

## Status

- **Created**: 2026-05-19, alongside the brand-bible-redesign merge to production.
- **Owner**: TBD.
- **Target**: pick up after the editorial v1 has spent a week in prod.

# Press Review Agent (US-003 → V2)

Automated LLM agent that generates a daily French-language cocoa press review, extracts per-theme sentiment scores, and writes both to GCP PostgreSQL. The press review serves two purposes: a daily briefing for traders (narrative) and structured sentiment data for the trading engine (signal).

## Architecture

```
pl_contract_data_daily (read CLOSE)
    ↓
Fixed sources (8, httpx/Playwright) → full content
Google News RSS (8 thematic queries) → headlines only (titles, no link following)
    ↓
LLM (o4-mini) — single call, two outputs:
    ├→ resume + mots_cle + impact_synthetiques  → pl_fundamental_article (trader reads)
    └→ theme_sentiments (4 scores [-1,+1])      → pl_article_segment    (signal pipeline)
```

## V2 Changes (April 2026)

Driven by EXP-014 findings: only **production** (p=0.017) and **chocolat** (p=0.025) themes carry Granger-significant signal at lag 3-4 days via z-score delta.

| Change | Before | After |
|--------|--------|-------|
| Sources | 10 (4 redundant Reuters intermediaries) | 8 fixed + Google News RSS (8 queries) |
| Prompt priority | MARCHE first | OFFRE/FONDAMENTAUX first (signal-carrying themes) |
| Output fields | 3 (resume, mots_cle, impact) | 4 (+theme_sentiments) |
| MAX_CHARS_PER_SOURCE | 2000 | 4000 (prevents content truncation on heavy days) |
| Sentiment extraction | None | Inline per-theme scores stored in pl_article_segment |
| JSON parser | Basic (fences + newlines) | OpenAI: API JSON mode. Others: balanced brace extraction + 6-stage repair cascade |

Full strategy document: [press-review-v2-strategy.md](../../../docs/press-review-v2-strategy.md)

## News Sources (8 fixed + Google News RSS)

### Fixed Sources (full content via httpx/Playwright)

| Source | Theme | Method | Status |
|--------|-------|--------|--------|
| Investing.com Cocoa | Market (price context) | httpx | OK |
| CocoaIntel | Production + Market | httpx | OK |
| ICCO News | Production (official) | httpx | OK |
| Confectionery News | Chocolat / Demand | httpx | OK |
| Abidjan.net | Africa / Production | httpx | OK |
| Cacao.ci | Production Ivory Coast | httpx | OK — *new in V2* |
| The Cocoa Post | Production Ghana/Global | httpx | OK — *new in V2* |
| Agence Ecofin Cacao | Africa / Production | Playwright | OK |

### Google News RSS (headlines only — coverage layer)

12 thematic queries (6 themes × 2 languages EN/FR), `when:3d` window, max 10 items per query. Headlines are deduplicated by MD5 hash and passed to the LLM as a separate "Headlines du jour" section in the prompt. No link following — titles only.

| Theme | Query (EN) | Query (FR) |
|-------|-----------|-----------|
| production | cocoa AND (crop OR ivory coast OR ghana) | cacao AND (arrivages OR récolte OR production) |
| chocolat | cocoa AND (grindings OR chocolate demand) | cacao AND (broyages OR chocolat OR demande) |
| marche | cocoa AND (price OR futures OR market) | cacao AND (prix OR cours OR marché) |
| offre | cocoa AND (supply OR deficit OR stocks) | cacao AND (offre OR déficit OR stocks) |
| economie | cocoa AND (dollar OR currency OR tariff OR trade policy) | cacao AND (dollar OR devise OR tarif OR inflation) |
| transformation | cocoa AND (processing OR grinding OR butter OR powder) | cacao AND (broyage OR transformation OR beurre OR usine) |

The 4 sentiment themes (production, chocolat, transformation, economie) each have dedicated queries. The marche and offre queries feed the resume content but don't map directly to sentiment themes.

### Removed Sources (V2)

| Source | Reason |
|--------|--------|
| Barchart Cocoa News | Redundant — same Reuters wire as Investing.com |
| Nasdaq Cocoa | Redundant — same Reuters wire |
| MarketScreener Cocoa | Redundant — same Reuters wire |
| ICCO Statistics | Quasi-static page, rarely updated |

### Sources that don't work via httpx (tried and rejected)

| Source | Issue |
|--------|-------|
| Reuters | DataDome WAF — 401 ($2K-5K+/month API, not worth it for zero-signal theme) |
| Commodafrica | 503 Service Unavailable |
| Candy Industry | 403 WAF |
| Barry Callebaut | Content not extractible (corporate format) |
| Bloomberg / FT | WAF |

## Output Format

Each run produces a JSON with 4 fields:

| Field | Target | Description |
|-------|--------|-------------|
| `resume` | pl_fundamental_article.summary | 600-1500 words French analysis (OFFRE → FONDAMENTAUX → MARCHE → SENTIMENT) |
| `mots_cle` | pl_fundamental_article.keywords | Semicolon-separated data points from sources |
| `impact_synthetiques` | pl_fundamental_article.impact_synthesis | 100-250 word synthesis paragraph |
| `theme_sentiments` | pl_article_segment (×1-4 rows) | Per-theme score [-1,+1], confidence [0,1], rationale |

### theme_sentiments example

```json
{
  "production": {"score": -0.6, "confidence": 0.8, "rationale": "Inquiétudes mid-crop CI"},
  "chocolat": {"score": 0.3, "confidence": 0.7, "rationale": "Demande asiatique soutenue"}
}
```

Themes are omitted if no source covers them (NULL, not 0 — per EXP-014).

## Database Write

For each successful provider result, writes three records:

1. **`pl_fundamental_article`** — resume, keywords, impact_synthesis, source metadata
2. **`aud_llm_call`** — tokens, latency, model audit trail
3. **`pl_article_segment`** (×1-4 rows) — per-theme sentiment with `extraction_version='inline_v1'`, `zone='all'`

Theme sentiment write is non-blocking — if it fails, the article is still persisted.

## Shadow Mode Pipeline

A separate CLI computes z-delta features from accumulated sentiment data:

```
pl_article_segment (inline_v1) → avg by (date, theme)
    → rolling z-score (21 days, min_periods=5)
    → delta 3 days: z[t] - z[t-3]
    → pl_sentiment_feature (shadow — not injected into trading engine)
```

CLI: `poetry run compute-sentiment-features [--dry-run]`

Features will be activated when n > 250 (~October 2026) after re-validation of EXP-014.

## CLI Usage

```bash
# Production run (single provider, writes to DB)
poetry run press-review [--force]

# Dry run (calls LLM but skips DB writes)
poetry run press-review --dry-run --verbose

# Specific provider
poetry run press-review --provider claude --dry-run

# Compute sentiment z-delta features
poetry run compute-sentiment-features [--dry-run]
```

### Arguments

| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--provider` | `claude`, `openai`, `gemini`, `all` | `openai` | Which LLM(s) to run |
| `--dry-run` | flag | off | Run pipeline but don't write to DB |
| `--verbose` | flag | off | Enable DEBUG logging |
| `--force` | flag | off | Run on non-trading days |

## File Structure

```
backend/scripts/press_review_agent/
├── __init__.py
├── config.py            # Sources, Google News queries, prompts, models, validation, themes
├── db_reader.py         # Read CLOSE from pl_contract_data_daily
├── news_fetcher.py      # httpx + Playwright + Google News RSS (XML parsing, MD5 dedup)
├── llm_client.py        # 3 async provider functions + JSON extraction
├── validator.py         # Output validation (resume, mots_cle, impact, theme_sentiments)
├── db_writer.py         # Write to pl_fundamental_article + aud_llm_call + pl_article_segment
├── main.py              # CLI orchestrator with Sentry monitoring
└── run_agent.sh         # Cloud Run Job entry point

backend/scripts/compute_sentiment_features/
├── __init__.py
└── main.py              # CLI for z-delta computation (shadow mode)

backend/app/engine/
└── sentiment_features.py  # Pure function: rolling z-score + delta per theme
```

## Troubleshooting

### JSON extraction fails

**OpenAI (o4-mini)** uses `response_format={"type": "json_object"}` which guarantees valid JSON from the API. This was added after o4-mini produced double closing braces (`{...}}`) on 2026-04-22, causing two production failures.

**Claude and Gemini** don't have API-level JSON mode, so they rely on the `extract_json()` repair cascade in `scripts/llm_utils.py`:
1. Balanced brace extraction (finds matching `}` via depth counting, not `rfind`)
2. Markdown fences (` ```json ... ``` `)
3. Unescaped newlines/tabs inside strings
4. Trailing commas before `}` or `]`
5. Unclosed braces (truncated output — appends missing `}`)
6. Invalid escape sequences (`\'`, `\x`, `\a`)
7. Unescaped double quotes inside string values (heuristic)

### Theme sentiments missing for some themes

Check per-theme headline counts in logs: `Google News: N unique headlines from 12 queries (chocolat=5, economie=3, marche=12, offre=8, production=9, transformation=2)`.

Each of the 4 sentiment themes (production, chocolat, transformation, economie) has dedicated Google News queries. If a theme is still empty despite headlines, the LLM may not be mapping content correctly — check the theme definitions in the prompt.

The prompt instructs the LLM to "aim to score all 4 themes when possible" — even brief mentions of currency moves or trade policy in market commentary qualify for "economie". Low counts on weekends are expected.

**Bug fixed (2026-04-23):** Two issues caused "economie" to be empty for 3 consecutive sessions:
1. The theme was declared in THEMES but had no Google News queries — the LLM never saw economic content. Fixed by adding 4 queries (economie EN/FR + transformation EN/FR).
2. Headlines were passed to the LLM as a flat list without theme tags — the LLM couldn't map headlines to sentiment themes. Fixed by grouping headlines under `**ECONOMIE**`, `**PRODUCTION**`, etc. in the prompt.

### Resume too short

`resume_min_chars` is set to 800. If validation fails, the prompt instructs 600-1500 words with "développe en profondeur" on OFFRE and FONDAMENTAUX sections.

## Pipeline Schedule

```
7:00 PM UTC  -- Barchart scraper       → pl_contract_data_daily (OHLCV + IV)
7:00 PM UTC  -- Meteo agent            → pl_weather_observation
7:05 PM UTC  -- ICE stocks + CFTC      → pl_contract_data_daily (STOCK US, COM NET US)
7:05 PM UTC  -- Press review agent     → pl_fundamental_article + pl_article_segment ← this
7:15 PM UTC  -- Compute indicators     → pl_derived_indicators + pl_indicator_daily
7:20 PM UTC  -- Daily analysis          → pl_indicator_daily (LLM decision + score)
7:30 PM UTC  -- Compass brief          → Google Drive (.txt for NotebookLM)
```

Cron: `05 19 * * 1-5` (7:05 PM UTC weekdays)

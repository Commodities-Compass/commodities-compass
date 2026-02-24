# Press Review Agent (US-003)

Automated LLM agent that generates a daily French-language cocoa press review and writes it to the BIBLIO_ALL Google Sheet. Eliminates the last manual step before human validation.

## Architecture

```
TECHNICALS sheet (read CLOSE) → httpx (6 news sources) → LLM(s) → BIBLIO_ALL sheet(s)
```

Follows the same patterns as existing scrapers (barchart, ICE, CFTC): argparse CLI, Sentry cron monitoring, Google Sheets API, structured logging.

## A/B Test (Current Phase)

Running 3 providers in parallel for comparison before picking a winner:

| Provider | Model | Staging Sheet |
|----------|-------|---------------|
| Claude | `claude-sonnet-4-5-20250929` | `BIBLIO_ALL_STAGING_CLAUDE` |
| OpenAI | `gpt-4.1` | `BIBLIO_ALL_STAGING_OPENAI` |
| Gemini | `gemini-2.5-pro` | `BIBLIO_ALL_STAGING_GEMINI` |

Same system prompt and news sources for all 3 — fair comparison.

## News Sources (6)

| Source | URL | Status |
|--------|-----|--------|
| Barchart Cocoa News | barchart.com/futures/quotes/CA*0/news | OK |
| Investing.com Cocoa | investing.com/commodities/us-cocoa-news | OK |
| Nasdaq Cocoa | nasdaq.com/market-activity/commodities/cj:nmx | OK |
| CocoaIntel | cocoaintel.com | OK |
| MarketScreener Cocoa | marketscreener.com/.../COCOA-2298/news/ | OK |
| ICCO News | icco.org/news/ | OK |

Graceful degradation: if < 2 sources return content, agent runs in price-only mode.

### Sources that don't work via httpx (tried and rejected)

| Source | Issue | Replaced by |
|--------|-------|-------------|
| Reuters (`reuters.com/markets/commodities/`) | DataDome WAF — 401 on all non-browser clients | Investing.com (same Reuters wire content) |
| TradingEconomics (`tradingeconomics.com/commodity/cocoa`) | All cocoa data is JS-rendered, SSR shell is empty | CocoaIntel (cocoa-specialized) |
| ICCO old URL (`icco.org/category/press-release/`) | 404 — site restructured | Fixed to `icco.org/news/` |
| Yahoo Finance (`CC=F`) | Returns error page | Not used |
| MarketWatch | Same DataDome WAF as Reuters | Not used |

## Environment Variables

```bash
# Required — LLM API keys (add to backend/.env)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-proj-...
GEMINI_API_KEY=AIza...

# Existing — already set in .env
GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON=...
SENTRY_DSN=...
```

## CLI Usage

```bash
# All 3 providers, dry-run (no writes), verbose logging
poetry run python -m scripts.press_review_agent.main --sheet staging --dry-run --verbose

# All 3 providers, write to staging sheets
poetry run python -m scripts.press_review_agent.main --sheet staging

# Single provider only
poetry run python -m scripts.press_review_agent.main --sheet staging --provider claude

# Production (single winner, after A/B test)
poetry run python -m scripts.press_review_agent.main --sheet production --provider claude
```

### Arguments

| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--sheet` | `staging`, `production` | `staging` | Target sheet mode |
| `--provider` | `claude`, `openai`, `gemini`, `all` | `all` | Which LLM(s) to run |
| `--dry-run` | flag | off | Run pipeline but don't write to Sheets |
| `--verbose` | flag | off | Enable DEBUG logging |

## Output Format (BIBLIO_ALL)

Each run appends a new row at the bottom of the sheet (chronological order).

| Column | Field | Example |
|--------|-------|---------|
| A | DATE | `02/24/2026` |
| B | AUTEUR | `LLM Agent (Claude Sonnet 4.5)` |
| C | RESUME | 800-1200 word French market analysis |
| D | MOTS-CLE | `Londres CAH26 2 261 GBP/t ; ...` |
| E | IMPACT SYNTHETIQUES | 150-250 word synthesis paragraph |
| F | DATE TEXT | `24 fevrier 2026` |

## Pipeline Schedule (Railway Cron)

```
7:00 PM UTC  — Barchart scraper writes CLOSE to TECHNICALS
7:30 PM UTC  — Press review agent reads CLOSE + fetches news + writes BIBLIO_ALL  ← this
8:30 PM UTC  — 1DAY METEO writes METEO_ALL
10:15 PM UTC — Railway ETL imports all sheets to PostgreSQL
11:00 PM UTC — DAILY BOT AI reads everything → INDICATOR
```

Cron: `30 19 * * 1-5` (weekdays only)

## File Structure

```
backend/scripts/press_review_agent/
├── __init__.py
├── config.py            # Sources, prompts, sheet names, models, validation
├── sheets_reader.py     # Read CLOSE from TECHNICALS (last row)
├── news_fetcher.py      # httpx + BeautifulSoup, 6 sources
├── llm_client.py        # 3 async provider functions + JSON extraction
├── validator.py         # Output length/structure checks
├── sheets_writer.py     # Append row to BIBLIO_ALL sheets (bottom of sheet)
├── main.py              # CLI orchestrator with Sentry monitoring
└── run_agent.sh         # Railway cron entry point
```

## Troubleshooting

### JSON extraction fails for a provider

All 3 LLMs wrap JSON in markdown fences (` ```json ... ``` `) and output literal newlines inside JSON string values. The `extract_json()` function in `llm_client.py` handles both:
1. Strips markdown fences
2. Extracts content between first `{` and last `}`
3. Escapes literal newlines/tabs inside string values via `_fix_unescaped_newlines()`

If a provider still fails, it's likely hitting the `max_tokens` limit and the JSON is truncated (no closing `}`). The current limit is 8192 tokens — increase in `llm_client.py` if needed.

### Response truncated (no closing brace)

Gemini 2.5 Pro generates verbose `resume` fields (5000+ chars). If `max_output_tokens` is too low (e.g. 4096), the response gets cut off mid-sentence and JSON parsing fails with "No JSON object found". Fix: set `max_output_tokens=8192` (already done).

### News source returns 401/403

Some sites (Reuters, MarketWatch) use DataDome/Cloudflare WAF that blocks all non-browser requests regardless of User-Agent. These cannot be fixed with httpx — they require Playwright. We replaced them with accessible alternatives (see rejected sources table above).

### News source returns empty content

If a site returns HTML but the CSS selectors don't match any content, it's likely JS-rendered (TradingEconomics). The page HTML is just a shell. Fix: replace with a site that serves server-rendered content.

### API key not found

The `.env` is loaded via `load_dotenv()` at module level in `main.py`. If running outside the CLI (e.g. testing in a Python REPL), load it manually:
```python
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path('.env'))
```

## Current Status

- [x] All 8 module files created and importable
- [x] Dependencies installed (`anthropic`, `openai`, `google-genai`)
- [x] Sheets reader tested — reads CLOSE from TECHNICALS_STAGING
- [x] News fetcher tested — 6/6 sources returning content
- [x] Validator tested — catches short/missing fields
- [x] JSON extractor hardened — handles markdown fences, literal newlines, truncation
- [x] Live staging test — all 3 providers write successfully
- [ ] Run 3-day A/B test, compare outputs in staging sheets
- [ ] Pick winner, switch to single-provider production mode
- [ ] Deploy Railway cron service (`30 19 * * 1-5`)
- [ ] Monitor first week in production

## First Run Results (2026-02-24)

| Provider | Tokens (in/out) | Latency | Resume | Mots-cle | Impact |
|----------|----------------|---------|--------|----------|--------|
| Claude Sonnet 4.5 | 3796 / 2329 | 52s | 5603 chars | 416 chars | 1467 chars |
| GPT-4.1 | 3227 / 1301 | 24s | 3841 chars | 268 chars | 1201 chars |
| Gemini 2.5 Pro | 3591 / 1920 | 50s | 5933 chars | 275 chars | 1166 chars |

## Cost Estimate

| Phase | Monthly Cost |
|-------|-------------|
| A/B test (3 providers) | ~$3-5/month |
| Production (single provider) | < $2/month |

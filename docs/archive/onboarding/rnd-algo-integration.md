# R&D Algorithm Integration — Production Context

> **Audience**: an R&D engineer who has designed a new trading algorithm against raw exported data, and needs to ship it into the Commodities Compass production pipeline.
>
> **Prerequisites assumed**: you know your algorithm cold (math, indicators, decision logic) and you've validated it offline. You do **not** know anything about the prod system.
>
> **Goal of this doc**: give you the minimum mental model + decision tree to integrate cleanly, plus the guardrails that are non-negotiable in this codebase.

---

## Part 0 — TL;DR (read this first)

### 60-second mental model

Commodities Compass is a BI/decision tool for cocoa trading on **ICE London #7 futures** (contracts like `CAK26` = May 2026 delivery). Every weekday evening (19:00–19:30 UTC), an 8-job pipeline runs on GCP Cloud Run Jobs:

```
scrapers (Barchart, ICE, CFTC)  →  pl_contract_data_daily        (raw OHLCV + IV + stocks + COT)
press-review agent (OpenAI)     →  pl_fundamental_article         (LLM-summarised news)
meteo agent (Open-Meteo+LLM)    →  pl_weather_observation         (cocoa region weather)
                                            │
                                            ▼
compute-indicators (engine)     →  pl_derived_indicators           (27 technical indicators)
                                +  pl_indicator_daily (partial)    (scores, z-scores, composite, decision)
                                +  pl_signal_component             (per-indicator contributions)
                                            │
                                            ▼
daily-analysis (LLM, 2 calls)   →  pl_indicator_daily (LLM cols)   (DECISION / CONFIDENCE / DIRECTION / ECO / CONCLUSION)
                                            │
                                            ▼
compass-brief                   →  Google Drive .txt for NotebookLM
                                            │
                                            ▼
FastAPI + React dashboard       →  trader reads OPEN / HEDGE / MONITOR signal + gauges + audio brief
```

The output the human consumes daily: **one trading signal (OPEN / HEDGE / MONITOR), 6 gauges, a press-review tab, a weather tab, and a 2-minute audio brief.**

### What's already in place

- A pure-function **indicator engine** (`backend/app/engine/`) that replaces a legacy Google Sheets formula engine. It computes 27 technical indicators, applies a 5-day SMA smoothing layer, rolling 252-day z-score normalisation, then a configurable "power-formula" composite that maps to OPEN/HEDGE/MONITOR.
- **Algorithm parameters are stored as DB rows**, not code (table `pl_algorithm_config`). Adding a tuned variant is an INSERT, not a deploy.
- **Multiple algorithm versions can coexist** — every row in `pl_indicator_daily` is keyed on `(date, contract_id, algorithm_version_id)`. The dashboard reads the version where `is_active = true`.
- The engine is **idempotent** (UPSERT). Re-runs are safe. CLI: `poetry run compute-indicators ...`.

### Decision tree — which integration path is yours?

```
Does your algorithm need INDICATORS that don't exist yet (e.g. OBV, Ichimoku, custom feature)?
├── No  → does it just change coefficients / exponents / thresholds / decision logic?
│        ├── Yes → PATH A (lightest): new algorithm version, DB rows only, no code deploy.
│        │                            See §5.A.
│        └── No, it needs a whole new composite/decision formula
│                → PATH A with extended config (still no new indicators)
│                  OR a small code change in app/engine/composite.py if the formula
│                  shape (not just params) is different.
└── Yes → does it also need a NEW DATA SOURCE (new scraper, ML model artifact, external feed)?
         ├── No  → PATH B: new indicator(s) + new algorithm version. Code + schema migration.
         │                 See §5.B.
         └── Yes → PATH C (heaviest): new data pipeline. New scraper/agent + new tables
                                       + new Cloud Run Job + new Cloud Scheduler cron.
                                       See §5.C.
```

### Five non-negotiable rules

These come from real prod incidents. Breaking them will get caught in review. If your prototype violates one of them, refactor before the PR.

1. **Fail loud, no silent recovery.** No `try/except: pass`. No auto-retry. No provider fallback. Jobs that fail must exit non-zero so the operator notices. (Rule file: `.claude/rules/pipeline-error-handling.md`.)
2. **No hardcoded contract codes.** Never put `"CAK26"` in code. The active contract changes ~monthly when OI rolls. Always resolve via `resolve_active_code()` reading `ref_contract.is_active = TRUE`.
3. **Computed values must trace back to a computation.** Every column in an INSERT/UPDATE has to come from a function return value, not a hardcoded constant in the writer. If unknown, write `NULL`, never `0.0` as a placeholder. (Rule file: `.claude/rules/pipeline-continuity.md`.)
4. **Contract-centric.** All time-series data is keyed on `(date, contract_id)`. Never on commodity. Never on a "current month" abstraction.
5. **Config as data, not code.** Algorithm parameters belong in `pl_algorithm_config` rows so they can be tuned without a deploy. Don't define new "magic constants" in Python modules.

### Where the code lives

| What | Path |
|---|---|
| Engine (the algorithm) | `backend/app/engine/` |
| Models (table schemas) | `backend/app/models/` |
| Scrapers + agents (jobs) | `backend/scripts/<name>/` |
| API | `backend/app/api/api_v1/endpoints/` |
| Service layer | `backend/app/services/` |
| Frontend | `frontend/` |
| Migrations | `backend/alembic/versions/` |
| Infra (Terraform) | `infra/terraform/` |
| CI/CD | `.github/workflows/deploy.yml` |
| Runbooks | `docs/runbooks/` |
| Project rules | `.claude/rules/` |
| North Star (long-term schema) | `The_North_Star.md` |
| Repo overview | `CLAUDE.md` (root) |
| Engine deep dive | `backend/app/engine/README.md` |

---

## Part 1 — Product & system overview

### What Compass does

- **Asset class**: London Cocoa #7 futures (ICE Europe Financials, GBP/tonne). The active contract code follows the standard delivery-month suffix (`H` Mar, `K` May, `N` Jul, `U` Sep, `Z` Dec) plus year — e.g. `CAK26`.
- **User**: a human trader (initially Hedi). They log in via Auth0 once per day around 19:30 UTC, read the dashboard, and decide whether to open, hold, hedge, or stay out.
- **What they see**:
  - One **Signal**: `OPEN` / `HEDGE` / `MONITOR` (plus YTD performance).
  - Six **gauges**: MACROECO / MACD / VOL-OI / RSI / %K / ATR — each gauge is a colored arc (RED / ORANGE / GREEN) with a tooltip showing the underlying indicator.
  - A **press-review** card (Technique / Fondamentaux / Synthèse tabs) — French summaries generated by `o4-mini` from 6 news sources.
  - A **weather** card (campaign health bars, market impact).
  - A **price chart** (Recharts) with metric/days selectors.
  - An **audio brief** (~2 min) — generated by NotebookLM offline from a `.txt` dropped in Google Drive by the `compass-brief` job.

### Stack at a glance

| Layer | Tech |
|---|---|
| Backend | Python 3.11, FastAPI (async), SQLAlchemy 2 async + sync, Pydantic v2 |
| DB | PostgreSQL 15 on GCP Cloud SQL (private IP) + Redis (rate-limit) |
| Engine | pure-function pipeline using `pandas` + `numpy` |
| ML/LLM agents | OpenAI (`o4-mini`, `gpt-4.1`, `gpt-4-turbo`), Anthropic (testing), Google Gemini (testing) |
| Frontend | React 19 + TypeScript strict, Vite, TanStack Query, Tailwind + shadcn/ui, Recharts |
| Auth | Auth0 SPA, JWT RS256, JWKS cached 6h |
| Infra | GCP Cloud Run (services + jobs), Cloud Scheduler, Cloud SQL, VPC connector, Workload Identity Federation, Secret Manager |
| IaC | Terraform (`infra/terraform/`) |
| CI/CD | GitHub Actions (`.github/workflows/`) |
| Observability | Sentry (errors + traces 20%), Cloud Run logs |

### Repository layout (just enough to navigate)

```
commodities-compass/
├── backend/
│   ├── app/
│   │   ├── main.py                       FastAPI entry
│   │   ├── core/{config,auth,database,security,rate_limit,sentry}.py
│   │   ├── api/api_v1/endpoints/         HTTP layer (thin)
│   │   ├── services/                     business logic
│   │   ├── models/                       SQLAlchemy ORM (pipeline.py, signal.py, reference.py, ...)
│   │   ├── schemas/                      Pydantic request/response
│   │   ├── utils/                        contract_resolver.py, date_utils.py
│   │   └── engine/                       indicator engine — see §4
│   ├── scripts/
│   │   ├── barchart_scraper/             OHLCV from Barchart
│   │   ├── ice_stocks_scraper/           ICE certified stocks
│   │   ├── cftc_scraper/                 CFTC COT commercial net
│   │   ├── press_review_agent/           LLM press review
│   │   ├── meteo_agent/                  Open-Meteo + LLM weather
│   │   ├── daily_analysis/               2-step LLM scoring
│   │   ├── compass_brief/                .txt brief for NotebookLM
│   │   └── db/                           shared DB helpers (should_skip_non_trading_day, etc.)
│   ├── alembic/versions/                 idempotent migrations
│   ├── tests/                            pytest
│   ├── Dockerfile                        app image (~200MB)
│   ├── Dockerfile.jobs                   jobs image with Playwright (~1GB)
│   └── pyproject.toml                    poetry scripts entrypoints
├── frontend/                             React + Vite
├── infra/terraform/                      Cloud SQL, scheduler, IAM, VPC, LB, secrets
├── .github/workflows/deploy.yml          CI/CD
├── docs/
│   ├── runbooks/                         operational SOPs
│   └── onboarding/                       this folder
├── .claude/rules/                        project rules (must read)
├── CLAUDE.md                             repo-level architecture overview
└── The_North_Star.md                     long-term schema (not yet implemented)
```

---

## Part 2 — The daily pipeline (8 crons)

### Schedule (UTC, weekdays only)

Source of truth: `infra/terraform/scheduler.tf`. Cloud Scheduler lives in `europe-west1` (Belgium) because `europe-west9` (Paris) doesn't support it; the actual jobs execute in `europe-west9`.

| Cron (UTC) | Job name | Memory | Writes to |
|---|---|---|---|
| `0 19 * * 1-5` | `cc-barchart-scraper` | 2Gi | `pl_contract_data_daily` (OHLCV + IV + `display_date`) |
| `0 19 * * 1-5` | `cc-meteo-agent` | 1Gi | `pl_weather_observation` |
| `5 19 * * 1-5` | `cc-ice-stocks-scraper` | 512Mi | `pl_contract_data_daily.stock_us` (UPDATE on existing row) |
| `5 19 * * 1-5` | `cc-cftc-scraper` | 512Mi | `pl_contract_data_daily.com_net_us` (UPDATE) |
| `5 19 * * 1-5` | `cc-press-review-agent` | 1Gi | `pl_fundamental_article` |
| `15 19 * * 1-5` | `cc-compute-indicators` | 1Gi | `pl_derived_indicators`, `pl_indicator_daily` (engine cols), `pl_signal_component` |
| `20 19 * * 1-5` | `cc-daily-analysis` | 1Gi | `pl_indicator_daily` (`macroeco_bonus`, `decision`, `confidence`, `direction`, `eco`, `conclusion`) |
| `30 19 * * 1-5` | `cc-compass-brief` | 1Gi | Google Drive `.txt` file |

All jobs run as `poetry run <script>` inside the same image (`backend/Dockerfile.jobs`). The job's command is its only Cloud Run argument:

```bash
deploy_job cc-compute-indicators 1Gi "compute-indicators,--all-contracts,--all-versions"
```

### Dependency graph

```
                                  pl_contract_data_daily (date, contract_id)
        ┌───────────────────────────────┴────────────────────────┐
        │                       │                                │
   barchart (OHLCV+IV)    ice (stock_us)                cftc (com_net_us)
                                │
                  press-review ─┤   meteo ─── pl_weather_observation
                                │   (independent of barchart)
                                ▼
                      compute-indicators ────────► pl_derived_indicators
                                │                  pl_indicator_daily (partial)
                                │                  pl_signal_component
                                ▼
                      daily-analysis (LLM) ───────► pl_indicator_daily (decision cols)
                                │
                                ▼
                      compass-brief ──────────────► Google Drive (.txt)
```

`daily-analysis` reads from `pl_contract_data_daily`, `pl_derived_indicators`, `pl_indicator_daily`, `pl_fundamental_article`, `pl_weather_observation` — and writes back to `pl_indicator_daily` (the `macroeco_bonus`, plus the LLM decision fields).

Note the cyclic-looking pattern: `compute-indicators` produces `pl_indicator_daily` rows (without `macroeco_bonus`), then `daily-analysis` updates them with `macroeco_bonus`. The `macroeco_bonus` value is consumed by the **next day's** `compute-indicators` run via the SQL JOIN in `runner.load_all_market_data()`. So macroeco is a 1-day-lagged input to the composite. No circular write.

### When things break

The pipeline is **fail-loud, no auto-retry, no provider fallback**. If a job fails, downstream consumers (`daily-analysis`, `compass-brief`) MAY degrade gracefully on missing input — but the failing producer itself stops. The operator (you / Hedi) reads logs, fixes root cause, manually relaunches:

```bash
gcloud run jobs execute cc-<job> --region=europe-west9 --project=cacaooo
```

For diagnostic flowcharts, see `docs/runbooks/pipeline-failure-recovery.md`.

---

## Part 3 — The data model (the contract you're integrating with)

> Everything below is the actual current schema. Source: `backend/app/models/`. Bring this section up before writing your migrations / queries.

### Date semantics (critical — get this right)

There are **two date columns** on `pl_contract_data_daily`:

- **`date`** = the **session date** = the day the market actually traded. **Immutable. Source of truth.** All indicator computations, normalisation windows, momentum lookbacks use this.
- **`display_date`** = `next_trading_day(date)` = the day the user first sees that row on the dashboard. **Dashboard-only.** Computed by the barchart scraper. NULL on pre-calendar historical rows.

All other tables (`pl_derived_indicators`, `pl_indicator_daily`, `pl_signal_component`, `pl_fundamental_article`, `pl_weather_observation`) use `date` = session date.

**Rule**: in your code, always work in session dates. The dashboard layer alone translates between them.

### The contract model

```python
# backend/app/models/reference.py
class RefContract(Base):
    __tablename__ = "ref_contract"

    id:              uuid.UUID  PK
    commodity_id:    uuid.UUID  FK -> ref_commodity.id
    code:            str(20)    UNIQUE   # e.g. "CAK26"
    contract_month:  str(10)              # e.g. "2026-05"
    expiry_date:     date | NULL
    is_active:       bool       NOT NULL  # exactly one row is_active=TRUE per commodity
    created_at:      timestamp
```

**Contract rolls**. Approximately monthly, OI shifts from the front-month to the next delivery month (e.g. `CAK26` → `CAN26`). The roll procedure (manual, ~5 minutes):

```bash
# Against GCP via IAP bastion tunnel — see §6
poetry run roll-contract CAN26
# → sets old contract is_active=FALSE, new contract is_active=TRUE
# → scrapers auto-detect on next run (they read ref_contract.is_active=TRUE)

# Backfill new contract data + recompute indicators for all versions
gcloud run jobs execute cc-barchart-scraper      # populate new contract
poetry run compute-indicators --all-contracts --full --all-versions
```

Full procedure with rollback steps: `docs/runbooks/contract-roll-procedure.md`.

**Implication for your code**: anything that looks up "today's market data" must resolve the contract by `is_active`, not by a hardcoded code. Use the helper:

```python
# backend/app/utils/contract_resolver.py
from app.utils.contract_resolver import resolve_active_code, resolve_active_contract_id
code = resolve_active_code(session)            # → "CAK26"
contract_id = resolve_active_contract_id(session)  # → uuid.UUID
```

### Raw market data — `pl_contract_data_daily`

```python
# backend/app/models/pipeline.py
class PlContractDataDaily(Base):
    __tablename__ = "pl_contract_data_daily"

    id:                  uuid.UUID  PK
    date:                date       NOT NULL          # session date
    contract_id:         uuid.UUID  FK -> ref_contract.id   NOT NULL

    open, high, low, close: Decimal(15,6) | NULL
    volume:              int        | NULL            # raw contract count
    oi:                  int        | NULL            # open interest

    implied_volatility:  Decimal(15,6) | NULL         # decimal, e.g. 0.5538 = 55.38%
    stock_us:            Decimal(15,6) | NULL         # ICE US certified stocks (tonnes)
    com_net_us:          Decimal(15,6) | NULL         # CFTC commercial net position

    display_date:        date       | NULL            # dashboard-only
    created_at:          timestamp

    UNIQUE (date, contract_id)  -- uq_contract_data_daily
    INDEX  (date)
    INDEX  (display_date)
```

Writer responsibilities:
- `barchart_scraper` writes OHLCV+IV+`display_date` (INSERT).
- `ice_stocks_scraper` writes `stock_us` (UPDATE on the existing row).
- `cftc_scraper` writes `com_net_us` (UPDATE).

Note: ICE and CFTC scrapers depend on the Barchart row existing first (hence the 5-minute lag in the schedule). They fail loud if the row is missing.

### Derived indicators — `pl_derived_indicators`

The 27 columns written by the engine's `registry.compute_all()` step (raw OHLCV → technicals, no smoothing yet).

```python
class PlDerivedIndicators(Base):
    __tablename__ = "pl_derived_indicators"

    id, date, contract_id  (PK / FK as above)

    # Pivots (classical)
    r3, r2, r1, pivot, s1, s2, s3: Decimal(15,6) | NULL

    # Moving averages + MACD
    ema12, ema26, macd, macd_signal: Decimal(15,6) | NULL

    # RSI (Wilder) + Stochastic
    rsi_14d, stochastic_k_14, stochastic_d_14: Decimal(15,6) | NULL

    # Volatility
    atr, atr_14d: Decimal(15,6) | NULL

    # Bollinger (symmetric SMA20 ± 2·STDEV20)
    bollinger, bollinger_upper, bollinger_lower, bollinger_width: Decimal(15,6) | NULL

    # Ratios + RSI internals
    close_pivot_ratio, volume_oi_ratio: Decimal(15,6) | NULL
    gain_14d, loss_14d, rs:             Decimal(15,6) | NULL

    # Daily return
    daily_return: Decimal(15,6) | NULL

    UNIQUE (date, contract_id)  -- uq_derived_indicators
```

If your algorithm needs a new technical indicator, you'll add a column here (Alembic migration) and a class in `app/engine/indicators/`. See §5.B.

### Scores, normalisation, composite, decision — `pl_indicator_daily`

This is the multi-version table. **Each `(date, contract_id, algorithm_version_id)` triple gets its own row.**

```python
class PlIndicatorDaily(Base):
    __tablename__ = "pl_indicator_daily"

    id, date, contract_id, algorithm_version_id  (PK + FKs)

    # Raw scores (post-smoothing, pre-normalisation) — written by engine
    rsi_score, macd_score, stochastic_score, atr_score: Decimal(15,6) | NULL
    close_pivot, volume_oi:                              Decimal(15,6) | NULL

    # Normalized z-scores (rolling 252d) — written by engine
    rsi_norm, macd_norm, stoch_k_norm, atr_norm:          Decimal(15,6) | NULL
    close_pivot_norm, vol_oi_norm:                        Decimal(15,6) | NULL

    # Composites — written by engine
    indicator_value:  Decimal(15,6) | NULL    # base score (power formula with momentum=0)
    momentum:         Decimal(15,6) | NULL    # ±momentum_threshold (direction of indicator_value)
    macroeco_bonus:   Decimal(15,6) | NULL    # written by daily-analysis (LLM)
    macroeco_score:   Decimal(15,6) | NULL    # = 1.0 + macroeco_bonus (engine)
    final_indicator:  Decimal(15,6) | NULL    # full power formula score (the decision input)

    # Decision — written initially by engine (rule-based on final_indicator),
    # overwritten by daily-analysis LLM call #2 with LLM judgement + rationale
    decision:    str(50)  | NULL  -- "OPEN" / "HEDGE" / "MONITOR"
    confidence:  Decimal(5,2) | NULL
    direction:   str(50)  | NULL  -- "LONG" / "SHORT" / "NEUTRAL"
    eco:         text     | NULL
    conclusion:  text     | NULL

    UNIQUE (date, contract_id, algorithm_version_id)  -- uq_indicator_daily
```

**Important**: `decision` here ends up being the LLM-overwritten version, not the pure-engine rule output. If you want the raw rule-based decision, recompute it from `final_indicator` vs thresholds. The dashboard reads `decision` as the final answer.

### Per-indicator decomposition — `pl_signal_component`

Why a HEDGE on Feb 10? This table answers it. Eight rows per `(date, contract_id, algorithm_version_id)`, one per input indicator. Already used by debug tooling and the planned explainability UI.

```python
class PlSignalComponent(Base):
    __tablename__ = "pl_signal_component"

    id, date, contract_id, algorithm_version_id  (PK + FKs)
    indicator_name:        str(50) NOT NULL     # "rsi" | "macd" | "stochastic" | "atr"
                                                # | "close_pivot" | "volume_oi"
                                                # | "momentum" | "macroeco"
    raw_value:             Decimal(15,6) | NULL  # pre-normalisation score
    normalized_value:      Decimal(15,6) | NULL  # z-score
    weighted_contribution: Decimal(15,6) | NULL  # coeff × sign(norm) × |norm|^exp
    created_at:            timestamp
```

If your algorithm changes the list of inputs (drops one, adds one), update both the engine writer (`app/engine/db_writer.py:_SIGNAL_COMPONENTS`) and the indicator_name values you write here.

### Algorithm versioning — `pl_algorithm_version` + `pl_algorithm_config`

This is **the core integration surface for Path A**.

```python
class PlAlgorithmVersion(Base):
    __tablename__ = "pl_algorithm_version"

    id:               uuid.UUID  PK
    name:             str(100)   NOT NULL          # e.g. "legacy", "v2_power_formula"
    version:          str(50)    NOT NULL          # e.g. "1.0.0", "1.0.1"
    horizon:          str(50)    NOT NULL  default "short_term"
    is_active:        bool       NOT NULL  default FALSE   # dashboard reads is_active=TRUE
    compute_enabled:  bool       NOT NULL  default FALSE   # nightly cron computes if TRUE
    description:      text       | NULL
    created_at:       timestamp

    UNIQUE (name, version)  -- uq_algorithm_version
```

```python
class PlAlgorithmConfig(Base):
    __tablename__ = "pl_algorithm_config"

    id:                    uuid.UUID  PK
    algorithm_version_id:  uuid.UUID  FK -> pl_algorithm_version.id  NOT NULL
    parameter_name:        str(100)   NOT NULL    # e.g. "k", "a", "open_threshold"
    value:                 text       NOT NULL    # stringified, parsed to float/int by AlgorithmConfig.from_db_rows
    description:           text       | NULL
    created_at:            timestamp

    UNIQUE (algorithm_version_id, parameter_name)  -- uq_algorithm_config_param
```

**`is_active` vs `compute_enabled`** — two independent flags:
- `compute_enabled=TRUE` → nightly `compute-indicators --all-versions` includes this version in its run, writing rows to `pl_indicator_daily` and `pl_signal_component` keyed by this version_id.
- `is_active=TRUE` → the dashboard reads this version as the user-visible signal. **Exactly one version per logical "algorithm" should be active** (currently enforced by convention, not constraint).

This means you can run your new version in parallel (compute_enabled=TRUE, is_active=FALSE) for weeks, comparing it to legacy on the same dates, before flipping it live.

Required parameter names (from `AlgorithmConfig.from_db_rows()` in `backend/app/engine/types.py`):

```
k, a, b, c, d, e, f, g, h, i, j, l, m, n, o, p, q,
open_threshold, hedge_threshold,
momentum_threshold (default "0.2"),
smoothing_window (default "5")
```

Mapping coefficient/exponent pairs to inputs:

| Indicator | Coefficient | Exponent |
|---|---|---|
| RSI | `a` | `b` |
| MACD | `c` | `d` |
| Stochastic %K | `e` | `f` |
| ATR | `g` | `h` |
| Close/Pivot | `i` | `j` |
| Volume/OI | `l` | `m` (note: `k` is the constant offset, so `l` not `k`) |
| Momentum | `n` | `o` |
| Macroeco bonus | `p` | `q` |

### Other tables you'll touch

- `pl_fundamental_article` — multi-provider press review. `is_active` flag picks the "production" provider (currently OpenAI o4-mini). PK: `(date, llm_provider)`. Provider-switch runbook: `docs/runbooks/press-review-provider-switch.md`.
- `pl_weather_observation` — one row per day (UNIQUE on `date`). Region is informational; the 6 cocoa-belt locations are aggregated into one daily row with a `diagnostics` JSONB.
- `pl_seasonal_score` — campaign-memory weather scores, separate cadence (computed at season transitions). Not in the daily critical path.
- `pl_article_segment` — populated daily by `press_review_agent/db_writer.py:write_theme_sentiments()` (cron `5 19 * * 1-5`, OpenAI o4-mini, `extraction_version="inline_v1"`). ~4-8 rows/day, one per theme extracted from the LLM prompt. **Consumed in shadow mode** by `compute_sentiment_features` (not in Cloud Run cron — manual only) and by the dashboard (not yet wired). The model docstring claiming "MODEL-ONLY — extraction lives on feat/pattern-extractor branch" is **stale** (branch was never merged; inline extraction is the prod path). The Campaign 5 ensemble (in progress) will be the first consumer wired to the composite.
- `pl_sentiment_feature` — **shadow table**. Computed daily but not yet wired into the composite. Will activate around Oct 2026 when sample size is sufficient (n > 250 per theme). Backfill 10y via GDELT planned in [docs/user-stories/P1-press-review-backfill-10y.md](../user-stories/P1-press-review-backfill-10y.md) to accelerate activation. Don't depend on them; don't break them.

### Tables you must **not** touch

Legacy tables from the Google Sheets era still exist in prod for safety but **are not read by any production code**: `technicals`, `indicator`, `market_research`, `weather_data`. Will be dropped in a future migration. Do not query them. Do not write to them.

---

## Part 4 — The indicator engine (`backend/app/engine/`)

Understanding this is mandatory before you write any new algorithm code. Full reference: `backend/app/engine/README.md`.

### Pipeline shape

```
raw OHLCV (pl_contract_data_daily)        ← runner.load_all_market_data() loads full series
   │
   │   IndicatorRegistry.compute_all()    ← topological sort on depends_on → outputs
   ▼
27 derived indicators in DataFrame
   │
   │   smoothing.compute_raw_scores()      ← 5-day SMA on 5 cols + 1 direct (close_pivot)
   ▼
6 raw score columns (rsi_score, macd_score, stochastic_score, atr_score, close_pivot, volume_oi)
   │
   │   normalization.normalize_scores()    ← rolling 252-day z-score, clipped ±10
   ▼
6 normalized columns (rsi_norm, macd_norm, stoch_k_norm, atr_norm, close_pivot_norm, vol_oi_norm)
   │
   │   composite.compute_signals(config)   ← power formula, two-pass momentum, decision
   ▼
indicator_value (base score), momentum, final_indicator, decision
```

All functions are pure (no I/O, no DB, no mutation). Input DataFrames are always copied. The DB layer (`db_writer.py`) is separate and writes per `(date, contract_id, algorithm_version_id)` upsert.

### The `Indicator` protocol

```python
# backend/app/engine/indicators/base.py
from typing import Protocol, runtime_checkable
import pandas as pd

@runtime_checkable
class Indicator(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def outputs(self) -> tuple[str, ...]: ...
    @property
    def depends_on(self) -> tuple[str, ...]: ...
    @property
    def warmup(self) -> int: ...

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Pure function: returns a NEW DataFrame with output columns added. Never mutate input."""
        ...
```

Example — Wilder's RSI (`backend/app/engine/indicators/rsi.py`):

```python
class WilderRSI:
    name = "wilder_rsi"
    outputs = ("rsi_14d", "gain_14d", "loss_14d", "rs")
    depends_on = ("close",)
    warmup = 15  # 14 deltas → need 15 closes

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        # ... pure-numpy Wilder's smoothing ...
        result["rsi_14d"] = rsi
        result["gain_14d"] = gain_out
        result["loss_14d"] = loss_out
        result["rs"] = rs_out
        return result
```

To register, append the class instance to `ALL_INDICATORS` in `app/engine/indicators/__init__.py`. The registry topologically sorts indicators by `depends_on` → `outputs`. Circular dependencies raise at startup.

### Normalisation — rolling z-score (the look-ahead-bias fix)

```python
# backend/app/engine/normalization.py
DEFAULT_WINDOW = 252        # ~1 trading year
DEFAULT_OUTLIER_CAP = 10.0

z = (x - rolling_mean(x, 252)) / rolling_std(x, 252, ddof=1)
z = z.clip(-10, 10)
# min_periods = max(window // 2, 20) before producing values
```

This replaced the legacy full-history `AVERAGE(B:B) / STDEV(B:B)` (look-ahead bias). **If your algorithm normalises features, use this rolling pattern or justify deviation explicitly.** Aligns with North Star principle "rolling normalization".

### Composite — the power formula

```python
# backend/app/engine/composite.py
SCORE = k + Σ (coefficient × sign(input) × |input|^exponent)
       over 8 inputs: RSI, MACD, Stochastic, ATR, Close/Pivot, Vol/OI, Momentum, Macroeco

decision = OPEN     if SCORE >= open_threshold
         = HEDGE    if SCORE <= hedge_threshold
         = MONITOR  otherwise
```

**Two-pass momentum** to avoid circular dependency on its own previous output:

1. `base_score[t]` = power formula with momentum input = 0 (stored as `indicator_value`)
2. `momentum[t]` = `+momentum_threshold` if `base_score[t] > base_score[t-1]` else `-momentum_threshold`
3. `final_indicator[t]` = power formula with real momentum (stored as `final_indicator`, used for decision)

Hardcoded fallback `LEGACY_V1` in `types.py` is the v1.0.0 production parameters — only used if the DB config is empty. **Never edit `LEGACY_V1`.** Make a new version row.

### CLI — `poetry run compute-indicators`

Source: `backend/app/engine/runner.py`. Available flags:

| Flag | Purpose |
|---|---|
| `--contract CAK26` (or `--all-contracts`) | scope; mutually exclusive, one is required |
| `--algorithm legacy` | algorithm name (default `legacy`) |
| `--algorithm-version 1.0.1` | specific version; if omitted, uses `is_active=TRUE` for the given name |
| `--all-versions` | run all rows in `pl_algorithm_version` with `compute_enabled=TRUE` (nightly mode) |
| `--full` | upsert all rows; default is **incremental** (compute full series, write only new rows) |
| `--dry-run` | compute + log summary, no DB write |
| `--window 252` | normalisation window (default 252) |
| `--force` | run even on non-trading days (for backfills/debugging) |

Examples:

```bash
# Default nightly run (matches what the prod cron does)
poetry run compute-indicators --all-contracts --all-versions

# Backfill / version switch: rewrite all rows for one version
poetry run compute-indicators --all-contracts --full --algorithm legacy --algorithm-version 1.0.1

# Quick experiment: dry run for one contract
poetry run compute-indicators --contract CAK26 --algorithm my_algo --algorithm-version 0.1.0 --dry-run

# Custom normalisation window experiment
poetry run compute-indicators --all-contracts --window 365 --dry-run
```

### How `--all-contracts` handles rolls

Reading `runner.load_all_market_data()`:

```sql
WITH market AS (
    SELECT DISTINCT ON (d.date)
        d.date, d.close, d.high, d.low, d.volume, d.oi,
        d.implied_volatility, d.stock_us, d.com_net_us,
        d.contract_id, c.code AS contract_code
    FROM pl_contract_data_daily d
    JOIN ref_contract c ON d.contract_id = c.id
    ORDER BY d.date, d.oi DESC NULLS LAST
)
SELECT m.*, i.macroeco_bonus
FROM market m
LEFT JOIN pl_indicator_daily i ON m.date = i.date AND m.contract_id = i.contract_id
ORDER BY m.date ASC
```

One date → one row, picked by highest OI (front-month). Indicators are computed on the continuous front-month series (matches the Sheets behaviour). Each row's original `contract_id` is preserved so writes go to the correct contract.

This is the **only** correct way to handle cross-contract continuity — never write your own version that lazily filters by current active contract; you'll get gaps across rolls.

---

## Part 5 — Three integration paths

Pick the lightest path that actually fits your algorithm. Don't reach for Path C if Path A works.

### Path A — new algorithm version (no code deploy)

**Use when**: your algorithm uses the same inputs (RSI, MACD, Stochastic, ATR, Close/Pivot, Vol/OI, Momentum, Macroeco) but different coefficients, exponents, decision thresholds, smoothing window, or momentum threshold.

**Steps**:

1. INSERT version row + config rows in prod DB (via bastion tunnel — see §6). Wrap in a transaction.

```sql
BEGIN;

INSERT INTO pl_algorithm_version (id, name, version, horizon, is_active, compute_enabled, description)
VALUES (gen_random_uuid(), 'champion_v2', '1.0.0', 'short_term',
        false, true,
        'R&D candidate — backtested 2024-2025 Sharpe 1.8, max DD 12%');

INSERT INTO pl_algorithm_config (id, algorithm_version_id, parameter_name, value, description)
SELECT gen_random_uuid(), v.id, kv.k, kv.v, NULL
FROM pl_algorithm_version v,
     (VALUES
        ('k','-1.20'),
        ('a','-1.30'), ('b','1.80'),
        ('c','0.50'),  ('d','0.70'),
        ('e','-2.50'), ('f','1.00'),
        ('g','1.204'), ('h','0.50'),
        ('i','-0.40'), ('j','1.751'),
        ('l','4.98'),  ('m','1.20'),
        ('n','-1.30'), ('o','0.515'),
        ('p','-0.50'), ('q','1.98'),
        ('open_threshold','1.50'),
        ('hedge_threshold','-1.50'),
        ('momentum_threshold','0.20'),
        ('smoothing_window','5')
     ) AS kv(k, v)
WHERE v.name = 'champion_v2' AND v.version = '1.0.0';

COMMIT;
```

2. Backfill historical signals for the new version (full series so the rolling z-score warms up):

```bash
# Locally against a synced DB first (see §6 for sync), then in prod
poetry run compute-indicators --all-contracts --full \
  --algorithm champion_v2 --algorithm-version 1.0.0
```

3. Validate offline: compare your new version's rows in `pl_indicator_daily` against the current active version across (a) decision distribution, (b) decision agreement rate, (c) PnL on historical price moves. Use the seasonal-score backtest tool as a reference (`docs/backtests/`).

4. Run in parallel (compute_enabled=TRUE, is_active=FALSE) for at least 2-4 weeks. The nightly cron picks it up automatically because `compute-indicators` is deployed with `--all-versions`.

5. Promote: flip `is_active=TRUE` on the new version and `is_active=FALSE` on the previous one, in a single transaction. The dashboard will read the new version on the next API call (no cache invalidation needed — TanStack Query has 24h stale time but the data is fresh by then).

**Risk surface**: only DB rows. Reversible with one UPDATE. No code review, no deploy, no infra change.

### Path B — new indicator(s) + new composite

**Use when**: you need a feature that doesn't exist yet (e.g. OBV, On-Balance Volume; Ichimoku; a custom volatility regime; a feature derived from existing tables but with new logic).

**Steps**:

1. **Implement the indicator** as a pure class in `backend/app/engine/indicators/<name>.py`. Follow the `Indicator` protocol exactly. Look at `rsi.py`, `macd.py`, `stochastic.py` as references. Use numpy where possible (the engine processes ~10 years × ~250 days = ~2500 rows, performance is not critical but vectorise where natural).

2. **Register** in `backend/app/engine/indicators/__init__.py` — append an instance of your class to `ALL_INDICATORS`. Topological sort handles ordering from `depends_on` automatically.

3. **Alembic migration** to add the new column(s) to `pl_derived_indicators`. Pattern (idempotent — required for GCP re-apply safety):

```python
# backend/alembic/versions/<timestamp>_add_obv_indicator.py
"""add OBV indicator to pl_derived_indicators

Revision ID: <rev>
Revises: <down_rev>
"""
from alembic import op
import sqlalchemy as sa

revision = "<rev>"
down_revision = "<down_rev>"

def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    res = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name=:t AND column_name=:c"
    ), {"t": table, "c": column}).fetchone()
    return res is not None

def upgrade() -> None:
    if not _has_column("pl_derived_indicators", "obv"):
        op.add_column("pl_derived_indicators", sa.Column("obv", sa.DECIMAL(15, 6), nullable=True))

def downgrade() -> None:
    if _has_column("pl_derived_indicators", "obv"):
        op.drop_column("pl_derived_indicators", "obv")
```

4. **Update `DERIVED_COLS`** in `backend/app/engine/types.py` so the writer knows to persist the new column. (`db_writer.py` reads from this constant.)

5. **If your indicator becomes a composite input** (i.e. you want it in the power formula, not just stored alongside), add a parallel scoring/normalisation step in `app/engine/smoothing.py` and `app/engine/normalization.py`, extend `SCORE_COLS` / `NORM_COLS`, then expand the composite formula. **Crucially**: the power formula has 8 inputs hardcoded today. Adding a 9th means changing `compute_score`/`_vectorized_score` in `composite.py`, extending `AlgorithmConfig` with new coefficient/exponent fields, and updating `_SIGNAL_COMPONENTS` in `db_writer.py`. Coordinate with Hedi before doing this — it's a real change, not a config flip.

6. **Tests** — `backend/tests/engine/test_<your_indicator>.py`. Table-driven, edge cases (NaN handling, warmup boundary, multi-contract continuity). Aim for 80%+ coverage on the new code.

```python
import pytest, pandas as pd, numpy as np
from app.engine.indicators.obv import OBV

@pytest.mark.unit
def test_obv_known_values():
    df = pd.DataFrame({
        "date":   pd.date_range("2026-01-01", periods=5),
        "close":  [10, 11, 11, 10, 12],
        "volume": [100, 150, 120, 80, 200],
    })
    out = OBV().compute(df)
    # expected OBV from first principles
    assert out["obv"].iloc[-1] == pytest.approx(370)
```

7. **Run Path A** on top of your new indicator: create a `pl_algorithm_version` row that uses the extended config (with new coeff/exp params for your indicator).

8. **Backfill**: `poetry run compute-indicators --all-contracts --full --algorithm <name> --version <v>`. This populates `pl_derived_indicators.<new_col>` (your indicator) for historical dates and writes the new version's `pl_indicator_daily` rows.

**Risk surface**: code change → review → CI → deploy. Migration is idempotent and reversible. The new column on `pl_derived_indicators` is nullable, so existing readers don't break.

### Path C — new data source / new pipeline

**Use when**: your algorithm needs an input that doesn't exist anywhere in the pipeline (e.g. shipping AIS data, satellite NDVI from Sentinel, broker positioning leaked twice a week, an ML model with retrained artifacts on a separate cadence).

**Steps** (in order):

1. **New scraper or agent**. Create `backend/scripts/<name>/` with:
   - `__init__.py`
   - `<name>.py` — the scraper/agent logic, fail-loud, structured logging, Sentry tag (`service=<name>`).
   - `cli.py` — `argparse` entrypoint that respects `--dry-run`. Use `from scripts.db import should_skip_non_trading_day` to no-op on weekends if applicable.
   - Add to `backend/pyproject.toml` `[tool.poetry.scripts]`: `<name> = "scripts.<name>.cli:main"`.
   - Tests in `backend/tests/scripts/<name>/`.

2. **New table** in `backend/app/models/pipeline.py` (or `audit.py` if it's audit-style append-only data). Prefix: `pl_` for pipeline output, `ref_` for reference data, `aud_` for audit/event log. Use `(date, ...)` keying, UNIQUE constraints, indexes on `date`. Alembic migration with `_has_column`/`if_not_exists=True` patterns.

3. **New Cloud Run Job entry** in `.github/workflows/deploy.yml`, in the `deploy-jobs` step:

```bash
deploy_job cc-<name>  1Gi  "<name>[,--arg1,--arg2]"
```

Memory: 512Mi for pure-Python jobs, 1Gi for LLM agents, 2Gi for Playwright-based scrapers. The image is shared (`Dockerfile.jobs`); your script just needs to be installed as a poetry script.

4. **New Cloud Scheduler cron** in `infra/terraform/scheduler.tf` `cron_jobs` map:

```hcl
<name> = {
  description = "Short description of what it does"
  schedule    = "<minute> <hour> * * 1-5"   # UTC, weekdays
}
```

Pick a slot that respects the dependency graph. Don't run before its upstream producers. Don't run during the 15-25 window if it would slow down `compute-indicators` (shared DB connections).

5. **Apply infra**: open a PR. Once approved, run `terraform plan` / `apply` against prod (Hedi does this; you don't).

6. **Update `CLAUDE.md`** — the "Pipeline Schedule" section. This is the canonical operational reference.

7. **Add a runbook** in `docs/runbooks/<your-pipeline>-recovery.md` — at minimum: how to manually re-run, common failure modes, what's safe to re-run vs not.

8. **Wire it into the engine** (Path B) if your new data feeds the composite. Or directly into `daily-analysis` if it's just LLM context. Or directly into the dashboard if it's standalone presentation.

**Risk surface**: largest. Code + schema + infra + ops. Plan for at least one prod incident in the first month and pre-write the runbook for it.

---

## Part 6 — Local development workflow

### One-time setup

```bash
# Prereqs: Node 18+, pnpm, Poetry, Docker, gcloud SDK
# Clone repo, then:
scripts/setup-dev.sh                 # installs deps, creates .env from .env.example

# Or manually:
pnpm install:all                     # root + backend + frontend
cd backend && poetry install
cd ../frontend && pnpm install
```

Fill in `backend/.env` (a template lives in `backend/.env.example`). For local-only experimentation you need at minimum:

```bash
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5433/commodities_compass
DATABASE_SYNC_URL=postgresql://postgres:password@localhost:5433/commodities_compass
# Optional: only if your work touches LLM agents
OPENAI_API_KEY=...
SENTRY_DSN=                          # leave empty locally to silence Sentry
```

### Running the local stack

```bash
pnpm db:up                           # PostgreSQL 5433 + Redis 6380 (Docker)
poetry run alembic upgrade head      # apply all migrations
pnpm dev                             # backend (8000) + frontend (5173)
```

The local DB is empty by default. Get realistic data via the sync command below.

### Syncing prod data locally

Cloud SQL is **private IP only**. You can't reach it from your laptop directly. Use the IAP bastion tunnel (one-time per session):

```bash
# Open the tunnel in a separate terminal (leave running)
gcloud compute ssh cc-bastion \
  --zone=europe-west9-a \
  --tunnel-through-iap \
  --project=cacaooo \
  -- -N -L 5434:10.119.160.3:5432

# Now in another terminal, copy prod tables to local
poetry run python scripts/sync_from_gcp.py            # all pl_* / ref_* / aud_* tables
poetry run python scripts/sync_from_gcp.py --dry-run  # see what would be copied

# Or query prod directly with psql / DBeaver
psql -h 127.0.0.1 -p 5434 -U cc_app -d commodities_compass
```

`cc_app` is a read-only user (SELECT on `pl_*`, `ref_*`, `aud_*`). For writes you'd use the app service account — but as an R&D engineer, **always work read-only against prod** and write to local. Full runbook: `docs/runbooks/db-sync-from-gcp.md`.

### Running the engine locally

```bash
# Quick experiment, no DB write
poetry run compute-indicators --all-contracts --dry-run

# Run your new algorithm version end-to-end on local data
poetry run compute-indicators --all-contracts --full \
  --algorithm my_algo --algorithm-version 0.1.0

# Compare to legacy
poetry run compute-indicators --all-contracts --full --algorithm legacy --algorithm-version 1.0.1
# then SQL-diff pl_indicator_daily rows between the two algorithm_version_ids
```

### Tests + linting

```bash
cd backend
poetry run pytest                                       # all tests
poetry run pytest tests/engine/ -v                      # engine only
poetry run pytest --cov=app --cov-report=term-missing   # with coverage
poetry run lint                                         # ruff + pyright (pre-commit hooks)
```

Frontend (probably not needed for R&D algo work):

```bash
cd frontend
pnpm type-check
pnpm lint
```

Pre-commit hooks (Husky) run automatically: `ruff` + `pyright` (backend), `eslint --fix` + `prettier` (frontend). **Don't bypass with `--no-verify`.** If a hook fails, the underlying issue is real.

---

## Part 7 — Deployment & ops

### CI/CD

Source: `.github/workflows/deploy.yml`.

```
push to main
   │
   ├── CI workflow (lint + test, backend + frontend)
   │
   └── on CI success:
       Deploy workflow
       ├── deploy-backend  (Cloud Run service, image from backend/Dockerfile)
       ├── deploy-frontend (Cloud Run service, image from frontend/Dockerfile)
       └── deploy-jobs     (8 Cloud Run Jobs, image from backend/Dockerfile.jobs)
```

Auth: Workload Identity Federation (keyless). No SA JSON in CI. Image registry: `europe-west9-docker.pkg.dev/cacaooo/...`. Region: `europe-west9` (Paris).

### Secrets & env vars (`backend/app/core/config.py`)

| Source | Variables |
|---|---|
| Secret Manager → `--set-secrets` | `DATABASE_URL`, `DATABASE_SYNC_URL`, `GOOGLE_SHEETS_CREDENTIALS_JSON`, `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON`, `GOOGLE_DRIVE_CREDENTIALS_JSON`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `SENTRY_DSN`, and Auth0 credentials for the backend service |
| GitHub Vars → `--set-env-vars` | `GOOGLE_DRIVE_AUDIO_FOLDER_ID`, `GOOGLE_DRIVE_BRIEFS_FOLDER_ID`, region/project metadata |

If your new job needs a new secret, add it to:
1. GCP Secret Manager (manual + `infra/terraform/secrets.tf`).
2. The `SECRETS=` line in `deploy.yml` `deploy-jobs` step.
3. `backend/app/core/config.py` (Pydantic settings).

### Observability

- **Cloud Run logs** — first stop. Each job execution shows up under Cloud Run Jobs → `cc-<name>` → Executions. Python `logging` (INFO+) goes straight to stdout → Cloud Logging.
- **Sentry** — second stop. Errors are grouped by fingerprint with full traceback + breadcrumbs. Service tag distinguishes which job. Trace sample rate 20%, error rate 100%.
- **Cloud Scheduler** — job trigger history (HTTP 200/500 = trigger sent, not job result).

### Adding a new job — full checklist

1. Implement script under `backend/scripts/<name>/`.
2. Add `<name> = "scripts.<name>.cli:main"` to `pyproject.toml` `[tool.poetry.scripts]`.
3. Add `deploy_job cc-<name> <memory> "<name>"` line to `deploy.yml`.
4. Add entry to `infra/terraform/scheduler.tf` `cron_jobs` map.
5. Open PR → merge → CI deploys → terraform apply (Hedi) → first cron tick.
6. Update `CLAUDE.md` pipeline schedule.
7. Write runbook in `docs/runbooks/`.

---

## Part 8 — Non-negotiable rules

All three rule files live in `.claude/rules/`. Read them. They came from real incidents.

### Pipeline error handling — fail loud, no silent recovery

(`.claude/rules/pipeline-error-handling.md`)

- No `try/except: pass`.
- No auto-retry of LLM calls or HTTP requests beyond what the SDK does once.
- No "provider fallback" (e.g. if OpenAI fails, try Claude). If your prompt is flaky on the chosen provider, fix the prompt or the parser.
- Errors must be logged at ERROR level **and** raised so the job exits non-zero.
- Consumers (e.g. compass-brief) MAY degrade gracefully on missing input. Producers must not.
- Recovery is: diagnose from logs/Sentry → fix root cause → manually relaunch with `gcloud run jobs execute`.

### Pipeline continuity — computed values must trace

(`.claude/rules/pipeline-continuity.md`)

- Every column in an `INSERT`/`UPDATE` traces back to a function return value, not a literal in the writer.
- If a value isn't computed yet at write time, write `NULL` — not `0.0`. Zero is a valid math result and masks bugs.
- Two distinct columns (e.g. `raw_value` and `normalized_value`) must read from two distinct sources. Setting `normalized = raw` is wrong unless the value has genuinely no normalisation step (and then document why).
- Exception: metadata/identity columns (`pipeline_name`, `category`, etc.) and schema defaults are fine to literal-set.

Origin: a 2026-03-26 incident where the `daily-analysis` job computed momentum internally but the writer hardcoded `0.0`, corrupting 3 prod rows.

### North Star alignment — directional guardrails

(`.claude/rules/north-star-alignment.md`)

Long-term schema vision: contract-centric, immutable raw data, config-as-data, schema namespaces (`reference.`, `pipeline.`, `audit.`, `tenant.`), rolling normalisation, tenants subscribing to shared pipelines.

You don't need to implement the full North Star (`The_North_Star.md`) now. The rule is: **don't actively make it harder to reach.**

Concretely:
- Don't add new tables keyed on `commodity_id` instead of `contract_id`.
- Don't add tables that mutate raw data in place.
- Don't add new hardcoded constants that should be config.
- Don't add new full-history normalisation (use rolling).

### Plus

- **No hardcoded contract codes.** Use `resolve_active_code()`.
- **Use session `date`, never `display_date`** for computation.
- **Idempotent migrations** (use `_has_column` / `if_not_exists=True`).
- **Idempotent writers** (UPSERT, not blind INSERT).

---

## Part 9 — Pre-merge self-audit

Before opening a PR, run through this list. Reviewers will check it.

**Architectural**
- [ ] Active contract resolved dynamically (`resolve_active_code()` / `ref_contract.is_active`), no hardcoded `"CAK*"`.
- [ ] All time-series tables keyed on `(date, contract_id)`, not commodity.
- [ ] `date` used in computation; `display_date` only in dashboard-facing code.
- [ ] Algorithm parameters in `pl_algorithm_config`, not Python constants.

**Engine integration (Paths A/B)**
- [ ] If new indicator: implements the `Indicator` protocol; pure function; no DB I/O; new column added via Alembic migration with `_has_column` guard.
- [ ] `DERIVED_COLS` / `SCORE_COLS` / `NORM_COLS` / `_SIGNAL_COMPONENTS` updated consistently if relevant.
- [ ] New `pl_algorithm_version` + `pl_algorithm_config` rows created; values verified.
- [ ] `--dry-run` against full local history produces sane decision distribution (no all-MONITOR or all-OPEN).

**Continuity & error handling**
- [ ] Every column written in INSERT/UPDATE traces to a function return value.
- [ ] No literal `0.0` placeholder for not-yet-computed values — write `NULL`.
- [ ] No `except: pass` or silent fallback.
- [ ] Job exits non-zero on failure; ERROR-level log with structured context.

**Tests & quality**
- [ ] Unit tests, table-driven, ≥80% coverage on new code.
- [ ] Integration test hitting the local PostgreSQL (not mocks) for any new DB path.
- [ ] `poetry run lint` passes (`ruff` + `pyright`).
- [ ] `poetry run pytest` passes.
- [ ] No `print()` — use the `logging` module.
- [ ] No secrets in code; new secrets added to Secret Manager + `deploy.yml` + `config.py`.

**Path C extras**
- [ ] New job in `deploy.yml` with correct memory.
- [ ] New cron in `scheduler.tf` with dependency-respecting schedule.
- [ ] `CLAUDE.md` pipeline schedule updated.
- [ ] Runbook in `docs/runbooks/<job>-recovery.md`.

**Backfill plan (in PR description)**
- [ ] Which dates are being backfilled (start/end).
- [ ] Estimated row count and runtime.
- [ ] Rollback procedure if numbers look wrong.
- [ ] Whether the dashboard will see anything during the rollout (it shouldn't, until `is_active=TRUE`).

---

## Part 10 — Glossary & where to look next

### Glossary

| Term | Meaning |
|---|---|
| **Active contract** | The row in `ref_contract` with `is_active=TRUE`. Changes on roll. |
| **Algorithm version** | A `pl_algorithm_version` row + its `pl_algorithm_config` parameter rows. Independent variant of the composite. |
| **Composite (score)** | `final_indicator` — output of the power formula. Range typically ±5, decision thresholds at ±1.5. |
| **compute_enabled** | Flag on `pl_algorithm_version`. If TRUE, nightly cron computes this version. |
| **Contract roll** | OI shifts to next delivery month. Operationally: `poetry run roll-contract <NEW>`. |
| **display_date** | Dashboard-facing date = next trading day after session date. Stored on `pl_contract_data_daily` only. |
| **Front-month** | The contract with highest OI today. Implicit, never stored. `runner.load_all_market_data` resolves it per row. |
| **is_active** | Flag on `pl_algorithm_version` (dashboard reads). Or `ref_contract` (scrapers target). |
| **MACROECO_BONUS** | LLM-generated daily macro/weather adjustment, written by `daily-analysis`, consumed next day by `compute-indicators`. |
| **Momentum (engine)** | Two-pass: `±momentum_threshold` based on direction of yesterday's `indicator_value`. |
| **OPEN / HEDGE / MONITOR** | The three possible values of `pl_indicator_daily.decision`. |
| **Power formula** | The composite: `k + Σ (coeff × sign(x) × |x|^exp)` over 8 inputs. |
| **Session date** | The real trading day. `pl_*.date`. Source of truth. |
| **Signal component** | Per-indicator decomposition row in `pl_signal_component`. 8 per signal. |
| **z-score (rolling)** | `(x - mean(x, 252d)) / std(x, 252d)`, clipped ±10. Replaces look-ahead-biased full-history z. |

### Where to look next

- **`CLAUDE.md`** (repo root) — architecture overview, commands, environment, deployment. The single most useful file after this one.
- **`backend/app/engine/README.md`** — full engine reference, indicator-by-indicator math, list of bugs fixed vs the legacy Sheets engine.
- **`The_North_Star.md`** — long-term schema vision (43 tables, EAV, schema namespaces, tenants). Not yet implemented. Read this to understand directional pull.
- **`infra/INFRASTRUCTURE.md`** — Cloud SQL, VPC, Load Balancer, IAM, bastion details.
- **`.claude/rules/`** — three project rules quoted in §8. Quick reads, read them.

#### Runbooks (`docs/runbooks/`)

| File | When to read |
|---|---|
| `contract-roll-procedure.md` | Before / during a monthly roll |
| `db-sync-from-gcp.md` | First time syncing prod data locally |
| `multi-algorithm-parallel-run.md` | Running multiple algorithm versions in parallel |
| `pipeline-failure-recovery.md` | A nightly job failed — diagnose + relaunch |
| `press-review-provider-switch.md` | Switching LLM provider for press review |
| `seasonal-score-backfill.md` | Backfilling historical seasonal scores |

#### Contacts

- **Operator + reviewer**: Hedi (CTO). Pings him on Slack for: prod schema changes, contract rolls, deploy approvals, algorithm promotion (`is_active=TRUE` flip).
- **You**: own the algorithm correctness, backfill plan, test coverage, runbook for your new pipeline (Path C).

---

## Appendix — Quick command reference

```bash
# Local stack
pnpm db:up                                                    # Start local PG + Redis
pnpm db:down                                                  # Stop
poetry run alembic upgrade head                               # Apply migrations
poetry run alembic revision --autogenerate -m "msg"           # New migration
pnpm dev                                                      # Backend + frontend dev servers
poetry run dev                                                # Backend only
pnpm dev:frontend                                             # Frontend only

# Engine
poetry run compute-indicators --all-contracts --dry-run
poetry run compute-indicators --all-contracts --full \
    --algorithm <name> --algorithm-version <v>
poetry run compute-indicators --all-contracts --all-versions   # Nightly mode

# Tests + lint
poetry run pytest
poetry run pytest tests/engine/ -v
poetry run pytest --cov=app --cov-report=term-missing
poetry run lint

# Contract management
poetry run roll-contract CAN26                                # New active contract

# GCP DB tunnel + sync
gcloud compute ssh cc-bastion --zone=europe-west9-a \
    --tunnel-through-iap --project=cacaooo \
    -- -N -L 5434:10.119.160.3:5432
poetry run python scripts/sync_from_gcp.py

# Prod ops
gcloud run jobs execute cc-<job> --region=europe-west9 --project=cacaooo
gcloud run jobs describe cc-<job> --region=europe-west9 --project=cacaooo
```

---

*This doc is the entry point. Once you've picked a path (§5), the README in `backend/app/engine/` and the rule files in `.claude/rules/` are your next reads. Welcome aboard.*

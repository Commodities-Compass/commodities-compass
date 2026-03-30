# Commodities Compass — Master Conceptual Data Model

**From Spreadsheet to Scalable Platform**

**Date**: 2026-02-25
**Author**: Hedi Blagui
**Status**: Design — Pending Implementation Plan
**Sources**: 20 analysis documents, brainstorming session, whiteboard meeting notes

---

## Executive Summary

Commodities Compass today is a **Google Sheets calculation engine** orchestrated by **Make.com** with scrapers running on **Railway**. It serves one commodity (London cocoa), one user (Julien), one language (French), and one delivery channel (email). The algorithm works — a 4-layer pipeline that transforms 9 raw market inputs into a daily OPEN/MONITOR/HEDGE trading signal.

This document traces the path from that working prototype to a **production-grade data model** capable of supporting multiple commodities, multiple tenants, multiple languages, R&D sandboxing, non-technical fine-tuning, and EU regulatory compliance. It is not a theoretical exercise — every design decision is grounded in concrete findings from 8 deep-dive analysis documents and 4 real-world use cases explored during the brainstorming phase.

The result is a **7-schema PostgreSQL data model** with 43 entities that preserves the existing 4-layer pipeline logic while fixing the 17 structural gaps identified during analysis and review.

**Key architectural choices**:

- **Contract-centric** data model (not commodity-centric) — enables term structure, the #1 signal gap
- **EAV feature storage** — scales from 36 to 100+ indicators without schema changes
- **PostgreSQL schemas as namespaces** — clean permission isolation for cockpit operators vs pipeline code vs tenant API (4 schemas for MVP, 7 at full scale)
- **Immutable raw data and signals** — EU compliance (MiFID II, AI Act) by design, with strict separation between raw ingested data and LLM-computed analysis
- **Tenants subscribe to pipeline outputs** — they don't own pipelines
- **Credit-based billing** — pay-per-use outputs (reports, podcasts) via consumable credits, with subscription plans providing monthly credit allocations
- **Multi-horizon signals** — short-term, mid-term, and long-term signals per commodity, each with dedicated algorithm versions
- **Stripe + Auth0 as external sources of truth** — billing and auth delegated, local schema stores join keys and sync state

---

## Part 1: Where We Are Today

### The Current Architecture

```
Julien fills Google Form (9 fields, daily)
       │
       ▼
Google Sheets — TECHNICALS (36 derived indicators)
       │
       ▼
Google Sheets — INDICATOR (6 z-scored, composite formula)
       │
       ▼
Make.com — DAILY BOT AI (2 GPT-4 Turbo calls)
       │
       ├──► Writes MACROECO_BONUS to INDICATOR
       ├──► Writes DECISION/CONFIANCE/DIRECTION to TECHNICALS
       └──► Sends email to Julien

Railway — Scrapers (Barchart, ICE Report 41, CFTC)
       │
       └──► Feeds Google Form data (manual bridge)
```

**What exists**: 21,468 formulas across 9 sheets. A genetic algorithm that tested 10 million parameter combinations over 10 hours. A working daily pipeline that has been producing signals for months.

**What works**:

- The 4-layer pipeline concept (raw → derived → normalized → composite) is architecturally sound
- The power transformation formula (`a × SIGN(x) × |x|^b`) captures non-linear indicator relationships
- The contrarian macro overlay has empirical support in commodity markets
- The scoring system with 2x penalty for wrong calls creates appropriate risk aversion

### What Doesn't Scale

| Limitation | Impact | Root Cause |
|---|---|---|
| Single commodity (London cocoa CC*0) | Can't diversify, can't cross-correlate | Hardcoded everything |
| Single contract month (front-month only) | No term structure — the #1 signal gap | Data model is commodity-centric |
| Single user, single language | Can't sell to non-French speakers | No tenant concept |
| Google Sheets as compute engine | 21K formulas, O(N²) normalization, OFFSET bottleneck | Wrong tool for production compute |
| Manual data entry via Google Form | Pipeline blocks if Julien is unavailable | No automated ingestion |
| Make.com as orchestrator | Rate limits, no retry logic, no observability | Not built for data pipelines |
| No audit trail | Can't answer "why did you say HEDGE on Feb 10?" | No lineage tracking |
| No version control on formulas | Anyone can break the algorithm with an accidental edit | Spreadsheet has no git |
| Hardcoded algorithm parameters | Can't A/B test, can't rollback, can't explain changes | CONFIG sheet is manual |

### Critical Bugs Found During Analysis

These findings come from 8 deep-dive documents analyzing the spreadsheet formulas, the Make.com blueprints, and the algorithm logic:

1. **MOMENTUM is broken** — `#REF!` error in INDICATOR!O2. The 2nd strongest CONFIG component contributes nothing to the signal. (08-business-logic §3.4)
2. **MONITOR/HEDGE labels are swapped** in the backtesting formula. The GA optimized against corrupted fitness evaluation. (08-business-logic §5.4, 13-composite §6)
3. **Non-stationary z-scores** — full-column `AVERAGE(B:B)` means every new data point retroactively changes all historical z-scores. The 79.7% accuracy claim has implicit look-ahead bias. (12-normalization §3)
4. **Production uses the worst-performing formula** — NBEW CHAMPION (64.6%) is deployed while the linear formula (86.6%) sits unused. (09-algorithm §2, corrected 2026-02-23)
5. **Bollinger Bands are asymmetric** — Upper uses STDEVP (population), Lower uses STDEV (sample). (11-derived §2.7)
6. **MACD Signal line is missing** — column exists, no formula. Running 1/3 of the MACD system. (11-derived §2.3)

---

## Part 2: What the Analysis Revealed

Eight documents were produced between Feb 16-23, 2026, reverse-engineering every formula, every data flow, and every algorithmic decision in the system.

### The 4-Layer Pipeline — Already the Right Mental Model

The spreadsheet implicitly implements a sound architecture:

```
Layer 1: RAW INPUTS         →  9 fields from external sources
Layer 2: DERIVED TECHNICALS  →  36 indicators computed from raw data
Layer 3: NORMALIZATION       →  6 z-scored indicators (smoothed)
Layer 4: COMPOSITE + DECISION → Weighted formula → OPEN/MONITOR/HEDGE
```

This layered pipeline is the right pattern. Professional quant systems use exactly this structure. The problem isn't the architecture — it's the implementation medium (spreadsheets) and the structural limitations (single commodity, no term structure, no audit trail).

### Signal Gaps — What's Missing from the Data

The raw inputs analysis (10-raw-inputs) compared Compass's 9 fields against professional commodity trading standards (25-40+ streams). Critical gaps:

| Gap | Priority | Signal Value | Cost to Fix |
|---|---|---|---|
| Term structure (all contract months) | P0 | Very High — contango/backwardation is among the strongest commodity predictors | $200-350/mo (Barchart API) |
| OPEN price | P0 | High — completes OHLC, enables gap analysis | $0 |
| FX rates (GBP/USD, USD/GHS, EUR/USD) | P0 | High — London cocoa is GBP-denominated | $0 (ECB rates) |
| Cross-commodity (sugar, coffee, palm oil) | P1 | Medium — correlation breakdowns signal regime changes | $0 incremental |
| Satellite/NDVI crop monitoring | P1 | High — NDVI anomalies correlate with production shortfalls 3-6 months ahead | $0 (Google Earth Engine) |
| Grindings data (demand proxy) | P1 | Very High — single most important demand indicator | $0-200/yr (ICCO) |

### Indicator Gaps — What's Missing from the Computation

The derived technicals analysis (11-derived) found that Compass computes 36 indicators, but they're all variations on 5 classic oscillators. Missing entirely:

- **Zero trend-strength indicators** (no ADX/DMI)
- **Zero volume-flow indicators** (no OBV, MFI)
- **Zero commodity-specific indicators** (no CCI, no Herrick Payoff Index)
- **No Price/Volume/OI relationship analysis** — arguably the most important signal in commodity futures
- **Incomplete MACD** (missing Signal Line and Histogram — 2/3 of the system)
- **No SMA 50/200** (no Golden/Death Cross detection — the most-watched CTA signal)

Total eventual indicator count: 70-100+. The data model must accommodate this growth without schema changes.

### Normalization Issues — The Statistical Foundation is Flawed

The normalization analysis (12-normalization) found a fundamental statistical error:

**Full-history z-scores are a known anti-pattern in quantitative finance.** The current formula `Z = (X - AVERAGE(B:B)) / STDEV(B:B)` uses the entire column, meaning:

- Every new data point changes all historical z-scores retroactively
- Backtesting has implicit look-ahead bias (future data normalizes past values)
- The 2023-2024 cocoa crisis (2,500→10,000+ GBP) inflated historical stddev, compressing all current z-scores
- Signal strength is systematically dampened

**Fix**: 252-day rolling z-score. This single change eliminates look-ahead bias, adapts to regime changes, and produces 2.25x stronger signals for the same indicator reading.

---

## Part 3: Design Requirements — From Use Cases to Constraints

Four real-world use cases were explored during the brainstorming phase. Each one stress-tests the data model on a different axis.

### Use Case 1: Multi-Locale Pipelines

> "Tomorrow we have a full pipeline for two countries — one needs FR, one needs EN. They share some components but are mostly independent."

**What this requires from the MCD**:

- Clear separation between shared infrastructure (pipelines, indicators, data sources) and per-tenant configuration (locale, delivery, algo version)
- Pipelines compute once, serve multiple tenants in different locales
- The same HEDGE signal is delivered as "COUVERTURE" in FR and "HEDGE" in EN

**Design decision**: Tenants are client accounts with a subscription tier. Pipelines are internal shared infrastructure. Dashboards are the access layer between the two. A tenant never owns a pipeline — they subscribe to its outputs.

### Use Case 2: R&D Sandbox for New Commodities

> "We need to test a new commodity extensively before launch, in parallel with production, fully isolated."

**What this requires from the MCD**:

- The schema must work identically across environments
- A new commodity in dev must never affect prod tenants
- Promotion path must be clean — no manual schema migration

**Design decision**: Environment-based lifecycle (dev → staging → prod). Same schema deployed in 3 isolated PostgreSQL databases. CI/CD handles promotion. The MCD doesn't need environment columns — isolation is at the database level.

### Use Case 3: Non-Technical Fine-Tuning Cockpit

> "A cockpit that's not too technical, co-manageable by non-technical operators."

**What this requires from the MCD**:

- Every tunable parameter must be a row in a table, not a hardcoded constant
- Versioning: every change creates a new version, old versions are preserved
- Rollback: revert to any previous parameter set instantly
- Audit trail: who changed what, when, why

**Design decision**: The cockpit exposes two domains:

1. **Algorithm parameters** — the 17 coefficients/exponents + 2 thresholds (today's CONFIG sheet, but versioned and auditable)
2. **Data source configuration** — toggle sources on/off, adjust schedules, change smoothing windows, enable/disable indicators

Delivery rules and pipeline orchestration stay in code — technical territory.

### Use Case 4: Per-User Feature Customization

> "Different features for different users, rapid feedback loops, A/B testing."

**What this requires from the MCD**:

- Per-tenant algorithm version pinning (Tenant A on stable v6.3, Tenant B opts into beta v8)
- Per-tenant delivery configuration (email, webhook, push, podcast, weekly digest)
- Thresholds and feature sets are NOT per-tenant — they're internal pipeline decisions

**Design decision**: Customization happens through two knobs: algo version pinning and delivery channel configuration. The system computes multiple algorithm versions in parallel; each tenant is pinned to one.

### Consolidated Requirements

| Requirement | Source | MCD Impact |
|---|---|---|
| Multi-commodity support | Current limitation | `reference.commodity` + `reference.contract` |
| Term structure (multi-contract) | 10-raw-inputs §2.1 | `raw_data.contract_data_daily` (per-contract, not per-commodity) |
| 70-100+ indicators without schema changes | 11-derived §3 | EAV `features.feature_value` |
| Full signal explainability | EU AI Act, MiFID II | `signals.signal_component` per indicator |
| Immutable raw data and signals | MiFID II 5-year retention | Append-only tables, no UPDATE/DELETE |
| Algorithm versioning with rollback | Use case 3 | `signals.algorithm_version` + `signals.algorithm_config` |
| Per-tenant locale + delivery | Use case 1 | `tenant.account` + `tenant.delivery_config` |
| LLM call auditing | EU AI Act + A/B testing | `audit.llm_call` |
| Data quality gates | 08-business-logic §9.2 | `audit.data_quality_check` |
| Non-technical cockpit access | Use case 3 | PG schema permissions, `cockpit_role` |
| Trading calendar awareness | Data quality analysis | `reference.trading_calendar` — distinguish missing data from market holidays |
| Indicator dependency integrity | 11-derived §2.3 (MACD chain) | `reference.indicator_dependency` — FK-enforced DAG, topological sort |
| Billing via Stripe | SaaS monetization | `tenant.account.stripe_customer_id`, `tenant.webhook_event` |
| Auth via Auth0 | Multi-continent user management | `tenant.user.auth0_user_id`, `tenant.webhook_event` |
| Credit-based billing (pay-per-use + subscription credits) | On-demand output monetization | `reference.output_type`, `tenant.credit_ledger`, `tenant.subscription.monthly_credits` |
| Multi-horizon signals (short/mid/long term) | Complete trading signal coverage | `signals.algorithm_version.horizon`, `signals.signal.horizon` |
| Categorized fundamental analysis | Dedicated analysis per fundamental type | `raw_data.fundamental_article.category`, `raw_data.grindings_report` |

---

## Part 4: Architecture Decisions

Seven key decisions shape the MCD. Each is explained with alternatives considered, tradeoffs, and rationale.

### Decision 1: Contract-Centric, Not Commodity-Centric

**The problem**: The current system stores one row per date per commodity. This makes term structure impossible — you'd need one row per date per contract to track prices across CAH26, CAK26, CAN26 simultaneously.

**Alternative considered**: Keep commodity-centric, add separate `term_structure` table. Rejected because it creates two parallel data paths for what is fundamentally the same data (market prices), forcing every query to know which table to hit.

**Decision**: Every market data row is tagged to a specific **contract** (e.g., CAK26), not just a commodity (London cocoa). A commodity has many contracts. The front-month is derived (nearest non-expired contract per the roll rule), not stored as a separate entity.

**Tradeoff**: More rows in `contract_data_daily` (5x for cocoa — one per active delivery month). Negligible cost for the capability gained.

**What this enables**:

- Term structure visualization (all contract prices on one date)
- Contango/backwardation detection (curve slope)
- Calendar spread computation (price difference between months)
- Roll yield calculation (return from rolling contracts)
- Front-month derivation via `roll_rule` (data-driven, not hardcoded)

### Decision 2: EAV for Features, Not Wide Columns

**The problem**: Today there are 36 indicators. The analysis identified 15+ missing Tier 1 indicators, 10+ Tier 2, and 4 each for term structure and fundamentals. Total: 70-100+. A wide-column table with 100+ columns is unmaintainable.

**Alternative considered**: Wide columns with nullable fields. Rejected — adding an indicator requires a schema migration, and most columns would be null for most rows (sparse matrix).

**Decision**: Entity-Attribute-Value pattern. `features.feature_value` stores `(date, commodity_id, indicator_id, value, version, computation_id)`. Adding a new indicator means inserting a row in `reference.indicator_definition` — zero schema change.

**Tradeoff**: EAV queries are slightly more complex (require pivot/crosstab for tabular views). Solved with database views or application-level pivoting.

**What this enables**:

- Add indicators without schema changes (cockpit operation, not engineering)
- Multiple normalization versions of the same indicator (rolling z-score vs percentile rank)
- Feature set management (named collections of indicators for model comparison)
- Historical indicator versioning (recompute with corrected formula, keep both)

### Decision 3: PostgreSQL Schemas as Namespaces

**Three approaches were evaluated**:

| Approach | Description | Verdict |
|---|---|---|
| **A. Flat schema** | All tables in one PG schema, domain-prefixed names | Too noisy at 35+ tables, no permission isolation |
| **B. PG schemas** | 7 schemas mapping to domains, cross-schema FKs | Clean isolation, native permissions, zero distributed overhead |
| **C. Separate databases** | Internal DB + External DB with CDC sync | Over-engineered for current stage, added latency |

**Decision**: Approach B — 7 PostgreSQL schemas.

```
reference   — static entities (commodities, contracts, indicators, data sources)
raw_data    — immutable ingested market data
features    — computed indicator values
signals     — trading decisions and delivery
backtesting — performance evaluation
audit       — observability and lineage
tenant      — client accounts and subscriptions
```

**What this enables**:

- Schema-level `GRANT` for role isolation:
  - `cockpit_role` → sees `reference` + `signals.algorithm_*` + `tenant`
  - `pipeline_role` → sees everything except `tenant`
  - `tenant_api_role` → sees `tenant` (own data only via RLS) + `signals` (read-only)
- If Approach C is ever needed (multi-region tenants), the schema boundaries become exact database split lines — zero rework

**MVP simplification — 4 schemas instead of 7**: For MVP, the computation chain (`raw_data` → `features` → `signals`) is accessed by a single `pipeline_role` with identical permissions. Merging these into a single `pipeline` schema reduces initial Alembic setup without losing the isolation that matters (pipeline vs audit vs tenant vs reference). Split `pipeline` back into 3 schemas when the cockpit requires different permissions per computation layer.

| MVP Schema | Contains | Full-Scale Split |
|---|---|---|
| `reference` | All dictionary tables | Unchanged |
| `pipeline` | raw_data + features + signals + backtesting | → `raw_data`, `features`, `signals`, `backtesting` |
| `audit` | All observability tables | Unchanged |
| `tenant` | All client-facing tables | Unchanged |

### Decision 4: Tenants Subscribe to Outputs, Don't Own Pipelines

**The mental model**:

```
[Internal: pipelines + data + algorithms]
        │
        │  computes once
        ▼
[Access layer: subscriptions + permissions]
        │
        │  projects per-tenant
        ▼
[Tenant: dashboards + delivery + locale]
```

Pipelines are shared internal infrastructure. Tenants are client accounts. A tenant subscribes to specific commodities with a specific tier and receives signals through their configured delivery channels in their preferred locale.

**Per-tenant customization is deliberately limited to two knobs**:

1. **Algorithm version pinning** — stable vs beta
2. **Delivery configuration** — channels, frequency, format

Thresholds, feature sets, and indicator selection are internal pipeline decisions, not tenant-facing. This keeps the system predictable and auditable — every tenant on the same algo version sees the same signal.

### Decision 5: Environment-Based R&D Lifecycle

**Decision**: dev → staging → prod. Same schema, 3 isolated PostgreSQL databases.

The MCD doesn't contain environment columns. Isolation is at the infrastructure level. A new commodity starts in dev, passes quality gates (automated backtests, data quality checks), promotes to staging (internal validation), then prod (tenant-visible).

**Why not feature flags?** A flag-based approach (single DB, experimental commodities hidden by flag) risks data contamination. A buggy experimental scraper could corrupt shared tables. Environment isolation eliminates this risk class entirely.

### Decision 6: Cockpit Tunables Are Data, Not Code

**Two domains are cockpit-accessible**:

| Domain | What's Tunable | How It's Stored |
|---|---|---|
| Algorithm | 17 coefficients/exponents + 2 thresholds | `signals.algorithm_config` — one row per parameter per version |
| Data sources | Enabled/disabled, schedule, provider config | `reference.data_source` — configurable columns |
| Indicators | Smoothing window, enabled/disabled | `reference.indicator_definition` — configurable columns |

Every change creates a new `algorithm_version` (for algo params) or is logged in `audit.config_change_log` (for data source/indicator changes). Old versions are preserved. Rollback = pin to a previous version.

### Decision 7: Immutable Raw Data and Signals (EU Compliance)

Three EU regulations shape the data model:

| Regulation | Requirement | MCD Impact |
|---|---|---|
| **GDPR** | Right to erasure for tenant PII | `tenant.user` supports soft-delete + anonymization |
| **MiFID II** | 5-year retention of signals + inputs that produced them | `raw_data.*` and `signals.signal` are append-only (no UPDATE/DELETE) |
| **EU AI Act** | Transparency and explainability for AI-influenced decisions | `signals.signal_component` stores per-indicator contribution; `audit.llm_call` stores full prompt/response |

**The traceability chain**: Given any signal delivered to a tenant, you can reconstruct the full path: which raw data was ingested → which features were computed (with what normalization parameters) → which algorithm version produced the score → which indicators contributed what weight → what was delivered to whom, when, via what channel.

---

## Part 5: The Master Conceptual Data Model

### Schema Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        reference (dictionary)                       │
│  commodity │ exchange │ contract_month │ contract │ roll_rule       │
│  trading_calendar │ data_provider │ data_source │ output_type       │
│  indicator_definition │ indicator_dependency                        │
└──────────┬──────────────────────────────────────────────────────────┘
           │ FK
┌──────────▼──────────────────────────────────────────────────────────┐
│                      raw_data (immutable ledger)                    │
│  contract_data_daily │ fx_rate_daily │ cot_report                  │
│  weather_observation │ satellite_observation                        │
│  fundamental_article │ grindings_report                             │
└──────────┬──────────────────────────────────────────────────────────┘
           │ FK
┌──────────▼──────────────────────────────────────────────────────────┐
│                      features (computed indicators)                 │
│  feature_value │ feature_set │ feature_set_member                   │
└──────────┬──────────────────────────────────────────────────────────┘
           │ FK
┌──────────▼──────────────────────────────────────────────────────────┐
│                      signals (trading decisions)                    │
│  algorithm_version │ algorithm_config │ signal │ signal_component   │
│  signal_delivery                                                    │
└──────────┬──────────────────────────────────────────────────────────┘
           │ FK
┌──────────▼──────────────────────────────────────────────────────────┐
│                    backtesting (performance tracking)                │
│  backtest_run │ backtest_result │ performance_metric                 │
│  experiment_run                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      audit (observability & lineage)                │
│  data_ingestion_log │ pipeline_run │ llm_call                      │
│  data_quality_check │ config_change_log                             │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      tenant (client storefront)                     │
│  account │ user │ subscription │ delivery_config                    │
│  alert_rule │ alert_event │ webhook_event │ credit_ledger           │
└─────────────────────────────────────────────────────────────────────┘
```

### Schema: `reference` — The Dictionary

Static and semi-static entities that define what the system knows about. Changed infrequently, via cockpit or admin.

#### commodity

The asset being tracked. Multi-commodity from day one.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| code | VARCHAR(20) | Unique code — `london_cocoa`, `ny_cocoa`, `sugar_11` |
| name | VARCHAR(100) | Display name — "London Cocoa" |
| exchange_id | FK → exchange | Which exchange this trades on |
| currency | VARCHAR(3) | Denomination — GBP, USD |
| unit | VARCHAR(20) | "tonnes", "pounds", "bushels" |
| tick_size | DECIMAL | Minimum price increment |
| contract_size | DECIMAL | Tonnes per contract (10 for ICE cocoa) |
| is_active | BOOLEAN | Soft-disable without deleting |
| created_at | TIMESTAMPTZ | |

#### exchange

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| code | VARCHAR(10) | `ICE_EU`, `ICE_US`, `CME` |
| name | VARCHAR(100) | "ICE Futures Europe" |
| timezone | VARCHAR(50) | "Europe/London" |
| trading_hours | JSONB | Opening/closing times per session |

#### contract_month

Delivery month codes — standard across all exchanges.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| code | CHAR(1) | H, K, N, U, Z (March, May, July, Sep, Dec for cocoa) |
| name | VARCHAR(20) | "March", "May", etc. |
| month_number | SMALLINT | 3, 5, 7, 9, 12 |

#### contract

A specific tradeable instrument. This is the core entity that makes term structure possible.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| commodity_id | FK → commodity | Which commodity |
| contract_month_id | FK → contract_month | Which delivery month |
| year | SMALLINT | 2026, 2027 |
| symbol | VARCHAR(20) | "CAK26" — unique |
| expiry_date | DATE | Last trading date |
| first_notice_date | DATE | First delivery notice |
| is_active | BOOLEAN | Still trading? |

**How front-month works**: The front-month contract on any date is the nearest active contract whose expiry is after the roll date. This is a query, not a stored value:

```sql
SELECT c.* FROM reference.contract c
JOIN reference.roll_rule r ON r.commodity_id = c.commodity_id
WHERE c.commodity_id = 'london_cocoa'
  AND c.is_active = true
  AND c.expiry_date - r.days_before_expiry > CURRENT_DATE
ORDER BY c.expiry_date
LIMIT 1;
```

#### roll_rule

Defines when the system rolls from one front-month contract to the next.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| commodity_id | FK → commodity | One rule per commodity |
| days_before_expiry | SMALLINT | Roll N days before expiry (e.g., 15) |
| roll_method | VARCHAR(20) | `calendar`, `volume`, `open_interest` |
| description | TEXT | Human-readable explanation |

#### trading_calendar

Market holidays and trading sessions per exchange. Critical for distinguishing "scraper failed" from "market was closed" and for computing correct rolling windows (252 trading days, not calendar days).

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| exchange_id | FK → exchange | Which exchange |
| date | DATE | Calendar date |
| is_trading_day | BOOLEAN | Market open? |
| session_type | VARCHAR(20) | `regular`, `half_day`, `holiday` |
| reason | VARCHAR(100) | "Good Friday", "Christmas", NULL if regular |

**Unique constraint**: `(exchange_id, date)`

Populated annually from exchange-published calendars (ICE, CME). ~252 rows per exchange per year — trivial volume. Enables holiday-aware pipeline scheduling and correct data quality checks.

#### data_provider

The organization that provides data. One provider serves many sources.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| code | VARCHAR(30) | `barchart`, `ice`, `cftc`, `ecb`, `nasa_power`, `google_earth_engine` |
| name | VARCHAR(100) | Display name |
| api_type | VARCHAR(20) | `rest`, `websocket`, `scraper`, `file_download` |
| base_url | VARCHAR(500) | API base URL |
| credentials_encrypted | BYTEA | Encrypted API key / auth token |
| rate_limit | JSONB | `{"requests_per_minute": 60}` |
| is_active | BOOLEAN | Cockpit-toggleable |

#### data_source

A specific data feed from a provider. Cockpit-configurable.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| provider_id | FK → data_provider | Which provider |
| commodity_id | FK → commodity | NULL if cross-commodity (FX rates, weather) |
| code | VARCHAR(50) | `barchart_london_cocoa_ohlcv`, `cftc_cot_cocoa` |
| name | VARCHAR(100) | Display name |
| data_type | VARCHAR(30) | `market_data`, `cot`, `fx`, `weather`, `satellite`, `news` |
| frequency | VARCHAR(20) | `daily`, `weekly`, `quarterly`, `event_driven` |
| schedule_cron | VARCHAR(50) | Cockpit-configurable schedule |
| config | JSONB | Source-specific params (symbols, endpoints, parsing rules) |
| is_enabled | BOOLEAN | Cockpit-toggleable |
| last_successful_run | TIMESTAMPTZ | Tracked by ingestion pipeline |

#### indicator_definition

Every technical or fundamental indicator the system can compute. Cockpit-configurable.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| code | VARCHAR(50) | `rsi_14`, `macd_line`, `macd_signal`, `ema_12`, `sma_200`, `atr_14`, `cci_20` |
| name | VARCHAR(100) | Display name |
| category | VARCHAR(30) | `momentum`, `trend`, `volatility`, `volume`, `fundamental`, `term_structure` |
| formula_description | TEXT | Human-readable formula explanation |
| default_params | JSONB | `{"period": 14, "smoothing": "wilder"}` |
| smoothing_window | SMALLINT | 5-day SMA, cockpit-adjustable |
| normalization_method | VARCHAR(30) | `rolling_zscore`, `percentile_rank`, `robust_zscore`, `none` |
| normalization_window | SMALLINT | 252 (trading days), cockpit-adjustable |
| layer | SMALLINT | 1 (raw-derived), 2 (normalized), 3 (composite) |
| is_enabled | BOOLEAN | Cockpit-toggleable |
| created_at | TIMESTAMPTZ | |

#### indicator_dependency

Junction table for indicator computation dependencies. Replaces a `depends_on UUID[]` array column — PostgreSQL cannot enforce foreign keys on array elements, so a junction table ensures referential integrity and enables dependency graph queries.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| indicator_id | FK → indicator_definition | The indicator that has a dependency |
| depends_on_id | FK → indicator_definition | The indicator it depends on |

**Unique constraint**: `(indicator_id, depends_on_id)`

**Example**: MACD Signal depends on MACD Line and EMA(9). MACD Line depends on EMA(12) and EMA(26). This creates a directed acyclic graph (DAG) that determines pipeline execution order.

#### output_type

Defines platform outputs that consume credits. Each output type has a fixed credit cost. Cockpit-configurable.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| code | VARCHAR(30) | `daily_report`, `podcast`, `weekly_digest`, `alert`, `api_call` |
| name | VARCHAR(100) | Display name — "Daily Analysis Report" |
| description | TEXT | What this output includes |
| credit_cost | SMALLINT | Credits consumed per use (e.g., 5 for a report, 10 for a podcast) |
| is_active | BOOLEAN | Cockpit-toggleable |
| created_at | TIMESTAMPTZ | |

**How credits work**: When a tenant requests an output (report, podcast, etc.), the system checks their credit balance (computed from `tenant.credit_ledger`), debits the `credit_cost`, and records the transaction. Output types and their costs are managed in the cockpit — adjusting a price means updating one row, not changing code.

**Why a junction table instead of UUID[]**: FK enforcement (delete a dependency → PG blocks it), queryable with recursive CTEs for topological sort (compute dependencies before dependents), and standard relational pattern for graph structures.

```sql
-- Full computation chain for any indicator (topological sort)
WITH RECURSIVE dep_tree AS (
  SELECT depends_on_id, 1 AS depth
  FROM reference.indicator_dependency
  WHERE indicator_id = :target_indicator
  UNION ALL
  SELECT d.depends_on_id, t.depth + 1
  FROM reference.indicator_dependency d
  JOIN dep_tree t ON d.indicator_id = t.depends_on_id
)
SELECT * FROM dep_tree ORDER BY depth DESC;
```

---

### Schema: `raw_data` — The Immutable Ledger

All data ingested from external sources. **Append-only — no UPDATE, no DELETE.** This is the single source of truth and the foundation of EU compliance.

#### contract_data_daily

Market data per contract per day. This is the table that makes term structure possible.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| date | DATE | Trading date |
| contract_id | FK → contract | Specific contract (CAK26, not just "cocoa") |
| commodity_id | FK → commodity | Denormalized for query performance |
| open | DECIMAL(12,4) | Opening price (P0 gap — was missing) |
| high | DECIMAL(12,4) | High |
| low | DECIMAL(12,4) | Low |
| close | DECIMAL(12,4) | Close (settlement) |
| volume | INTEGER | Contracts traded |
| open_interest | INTEGER | Open contracts at close |
| implied_volatility | DECIMAL(8,4) | ATM implied vol (%) |
| source_id | FK → data_source | Which source provided this |
| ingestion_id | FK → data_ingestion_log | Which ingestion run |
| created_at | TIMESTAMPTZ | |

**Unique constraint**: `(date, contract_id)` — one row per contract per day.

**How the current TECHNICALS!A-I maps here**: Today's 9 fields become rows in this table, but per-contract instead of per-commodity. The OPEN price (today's P0 gap) gets its own column. Volume is stored raw (not ×10).

#### fx_rate_daily

Currency exchange rates. Separate from market data because FX rates aren't tied to a commodity contract.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| date | DATE | Rate date |
| base_currency | VARCHAR(3) | GBP, USD, EUR |
| quote_currency | VARCHAR(3) | USD, GHS, EUR |
| rate | DECIMAL(12,6) | Exchange rate |
| source_id | FK → data_source | ECB, Alpha Vantage |
| created_at | TIMESTAMPTZ | |

**Unique constraint**: `(date, base_currency, quote_currency)`

#### cot_report

CFTC Commitments of Traders — weekly data with inherent publication lag.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| report_date | DATE | As-of date (Tuesday) |
| publication_date | DATE | When published (Friday, 3-4 day lag) |
| commodity_id | FK → commodity | |
| commercial_long | INTEGER | Producer/merchant longs |
| commercial_short | INTEGER | Producer/merchant shorts |
| commercial_net | INTEGER | Long - Short (today's COM NET US) |
| non_commercial_long | INTEGER | Speculative longs |
| non_commercial_short | INTEGER | Speculative shorts |
| non_commercial_net | INTEGER | |
| open_interest_total | INTEGER | Total market OI from COT |
| source_id | FK → data_source | |
| created_at | TIMESTAMPTZ | |

#### weather_observation

Raw weather text as ingested from external sources. Maps to today's METEO_ALL.

**Immutability note**: This table stores only the raw ingested text. LLM-derived fields (summary, keywords, impact_score) are stored in `audit.llm_call.parsed_response` and linked via `llm_call_id`. If `impact_score` feeds the signal, the pipeline extracts it as a `feature_value` row — keeping the boundary clean between raw data and computed analysis.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| date | DATE | Observation date |
| commodity_id | FK → commodity | Which commodity's growing region |
| raw_text | TEXT | Full weather text as ingested from source |
| llm_call_id | FK → llm_call | Links to LLM analysis (summary, keywords, impact_score stored in parsed_response) |
| source_id | FK → data_source | |
| ingestion_id | FK → data_ingestion_log | Which ingestion run |
| created_at | TIMESTAMPTZ | |

#### satellite_observation

Structured numeric satellite data (NDVI, rainfall). Different from weather_observation (text-based).

**Immutability note**: Only raw observed values are stored here. Computed derivatives (e.g., `ndvi_anomaly` — deviation from historical baseline) belong in `features.feature_value` as computed indicators, not in the raw data ledger.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| date | DATE | Observation date |
| commodity_id | FK → commodity | Which commodity's growing region |
| region_code | VARCHAR(50) | Geographic region (e.g., "ivory_coast_cocoa_belt") |
| ndvi | DECIMAL(6,4) | Normalized Difference Vegetation Index (0-1) |
| rainfall_mm | DECIMAL(8,2) | Daily rainfall |
| temperature_avg_c | DECIMAL(5,2) | Average temperature |
| soil_moisture | DECIMAL(6,4) | Relative soil moisture (0-1) |
| source_id | FK → data_source | Google Earth Engine, NASA POWER |
| created_at | TIMESTAMPTZ | |

#### fundamental_article

Text-based fundamental analysis, categorized by topic. Replaces `news_article` (formerly BIBLIO_ALL) with explicit category tagging to enable dedicated analysis pipelines per fundamental type.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| date | DATE | Publication date |
| commodity_id | FK → commodity | Related commodity (NULL if macro) |
| category | VARCHAR(30) | `supply`, `demand`, `macro`, `geopolitical`, `weather`, `regulatory`, `trade_flow` |
| author | VARCHAR(200) | Source/author |
| summary | TEXT | Article summary |
| keywords | TEXT[] | Extracted keywords |
| impact_synthesis | TEXT | Impact analysis |
| url | VARCHAR(500) | Source URL |
| llm_call_id | FK → llm_call | If LLM-processed |
| source_id | FK → data_source | |
| created_at | TIMESTAMPTZ | |

**Why `category` instead of separate tables per topic**: All text-based fundamentals share the same structure (text in, LLM analysis out). The `category` column enables per-topic LLM prompts and analysis pipelines without schema proliferation. Structurally different data (like numeric grindings reports) gets its own table — see `grindings_report` below.

#### grindings_report

Structured numeric demand data from industry sources (ICCO, ECA, NCA). Grindings (cocoa bean processing volumes) are the single most important demand proxy in cocoa markets. Separate from `fundamental_article` because this is tabular numeric data, not text.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| report_date | DATE | Period end date |
| publication_date | DATE | When published (typically 1-2 month lag) |
| commodity_id | FK → commodity | Which commodity |
| region | VARCHAR(50) | `europe`, `north_america`, `asia`, `ivory_coast`, `ghana`, `global` |
| period_type | VARCHAR(20) | `quarterly`, `annual` |
| period_label | VARCHAR(20) | "Q1 2026", "2025" |
| volume_tonnes | DECIMAL(12,2) | Processing volume in metric tonnes |
| yoy_change_pct | DECIMAL(8,4) | Year-over-year change (%) |
| source_id | FK → data_source | ICCO, ECA, NCA |
| ingestion_id | FK → data_ingestion_log | Which ingestion run |
| created_at | TIMESTAMPTZ | |

**Unique constraint**: `(report_date, commodity_id, region, period_type)`

**How derived analysis works**: Raw grindings data is ingested here. Derived indicators (grindings momentum, demand trend, regional divergence) are computed by the pipeline and stored in `features.feature_value` via `indicator_definition` entries with `category = 'fundamental'`. The EAV pattern handles the analytical output; this table handles the structured numeric input.

---

### Schema: `features` — The Calculator

Computed indicator values. The EAV structure that scales from 36 to 100+ indicators without schema changes.

#### feature_value

One row per (date × commodity × indicator × version). The core of the feature store.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| date | DATE | Computation date |
| commodity_id | FK → commodity | Which commodity |
| indicator_id | FK → indicator_definition | Which indicator |
| value | DECIMAL(18,8) | The computed value |
| normalized_value | DECIMAL(18,8) | After normalization (z-score, percentile, etc.) |
| normalization_method | VARCHAR(30) | Method used (denormalized from indicator_definition for immutability) |
| normalization_window | SMALLINT | Window used |
| version | SMALLINT | Computation version (recompute = new version) |
| computation_id | FK → pipeline_run | Which pipeline run produced this |
| created_at | TIMESTAMPTZ | |

**Unique constraint**: `(date, commodity_id, indicator_id, version)`

**How the current spreadsheet maps here**: Today's TECHNICALS columns J-AT (36 indicators) become rows. INDICATOR columns H-M (6 z-scored values) map to the `normalized_value` column. Adding RSI(21) or CCI(20) means inserting a row in `indicator_definition` and the pipeline produces new `feature_value` rows — zero schema change.

**Partitioning strategy**: `feature_value` is the highest-growth table — at 100 indicators × 5 contracts × 252 trading days = ~126K rows/year/commodity. At 10 commodities over 5 years: ~6.3M rows. Range partition by year on `date` using PostgreSQL native declarative partitioning. Queries with date ranges only scan relevant partitions, and old partitions can be archived to cold storage. The schema is already partition-ready: `date` is part of the unique constraint `(date, commodity_id, indicator_id, version)`. Not needed at MVP (under 1M rows), but should be enabled before crossing ~2M rows.

#### feature_set

A named, versioned collection of indicators that feeds a model. Solves the undocumented "why these 6 indicators?" problem.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| name | VARCHAR(100) | "production_v1", "experimental_with_term_structure" |
| version | SMALLINT | Version number |
| description | TEXT | Why this set was chosen |
| created_by | VARCHAR(100) | Who created it |
| created_at | TIMESTAMPTZ | |
| is_active | BOOLEAN | |

#### feature_set_member

Which indicators belong to which feature set.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| feature_set_id | FK → feature_set | |
| indicator_id | FK → indicator_definition | |
| normalization_override | JSONB | Per-indicator normalization config if different from default |
| weight_hint | DECIMAL(6,4) | Optional suggested weight (for cockpit display) |

---

### Schema: `signals` — The Oracle

Trading decisions produced by the algorithm, and their delivery to tenants.

#### algorithm_version

A specific version of the algorithm. Today's CONFIG columns (ACTUEL, NBEW CHAMPION, TEST v8) become rows.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| name | VARCHAR(100) | "v6.3_actuel", "nbew_champion", "test_v8", "linear_legacy" |
| version | VARCHAR(20) | Semantic version |
| horizon | VARCHAR(20) | `short_term`, `mid_term`, `long_term` — the analysis timeframe this version targets |
| formula_type | VARCHAR(20) | `linear`, `power`, `ml_model` |
| feature_set_id | FK → feature_set | Which indicators this version uses |
| description | TEXT | What changed, why |
| status | VARCHAR(20) | `draft`, `testing`, `staging`, `production`, `deprecated` |
| created_by | VARCHAR(100) | |
| created_at | TIMESTAMPTZ | |
| promoted_at | TIMESTAMPTZ | When promoted to production |

**Multi-horizon design**: Each algorithm version is scoped to a single horizon. A commodity can have multiple production-status versions active simultaneously — one per horizon. Example: London cocoa has "v6.3_short" (daily signals), "v2.1_mid" (weekly outlook), and "v1.0_long" (monthly strategic view). Each uses different feature sets, different normalization windows, and different thresholds appropriate to its timeframe. Tenants subscribe to horizons via `delivery_config`.

#### algorithm_config

Parameter values for an algorithm version. Today's CONFIG rows become rows here. Cockpit-editable.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| algorithm_version_id | FK → algorithm_version | Which version |
| param_name | VARCHAR(50) | `k`, `rsi_coefficient`, `rsi_exponent`, `open_threshold` |
| param_value | DECIMAL(12,6) | The value (-0.947, 1.229, 1.813, 0.9) |
| param_min | DECIMAL(12,6) | Allowed range min (for cockpit validation) |
| param_max | DECIMAL(12,6) | Allowed range max |
| param_step | DECIMAL(12,6) | Allowed step size |
| description | VARCHAR(200) | Human-readable label for cockpit |

**How CONFIG maps here**: Today's 17 parameters × 4 versions = 68 rows. The ACTUEL column (F) becomes `algorithm_version` "v6.3_actuel" with 17+2 `algorithm_config` rows. NBEW CHAMPION (G) becomes another version with its own 19 rows. Creating a new version = duplicating + modifying rows.

#### signal

A trading signal produced for a specific commodity on a specific date. **Append-only.**

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| date | DATE | Signal date |
| commodity_id | FK → commodity | |
| algorithm_version_id | FK → algorithm_version | Which algo produced this |
| horizon | VARCHAR(20) | `short_term`, `mid_term`, `long_term` — denormalized from algorithm_version for query convenience |
| raw_score | DECIMAL(12,6) | The composite indicator value |
| decision | VARCHAR(10) | `OPEN`, `MONITOR`, `HEDGE` |
| confidence | DECIMAL(5,4) | 0-1 confidence score |
| open_threshold | DECIMAL(12,6) | Threshold used (denormalized for immutability) |
| hedge_threshold | DECIMAL(12,6) | Threshold used |
| computation_id | FK → pipeline_run | Which pipeline run |
| created_at | TIMESTAMPTZ | |

**Unique constraint**: `(date, commodity_id, algorithm_version_id)`

**How INDICATOR!Q-R maps here**: Today's FINAL INDICATOR (Q) becomes `raw_score`. CONCLUSION (R) becomes `decision`. But now we also store WHICH algorithm version produced it and what thresholds were active — answering "why did you say HEDGE?" becomes a simple query.

#### signal_component

Per-indicator contribution to a signal. This is the explainability table required by EU AI Act.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| signal_id | FK → signal | Parent signal |
| indicator_id | FK → indicator_definition | Which indicator |
| raw_value | DECIMAL(18,8) | The z-scored input value |
| coefficient | DECIMAL(12,6) | Weight applied |
| exponent | DECIMAL(12,6) | Power applied (1.0 for linear) |
| contribution | DECIMAL(12,6) | The term's contribution to composite score |

**How this maps**: For each signal, this table stores the 6-8 individual terms of the formula. `contribution` = `coefficient × SIGN(raw_value) × |raw_value|^exponent`. Sum of all contributions + constant = `signal.raw_score`. Full transparency.

#### signal_delivery

Who received what signal, when, via what channel. MiFID II compliance.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| signal_id | FK → signal | Which signal |
| tenant_id | FK → tenant.account | Which tenant |
| channel | VARCHAR(20) | `email`, `webhook`, `push`, `podcast`, `dashboard` |
| locale | VARCHAR(5) | `fr`, `en` |
| delivered_at | TIMESTAMPTZ | Actual delivery time |
| delivery_status | VARCHAR(20) | `pending`, `delivered`, `failed`, `retrying` |
| content_snapshot | JSONB | What was actually sent (email body, webhook payload) |
| error_detail | TEXT | If failed |

---

### Schema: `backtesting` — The Judge

Performance evaluation of algorithm versions. Tracks both individual backtests and GA optimization experiments.

#### backtest_run

A single backtest execution. Includes split type to prevent the "no train/test split" issue found in the current system.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| algorithm_version_id | FK → algorithm_version | What's being tested |
| feature_set_id | FK → feature_set | Which indicators |
| commodity_id | FK → commodity | Which commodity |
| date_range_start | DATE | Backtest start |
| date_range_end | DATE | Backtest end |
| split_type | VARCHAR(20) | `full` (bad), `train_test`, `walk_forward`, `k_fold` |
| train_pct | DECIMAL(4,2) | e.g., 0.60 |
| validation_pct | DECIMAL(4,2) | e.g., 0.20 |
| test_pct | DECIMAL(4,2) | e.g., 0.20 |
| normalization_method | VARCHAR(30) | Method used during backtest |
| normalization_window | SMALLINT | Window used |
| status | VARCHAR(20) | `running`, `completed`, `failed` |
| started_at | TIMESTAMPTZ | |
| completed_at | TIMESTAMPTZ | |
| notes | TEXT | |

#### backtest_result

Per-date results within a backtest run.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| backtest_run_id | FK → backtest_run | |
| date | DATE | |
| predicted_decision | VARCHAR(10) | What the algo said |
| actual_direction | DECIMAL(12,4) | Actual price change (next day) |
| is_correct | BOOLEAN | Was the prediction right? |
| score | DECIMAL(8,4) | Scoring matrix value (+1.25, +1.0, -2x|change|, +0.75) |
| split_partition | VARCHAR(10) | `train`, `validation`, `test` |

#### performance_metric

Aggregate metrics for a backtest. Addresses the "hit-rate only scoring" issue by requiring Sharpe, Sortino, drawdown.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| backtest_run_id | FK → backtest_run | |
| split_partition | VARCHAR(10) | Which partition (report on test only) |
| metric_name | VARCHAR(50) | `success_rate`, `sharpe_ratio`, `sortino_ratio`, `max_drawdown`, `profit_factor`, `expectancy`, `coverage`, `calmar_ratio` |
| metric_value | DECIMAL(12,6) | |

#### experiment_run

GA optimization runs. One experiment = many backtests. Maps to the 10M-iteration optimization.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| name | VARCHAR(100) | "ga_v6.3_10M", "ga_v8_5M" |
| commodity_id | FK → commodity | |
| feature_set_id | FK → feature_set | |
| method | VARCHAR(30) | `genetic_algorithm`, `bayesian`, `grid_search`, `random` |
| total_iterations | BIGINT | 10,000,000 |
| winners_found | INTEGER | 50 |
| runtime_minutes | DECIMAL(10,2) | 622.2 |
| tests_per_second | DECIMAL(10,2) | 268 |
| best_fitness | DECIMAL(10,6) | 0.651 |
| best_algorithm_version_id | FK → algorithm_version | The winner |
| config | JSONB | Search space definition, population size, mutation rate |
| started_at | TIMESTAMPTZ | |
| completed_at | TIMESTAMPTZ | |

---

### Schema: `audit` — The Witness

Observability, lineage, and compliance tracking across all pipeline stages.

#### data_ingestion_log

Every scrape/API call. Today's Sentry cron monitoring becomes structured data.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| source_id | FK → data_source | Which source |
| started_at | TIMESTAMPTZ | |
| completed_at | TIMESTAMPTZ | |
| status | VARCHAR(20) | `success`, `partial`, `failed` |
| rows_fetched | INTEGER | |
| rows_inserted | INTEGER | |
| latency_ms | INTEGER | |
| error_detail | TEXT | If failed |
| metadata | JSONB | Source-specific details (HTTP status, response size) |

#### pipeline_run

Tracks execution of each pipeline stage (L1 ingestion, L2 derivation, L3 normalization, L4 composite).

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| pipeline_name | VARCHAR(50) | `daily_analysis`, `backtest`, `recompute_features` |
| stage | VARCHAR(30) | `ingestion`, `derived`, `normalization`, `composite`, `delivery` |
| commodity_id | FK → commodity | |
| date | DATE | Processing date |
| started_at | TIMESTAMPTZ | |
| completed_at | TIMESTAMPTZ | |
| status | VARCHAR(20) | `running`, `completed`, `failed` |
| config_snapshot | JSONB | Frozen config at execution time |
| error_detail | TEXT | |

#### llm_call

Every LLM invocation. Required for EU AI Act transparency and for A/B testing providers.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| pipeline_run_id | FK → pipeline_run | |
| provider | VARCHAR(20) | `openai`, `anthropic`, `google` |
| model | VARCHAR(50) | `gpt-4-turbo`, `claude-sonnet-4-5-20250929` |
| temperature | DECIMAL(3,2) | 0.7, 1.0 |
| prompt_version | VARCHAR(20) | Versioned prompt identifier |
| prompt_text | TEXT | Full prompt sent |
| response_text | TEXT | Full response received |
| parsed_response | JSONB | Structured extraction from response (e.g., `{"summary": "...", "keywords": [...], "impact_score": 7.5}`) — used by downstream pipeline stages |
| input_tokens | INTEGER | |
| output_tokens | INTEGER | |
| latency_ms | INTEGER | |
| cost_usd | DECIMAL(8,6) | Estimated cost |
| created_at | TIMESTAMPTZ | |

**How Make.com's 2 daily LLM calls map here**: GPT-4 Turbo Call #1 (T=1.0, macro analysis → MACROECO_BONUS) and Call #2 (T=0.7, trading synthesis → DECISION) each become a row. Full prompt and response preserved for audit and future provider comparison (Claude vs GPT vs Gemini).

#### data_quality_check

Quality gates per ingestion. Addresses the data quality issues found in analysis (empty MACROECO_BONUS, missing 5-day data, outlier contamination).

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| ingestion_id | FK → data_ingestion_log | |
| date | DATE | |
| commodity_id | FK → commodity | |
| check_name | VARCHAR(50) | `null_check`, `range_check`, `staleness_check`, `outlier_check` |
| status | VARCHAR(10) | `pass`, `warn`, `fail` |
| details | JSONB | `{"field": "close", "value": 27360, "expected_range": [2000, 15000]}` |
| created_at | TIMESTAMPTZ | |

#### config_change_log

Every mutation to cockpit-configurable entities. Who changed what, when, old value → new value.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| entity_type | VARCHAR(50) | `algorithm_config`, `data_source`, `indicator_definition` |
| entity_id | UUID | Which row changed |
| field_name | VARCHAR(50) | Which column |
| old_value | TEXT | Previous value |
| new_value | TEXT | New value |
| changed_by | VARCHAR(100) | User who made the change |
| changed_at | TIMESTAMPTZ | |
| reason | TEXT | Optional justification |

---

### Schema: `tenant` — The Storefront

Client accounts, subscriptions, and delivery configuration. Row-Level Security ensures tenants only see their own data.

#### account

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| name | VARCHAR(200) | Company/individual name |
| slug | VARCHAR(50) | URL-safe identifier |
| locale | VARCHAR(5) | `fr`, `en` |
| tier | VARCHAR(20) | `free`, `pro`, `enterprise` — synced from Stripe via webhook |
| stripe_customer_id | VARCHAR(255) | Stripe Customer ID (`cus_xxx`) — source of truth for billing |
| billing_email | VARCHAR(255) | Billing contact (may differ from user email) |
| algorithm_version_id | FK → algorithm_version | Pinned algo version (NULL = latest stable) |
| is_active | BOOLEAN | |
| created_at | TIMESTAMPTZ | |

**Billing philosophy**: Stripe is the source of truth for all billing state (payment methods, invoices, subscription cycles, usage metering). The local `tier` column is a cached projection synced via Stripe webhooks (`customer.subscription.updated`). Never query Stripe in the hot path — use the local tier for access control, reconcile async.

#### user

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| account_id | FK → account | |
| email | VARCHAR(255) | PII — GDPR erasable |
| name | VARCHAR(200) | PII — GDPR erasable |
| role | VARCHAR(20) | `admin`, `operator`, `viewer` |
| auth0_user_id | VARCHAR(255) | Auth0 `sub` claim — used to resolve JWT → local user.id |
| is_active | BOOLEAN | |
| created_at | TIMESTAMPTZ | |
| deleted_at | TIMESTAMPTZ | Soft delete |
| anonymized_at | TIMESTAMPTZ | GDPR anonymization timestamp |

#### subscription

Which commodities a tenant has access to.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| account_id | FK → account | |
| commodity_id | FK → commodity | |
| monthly_credits | INTEGER | Credits allocated per billing cycle (NULL for unlimited/legacy plans) |
| started_at | DATE | |
| expires_at | DATE | NULL = no expiry |
| is_active | BOOLEAN | |

**Credit allocation**: When a subscription has `monthly_credits > 0`, the billing cycle (managed by Stripe) triggers a credit allocation — an automatic `credit_ledger` entry of type `allocation` for the specified amount. One-time credit purchases (e.g., "100 for 100 credits") are handled via Stripe Checkout sessions and recorded as `purchase` entries in the ledger.

#### delivery_config

Per-tenant, per-commodity delivery preferences.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| account_id | FK → account | |
| commodity_id | FK → commodity | NULL = all subscribed commodities |
| channel | VARCHAR(20) | `email`, `webhook`, `push`, `podcast` |
| frequency | VARCHAR(20) | `realtime`, `daily`, `weekly_digest` |
| config | JSONB | Channel-specific: `{"webhook_url": "...", "email": "..."}` |
| is_enabled | BOOLEAN | |

#### alert_rule

Per-tenant alert configuration.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| account_id | FK → account | |
| commodity_id | FK → commodity | |
| condition_type | VARCHAR(30) | `signal_decision`, `indicator_threshold`, `data_gap` |
| condition_config | JSONB | `{"decision": "HEDGE"}` or `{"indicator": "rsi_14", "above": 70}` |
| channel | VARCHAR(20) | Delivery channel for this alert |
| is_enabled | BOOLEAN | |

#### alert_event

Fired alert instances.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| alert_rule_id | FK → alert_rule | |
| signal_id | FK → signal | What triggered it |
| fired_at | TIMESTAMPTZ | |
| delivery_status | VARCHAR(20) | `delivered`, `failed` |

#### webhook_event

Inbound webhook sync log for external providers (Stripe, Auth0). Provides an audit trail of all external state changes and replay capability if sync breaks.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| provider | VARCHAR(20) | `stripe`, `auth0` |
| event_type | VARCHAR(100) | `customer.subscription.updated`, `user.created` |
| event_id | VARCHAR(255) | Provider's idempotency key — prevents duplicate processing |
| payload | JSONB | Full webhook payload as received |
| processed_at | TIMESTAMPTZ | When successfully processed (NULL if pending) |
| status | VARCHAR(20) | `processed`, `failed`, `skipped` |
| error_detail | TEXT | If failed |
| created_at | TIMESTAMPTZ | When received |

**Unique constraint**: `(provider, event_id)` — idempotent processing

#### credit_ledger

Append-only transaction log for credit-based billing. Every credit movement (purchase, monthly allocation, consumption, refund) is an immutable row. The current balance for any account is `SUM(amount) WHERE account_id = :id`.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| account_id | FK → account | Which tenant account |
| amount | INTEGER | Positive = credit (purchase, allocation, refund). Negative = debit (consumption). |
| balance_after | INTEGER | Running balance after this transaction (denormalized for fast reads) |
| transaction_type | VARCHAR(20) | `purchase`, `allocation`, `consumption`, `refund`, `expiry`, `adjustment` |
| output_type_id | FK → output_type | Which output was consumed (NULL for purchases/allocations) |
| reference_id | UUID | Links to the entity that triggered this transaction (signal_delivery.id, stripe payment_intent, etc.) |
| reference_type | VARCHAR(30) | `signal_delivery`, `stripe_payment`, `subscription_cycle`, `manual` |
| description | VARCHAR(200) | Human-readable note — "Monthly allocation (Pro plan)", "Daily report - London Cocoa" |
| created_at | TIMESTAMPTZ | |

**Append-only — no UPDATE, no DELETE.** Corrections are handled via `adjustment` or `refund` entries, never by modifying existing rows. This ensures a complete audit trail for billing disputes.

**Balance computation**: `balance_after` is denormalized for performance (avoids `SUM()` on every credit check). The pipeline computes it at insertion time: `balance_after = previous_balance_after + amount`. Periodic reconciliation job verifies `balance_after` matches `SUM(amount)`.

**Credit lifecycle**:
1. **Purchase**: Tenant buys 100 credits via Stripe → webhook creates `purchase` entry (+100)
2. **Monthly allocation**: Billing cycle triggers → `allocation` entry (+1000 for Pro plan)
3. **Consumption**: Tenant requests a report → system checks `balance_after >= output_type.credit_cost`, then creates `consumption` entry (-5)
4. **Expiry** (optional): Unused monthly credits expire at cycle end → `expiry` entry (-remaining)

**Auth philosophy**: Auth0 is the source of truth for all authentication state (passwords, MFA, sessions, tokens). The local `user` table stores only the `auth0_user_id` join key and application-level attributes (role, account membership). Never store credentials locally.

---

## Part 6: How the MCD Supports Each Use Case

### Use Case 1: Multi-Locale Pipelines

**Scenario**: France tenant (FR) and UK tenant (EN) both subscribe to London cocoa.

**How it works**:

1. Pipeline computes `signal` for London cocoa once (shared infra)
2. France tenant: `account.locale = 'fr'` → `signal_delivery.locale = 'fr'` → email says "COUVERTURE"
3. UK tenant: `account.locale = 'en'` → `signal_delivery.locale = 'en'` → email says "HEDGE"

Same signal, same algorithm, different presentation. The `content_snapshot` in `signal_delivery` stores what was actually sent, in the tenant's locale.

### Use Case 2: R&D Sandbox for New Commodities

**Scenario**: Testing sugar futures before launch.

**How it works**:

1. **Dev DB**: Insert `commodity` "sugar_11", configure `data_source`, add `indicator_definition` entries, run pipeline. Test freely — dev DB is isolated.
2. **Staging DB**: Promote schema + seed data via CI/CD. Internal team validates signals, runs backtests. No tenants in staging.
3. **Prod DB**: Insert `commodity` "sugar_11" in prod. Create `subscription` for beta tenants. Sugar signals start flowing.

Same schema across all three environments. No manual migration. A new commodity in dev never touches prod. Can run in parallel with production cocoa pipeline indefinitely.

### Use Case 3: Non-Technical Fine-Tuning Cockpit

**Scenario**: Operator wants to adjust RSI exponent from 1.813 to 1.5 and see the impact.

**How it works**:

1. Operator opens cockpit → sees `algorithm_version` "v6.3_actuel" with its `algorithm_config` rows
2. Clicks "Create New Version" → system duplicates all 19 config rows into "v6.3.1_test"
3. Operator changes `rsi_exponent` from 1.813 to 1.5 → `config_change_log` records old/new/who/when
4. Clicks "Run Backtest" → `backtest_run` created, results populate `backtest_result` + `performance_metric`
5. Operator compares metrics side-by-side → decides to promote or discard
6. If promoted: `algorithm_version.status` → "production", tenants pinned to "latest stable" auto-switch

**No code changes required.** Every parameter is a row. Every change is logged. Rollback = re-pin to previous version.

### Use Case 4: Per-User Feature Customization

**Scenario**: Tenant A on stable v6.3, Tenant B opts into beta v8 with term structure indicators.

**How it works**:

1. Tenant A: `account.algorithm_version_id` = v6.3_actuel → receives signals from v6.3
2. Tenant B: `account.algorithm_version_id` = test_v8 → receives signals from v8
3. Pipeline computes BOTH versions daily (for all commodities both versions serve)
4. `signal_delivery` routes the right signal to the right tenant

Combined with per-tenant `delivery_config`: Tenant A gets daily email, Tenant B gets realtime webhook + weekly podcast. Same underlying signal engine, completely different delivery experience.

### Use Case 5: Credit-Based On-Demand Billing

**Scenario**: Tenant buys a 100-credit pack for one-off use. Another tenant subscribes to a Pro plan (750/mo) with 1000 monthly credits. Both request reports and podcasts that consume credits.

**How it works**:

1. **One-time purchase**: Tenant pays 100 via Stripe Checkout → Stripe webhook fires → `webhook_event` logged → `credit_ledger` entry: `+100, type=purchase`
2. **Monthly subscription**: Billing cycle renews → Stripe webhook fires → `credit_ledger` entry: `+1000, type=allocation` (from `subscription.monthly_credits`)
3. **Consumption**: Tenant requests a podcast → system checks `credit_ledger` balance (`balance_after` on latest row) ≥ `output_type.credit_cost` (10 for podcast) → if sufficient, generates podcast, creates `signal_delivery`, creates `credit_ledger` entry: `-10, type=consumption, output_type_id=podcast`
4. **Insufficient credits**: Balance < cost → request rejected with clear message, tenant redirected to purchase page

**Key tables**: `reference.output_type` (catalog with costs), `tenant.credit_ledger` (immutable transaction log), `tenant.subscription.monthly_credits` (allocation amount per plan)

### Use Case 6: Multi-Horizon Trading Signals

**Scenario**: Client wants short-term daily signals for tactical hedging, mid-term weekly outlook for procurement planning, and long-term monthly view for strategic budgeting.

**How it works**:

1. Three `algorithm_version` entries for London cocoa: `v6.3_short` (horizon=short_term), `v2.1_mid` (horizon=mid_term), `v1.0_long` (horizon=long_term)
2. Each version has its own `feature_set` (short-term uses RSI/MACD/Bollinger; long-term uses moving averages/term structure/seasonal patterns)
3. Each version has its own `algorithm_config` with appropriate thresholds and normalization windows (252d for short, 504d for mid, 1260d for long)
4. Pipeline computes all three daily → three `signal` rows per commodity per date, each tagged with `horizon`
5. Tenant `delivery_config` specifies which horizons to receive: daily email for short_term, weekly digest for mid_term, monthly report for long_term

**Key tables**: `algorithm_version.horizon`, `signal.horizon` (denormalized), `delivery_config` (horizon-aware routing)

### Use Case 7: Categorized Fundamental Analysis

**Scenario**: For cocoa, the team runs separate analysis pipelines for supply fundamentals (crop reports, disease, weather), demand fundamentals (grindings data, consumption trends), and macro fundamentals (currency moves, trade policy).

**How it works**:

1. Text-based fundamentals (crop reports, trade news, regulatory changes) are ingested into `fundamental_article` with appropriate `category` values (`supply`, `demand`, `macro`, `geopolitical`)
2. Numeric grindings data (quarterly ICCO volumes by region) is ingested into `grindings_report` with structured columns
3. Per-category LLM prompts in the pipeline produce different `indicator_definition` entries: `supply_sentiment` (from supply articles), `demand_momentum` (from grindings + demand articles), `macro_risk` (from macro articles + FX data)
4. All derived indicators flow into `feature_value` via the EAV pattern — the algorithm consumes them identically regardless of source

**Key tables**: `fundamental_article.category`, `grindings_report` (numeric demand data), `indicator_definition` (category=fundamental), `feature_value` (EAV output)

---

## Part 7: Transition Path — From Spreadsheet to MCD

### What Maps Where

| Current (Google Sheets) | MCD Entity | Notes |
|---|---|---|
| TECHNICALS cols A-I (9 raw fields) | `raw_data.contract_data_daily` | Per-contract now, not per-commodity. OPEN price added. |
| TECHNICALS cols J-AT (36 indicators) | `features.feature_value` | EAV rows, not wide columns. 70-100+ scalable. |
| INDICATOR cols B-G (5-day averages) | Computed in pipeline, stored in `feature_value` | Smoothing window configurable via `indicator_definition` |
| INDICATOR cols H-M (z-scores) | `feature_value.normalized_value` | Rolling 252d, not full-history |
| INDICATOR col Q (FINAL) | `signals.signal.raw_score` | With algorithm_version traceability |
| INDICATOR col R (CONCLUSION) | `signals.signal.decision` | With threshold values preserved |
| CONFIG sheet (4 version columns) | `signals.algorithm_version` + `algorithm_config` | One version = one row + N param rows |
| HISTORIQUE sheet | `backtesting.backtest_run` + `backtest_result` + `performance_metric` | With proper train/test split |
| BIBLIO_ALL | `raw_data.fundamental_article` | Renamed, with `category` column for per-topic analysis |
| BIBLIO_ALL (grindings data) | `raw_data.grindings_report` | Numeric demand data split into dedicated table |
| METEO_ALL | `raw_data.weather_observation` | |
| PODCAST sheet | Replaced by `signal_delivery` + `credit_ledger` | Credit-gated output delivery |
| Make.com GPT-4 calls | `audit.llm_call` | Full prompt/response tracked |
| Sentry cron monitoring | `audit.data_ingestion_log` + `audit.pipeline_run` | Structured, queryable |
| Email delivery | `signals.signal_delivery` | Multi-channel, multi-tenant |

### What's New (The 17 Gap Corrections)

| # | Entity | Why It Was Missing | What It Enables |
|---|---|---|---|
| 1 | `contract_data_daily` (renamed) | Data was commodity-centric | Term structure, forward curve, roll yield |
| 2 | `fx_rate_daily` | FX rates don't fit market data or fundamentals | GBP/USD, USD/GHS as first-class data |
| 3 | `satellite_observation` | Structured numeric data ≠ LLM text | NDVI, rainfall as computable features |
| 4 | `feature_set` + `feature_set_member` | No concept of "which indicators feed which model" | Documented, versioned indicator selection |
| 5 | `llm_call` | No LLM audit trail | Provider A/B testing, EU AI Act compliance |
| 6 | `signal_delivery` | No delivery tracking | MiFID II proof of delivery, SLA tracking |
| 7 | `experiment_run` | GA optimization ≠ single backtest | Track 10M-iteration experiments as first-class entities |
| 8 | `data_quality_check` | No quality gates | Catch empty MACROECO, missing data, outliers before they cascade |
| 9 | `data_provider` (split) | Provider ≠ source (Barchart serves cocoa, sugar, coffee) | Clean provider management in cockpit |
| 10 | `contract_month` + `roll_rule` | Roll logic was hardcoded in scraper | Data-driven contract management |
| 11 | Normalization metadata on `feature_value` | Same RSI, multiple normalization methods | Reproducibility, method comparison |
| 12 | `trading_calendar` | No way to distinguish "scraper failed" from "market closed" | Correct quality checks, holiday-aware scheduling, accurate rolling windows |
| 13 | `indicator_dependency` | `depends_on UUID[]` had no FK enforcement | Referential integrity, topological sort for pipeline execution order |
| 14 | `webhook_event` | No audit trail for external state changes (Stripe, Auth0) | Idempotent sync, replay capability, billing/auth reconciliation |
| 15 | `output_type` + `credit_ledger` | No pay-per-use billing model | Credit-based monetization for on-demand outputs (reports, podcasts) |
| 16 | `algorithm_version.horizon` + `signal.horizon` | Only short-term signals supported | Multi-horizon signals (short/mid/long term) per commodity |
| 17 | `fundamental_article.category` + `grindings_report` | All fundamentals in one undifferentiated table | Per-topic analysis pipelines, structured numeric demand data |

### Phased Approach

**Phase 1 — Foundation (Weeks 1-3)**:
Deploy `reference` + `raw_data` + `audit` schemas. Migrate existing scrapers to write to PostgreSQL instead of Google Sheets. Validate data quality. No algorithm changes yet — just the data layer.

**Phase 2 — Computation (Weeks 4-6)**:
Deploy `features` + `signals` schemas. Reimplement the 4-layer pipeline in Python (FastAPI). Fix the 6 critical bugs. Add missing P0 indicators (SMA 50/200, MACD Signal/Histogram). Rolling 252d z-scores.

**Phase 3 — Backtesting & Cockpit (Weeks 7-9)**:
Deploy `backtesting` schema. Build cockpit UI for algorithm parameter management and data source configuration. Implement proper train/test split. Re-run GA with correct labels and normalization.

**Phase 4 — Multi-Tenant (Weeks 10-12)**:
Deploy `tenant` schema. Build subscription management, delivery engine, and locale support. Onboard first external tenant.

---

## Appendix A: Entity Count by Schema

| Schema | Entities | Tables |
|---|---|---|
| reference | 11 | commodity, exchange, contract_month, contract, roll_rule, trading_calendar, data_provider, data_source, indicator_definition, indicator_dependency, output_type |
| raw_data | 7 | contract_data_daily, fx_rate_daily, cot_report, weather_observation, satellite_observation, fundamental_article, grindings_report |
| features | 3 | feature_value, feature_set, feature_set_member |
| signals | 5 | algorithm_version, algorithm_config, signal, signal_component, signal_delivery |
| backtesting | 4 | backtest_run, backtest_result, performance_metric, experiment_run |
| audit | 5 | data_ingestion_log, pipeline_run, llm_call, data_quality_check, config_change_log |
| tenant | 8 | account, user, subscription, delivery_config, alert_rule, alert_event, webhook_event, credit_ledger |
| **Total** | **43** | |

## Appendix B: Key Indexes

| Table | Index | Purpose |
|---|---|---|
| contract_data_daily | `(date, contract_id)` UNIQUE | One row per contract per day |
| contract_data_daily | `(commodity_id, date)` | Term structure query |
| feature_value | `(date, commodity_id, indicator_id, version)` UNIQUE | Feature lookup (partition-ready) |
| feature_value | `(commodity_id, indicator_id, date)` | Time-series query per indicator |
| signal | `(date, commodity_id, algorithm_version_id)` UNIQUE | Signal lookup |
| signal_delivery | `(tenant_id, date)` | Tenant delivery history |
| signal_component | `(signal_id)` | Explainability query |
| fx_rate_daily | `(date, base_currency, quote_currency)` UNIQUE | Rate lookup |
| trading_calendar | `(exchange_id, date)` UNIQUE | Holiday/trading day lookup |
| indicator_dependency | `(indicator_id, depends_on_id)` UNIQUE | Dependency graph integrity |
| data_quality_check | `(date, commodity_id, status)` | Quality gate dashboard |
| config_change_log | `(entity_type, entity_id, changed_at)` | Audit trail |
| webhook_event | `(provider, event_id)` UNIQUE | Idempotent webhook processing |
| fundamental_article | `(date, commodity_id, category, url)` | Deduplicate articles per topic |
| grindings_report | `(report_date, commodity_id, region, period_type)` UNIQUE | One report per period per region |
| credit_ledger | `(account_id, created_at)` | Balance lookups per tenant (latest row = current balance) |
| signal | `(date, commodity_id, horizon)` | Multi-horizon signal lookup |

## Appendix C: Database Roles & Permissions

| Role | reference | raw_data | features | signals | backtesting | audit | tenant |
|---|---|---|---|---|---|---|---|
| **admin** | ALL | ALL | ALL | ALL | ALL | ALL | ALL |
| **pipeline** | SELECT | INSERT, SELECT | INSERT, SELECT | INSERT, SELECT | INSERT, SELECT | INSERT, SELECT | — |
| **cockpit** | SELECT, UPDATE (data_source, indicator_def) | — | SELECT | SELECT, UPDATE (algorithm_*) | SELECT | SELECT | SELECT |
| **tenant_api** | — | — | — | SELECT (via RLS) | — | — | SELECT, UPDATE (own account, via RLS) |

**External service roles** (not PG roles — application-level):
- **Stripe webhooks**: Write to `tenant.webhook_event`, update `tenant.account.tier` — validated via Stripe signature verification
- **Auth0 webhooks**: Write to `tenant.webhook_event`, insert/update `tenant.user` — validated via Auth0 signature verification

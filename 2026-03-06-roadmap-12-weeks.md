

# Commodities Compass — 12-Week Roadmap

> Source: `2MonthsPlanPriorities.docx` (2026-02-25)
> Generated: 2026-03-06
> Objective: Migrate off Railway + Google Sheets → fully owned GCP infrastructure with PostgreSQL as source of truth

---

## Current State

| Dimension | Status |
|---|---|
| Production maturity | 3/10 |
| Test coverage | 0/10 |
| Infrastructure | 2/10 |
| Users | 1 (Julien) |
| Revenue | $0 |
| Monthly cost | $30-80 on Railway |
| Data volume | 353 rows across 18 months |
| Source of truth | Google Sheets (7 scrapers write to Sheets, PostgreSQL is read-only replica) |
| Computation engine | Google Sheets (circular buffer, formula recalculation, read-back) |
| Orchestration | Make.com |
| Security findings | 14 HIGH-severity |

## Target State

| Dimension | Target |
|---|---|
| Source of truth | PostgreSQL on Cloud SQL |
| Computation | All in Python (NumPy) |
| Hosting | Cloud Run (GCP) |
| Google Sheets | Optional export (write-only) |
| Make.com | Fully decommissioned |
| CI/CD | GitHub Actions |
| IaC | Terraform |
| Tests | TDD from Phase 0.4 onward |

## Architecture Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Schema model | ~15 tables in `public` schema (prefixed names) | Not 40 tables / 7 schemas. Add schemas when distinct roles exist. |
| Indicator storage | Wide columns (NOT EAV) | 36 indicators, 353 rows. EAV complexity unjustified. Migrate to EAV at 100+. |
| Contract model | Contract-centric from day one | `pl_contract_data_daily` keyed on `(date, contract_id)`. Enables future term structure. |
| EU compliance | Deferred | No MiFID II / AI Act until selling signals to external clients. |
| Multi-tenant | Deferred | Add when second customer exists. |
| Migration strategy | Additive — new tables alongside old | No destructive migrations. Old 5 tables stay alive for backward API compat. |

---

## MVP Schema (~15 Tables)

### Reference (4 tables)

| Table | Purpose | Key Columns |
|---|---|---|
| `ref_commodity` | Commodity registry | `id`, `code`, `name`, `exchange_id` |
| `ref_exchange` | Exchange registry | `id`, `code`, `name`, `timezone` |
| `ref_contract` | Contract definition | `id`, `commodity_id`, `contract_month`, `roll_rule` |
| `ref_trading_calendar` | Trading days per exchange | `id`, `exchange_id`, `date`, `is_trading_day` |

### Pipeline (7 tables)

| Table | Purpose | Key Columns |
|---|---|---|
| `pl_contract_data_daily` | Raw OHLCV (replaces `technicals` cols A-I) | `id`, `date`, `contract_id`, `open`, `high`, `low`, `close`, `volume`, `oi`, `stock_us`, `com_net_us` |
| `pl_derived_indicators` | Wide columns for 36+ indicators | `id`, `date`, `contract_id`, `ema12`, `ema26`, `rsi`, `macd`, `stochastic_k`, `bollinger_upper`, ... |
| `pl_indicator_daily` | Z-scores + composite + decision | `id`, `date`, `contract_id`, `algorithm_version_id`, z-score cols, `composite_score`, `decision` |
| `pl_fundamental_article` | Press review + fundamentals (replaces `market_research`) | `id`, `date`, `category`, `source`, `title`, `summary`, `sentiment`, `llm_provider` |
| `pl_weather_observation` | Weather data (replaces `weather_data`) | `id`, `date`, `region`, `observation`, `impact_assessment` |
| `pl_algorithm_version` | Algorithm version tracking | `id`, `name`, `version`, `horizon` (default `short_term`), `is_active`, `created_at` |
| `pl_algorithm_config` | Coefficients per algo version | `id`, `algorithm_version_id`, `parameter_name`, `value` |

### Audit (3 tables)

| Table | Purpose | Key Columns |
|---|---|---|
| `aud_pipeline_run` | Pipeline execution log | `id`, `pipeline_name`, `started_at`, `finished_at`, `status`, `error` |
| `aud_llm_call` | LLM invocation audit | `id`, `pipeline_run_id`, `provider`, `model`, `prompt`, `response`, `tokens`, `cost_usd`, `latency_ms` |
| `aud_data_quality_check` | Data validation results | `id`, `pipeline_run_id`, `check_name`, `passed`, `details` |

### Signal (1 table)

| Table | Purpose | Key Columns |
|---|---|---|
| `pl_signal_component` | Per-indicator contribution to composite | `id`, `date`, `contract_id`, `indicator_name`, `raw_value`, `normalized_value`, `weighted_contribution` |

---

## Tasks by Phase

### Phase 0: Foundation

| ID | Task | Description | Depends On | Unblocks | Files | Risk | Est. |
|---|---|---|---|---|---|---|---|
| **0.1** | Fix P0 Security & Data Issues | Remove JWT header logging. Fix ETL rollback bug. Fix HTTPException swallowed by catch-all. Add `.dockerignore`. | — | Everything | `app/main.py`, `app/services/data_import.py`, `app/api/api_v1/endpoints/dashboard.py` | Low | 1d |
| **0.2** | GCP Project + Terraform Bootstrap | Create GCP project. Enable Cloud SQL, Cloud Run, Artifact Registry, Secret Manager, Cloud Scheduler. Terraform modules. Cloud SQL PostgreSQL 15. | — | 0.4, 1.2, 4.1 | New `infra/terraform/` | Cloud SQL private IP + Cloud Run SQL Auth Proxy connectivity | 2-3d |
| **0.3** | GitHub Actions CI/CD | Backend: Ruff lint, Pyright, pytest. Frontend: ESLint, `tsc --noEmit`, build. Docker build + push to AR. Cloud Run deploy on push to main. Decision: split Dockerfile (API ~200MB vs scraper ~1GB). | 0.2 | 0.4, all deploys | `.github/workflows/ci.yml`, `.github/workflows/deploy.yml` | Low | 2d |
| **0.4** | Minimal Test Harness | pytest fixtures for async DB sessions, factory functions. Frontend: Vitest + RTL setup. Goal: every subsequent task includes tests. | 0.3 | All subsequent tasks (TDD) | `backend/tests/conftest.py`, `backend/tests/factories.py`, `frontend/vitest.config.ts` | Low | 1-2d |

**Phase 0 total estimate: ~1 week**

---

### Phase 1: Schema Evolution + Historical Data

| ID | Task | Description | Depends On | Unblocks | Files | Risk | Est. |
|---|---|---|---|---|---|---|---|
| **1.1** | Design MVP Schema (~15 tables) | Define 15 tables (4 ref, 7 pipeline, 3 audit, 1 signal). All in `public` schema with prefixed names. Wide columns for indicators. Contract-centric keying. | — | 1.2 | Design doc | Low | 2d |
| **1.2** | Alembic Migration | Create new tables alongside existing ones. Old tables untouched. | 1.1, 0.2 | 1.3, all Phase 2 | `backend/alembic/versions/xxxx_add_mvp_tables.py` | Low | 1d |
| **1.3** | Seed Reference Data + Migrate Historical Data | One-time script: seed ref data (commodity, exchange, contracts, calendar 2024-2026). Migrate TECHNICALS A-I (353 rows) → `pl_contract_data_daily`. BIBLIO_ALL (200+ rows) → `pl_fundamental_article` (all with `category='macro'` initially). METEO_ALL (200+ rows) → `pl_weather_observation`. CONFIG (4 versions × 19 params) → `pl_algorithm_version` + `pl_algorithm_config`. | 1.2 | 3.1 | New `backend/scripts/migrate_historical_data.py` | Run `--dry-run` first, validate row counts | 2-3d |

**Phase 1 total estimate: ~1 week**

---

### Phase 2: Retarget Scrapers to PostgreSQL

> All 5 tasks run **in parallel** once 1.2 is done.
> Pattern: keep scraping logic, replace `sheets_writer.py` → `db_writer.py`, add `--also-sheets` flag for transition.

| ID | Task | Description | Depends On | Unblocks | Files | Risk | Est. |
|---|---|---|---|---|---|---|---|
| **2.1** | Barchart Scraper → PostgreSQL | INSERT to `pl_contract_data_daily`. Conflict handling on `(date, contract_id)`. | 1.2 | 3.1 | `scripts/barchart_scraper/main.py`, new `db_writer.py` | Low | 1d |
| **2.2** | ICE Stocks Scraper → PostgreSQL | UPDATE `stock_us` in `pl_contract_data_daily` for matching date. | 1.2 | — | `scripts/ice_stocks_scraper/main.py`, new `db_writer.py` | Row must exist from barchart — use upsert | 1d |
| **2.3** | CFTC Scraper → PostgreSQL | UPDATE `com_net_us` in `pl_contract_data_daily`. Weekly data, idempotent. | 1.2 | — | `scripts/cftc_scraper/main.py`, new `db_writer.py` | Low | 1d |
| **2.4** | Press Review Agent → PostgreSQL | INSERT to `pl_fundamental_article` with appropriate `category`. Also write to `aud_llm_call` per LLM invocation. | 1.2 | 3.3 | `scripts/press_review_agent/main.py`, replace `sheets_writer.py` | Low | 1-2d |
| **2.5** | Meteo Agent → PostgreSQL | INSERT to `pl_weather_observation`. Also write to `aud_llm_call`. | 1.2 | 3.3 | `scripts/meteo_agent/main.py`, replace `sheets_writer.py` | Low | 1d |

**Phase 2 total estimate: ~1 week (parallel execution)**

---

### Phase 3: Computation Engine — Kill Sheets as Compute

> **Critical path. Hardest phase.**
> `indicator_writer.py` (528 lines) gets replaced by ~50 lines of Python/NumPy.

| ID | Task | Description | Depends On | Unblocks | Files | Risk | Est. |
|---|---|---|---|---|---|---|---|
| **3.1** | Python Indicator Computation Engine | Implement 36 technical indicators in Python/NumPy. Read `pl_contract_data_daily`, write to `pl_derived_indicators`. **Groups:** Trivial (Pivots, ratios, daily return), Recursive (EMA12, EMA26, ATR Wilder), Composed (MACD, RSI, Stochastic), Windowed (Bollinger). Validate against 353 historical Sheets rows (rounding tolerance). | 1.3 | 3.2 | New `backend/app/engine/indicators.py` | **Highest-risk.** Known bugs: Bollinger STDEVP/STDEV, ATR EMA vs Wilder, Stochastic negative. Replicate existing first, fix in second pass. | 5-7d |
| **3.2** | Normalization + Composite Score Engine | Z-score normalization for 6 indicators (full-history first, configurable rolling 252d later). Composite formula: `FINAL_INDICATOR = INDICATOR + (MOMENTUM * 0.5)` where `INDICATOR = k + Σ(coeff × SIGN(x) × |x|^exp)`. Decision thresholds from CONFIG (0.9/-1.5 for ACTUEL). Implement `pl_signal_component`. | 3.1, 1.3 | 3.3 | New `backend/app/engine/normalization.py`, `backend/app/engine/composite.py` | MOMENTUM broken (`#REF!`). Implement correctly, add zero-out flag for parity. | 3-4d |
| **3.3** | Rewrite Daily Analysis Pipeline (No Sheets) | **Current:** Read Sheets → LLM #1 → Write INDICATOR → Wait Sheets recalc → Read back → LLM #2 → Write TECHNICALS. **New:** Read PostgreSQL → Compute indicators (3.1) → Normalize + composite (3.2) → LLM #1 → Apply macro bonus → Final + decision → LLM #2 → Write PostgreSQL + `aud_llm_call`. Entire `indicator_writer.py` (528 lines) disappears. | 3.1, 3.2, 2.4, 2.5 | 3.4, 4.1 | Rewrite `scripts/daily_analysis/analysis_engine.py`, replace `sheets_reader.py` → `db_reader.py`, replace `indicator_writer.py` → `signal_writer.py` | Dual-write during transition. Keep `--legacy-sheets` flag 2 weeks. | 3-5d |
| **3.4** | Rewrite Compass Brief (No Sheets) | Replace Sheets reader with DB reader. Brief generator and Drive uploader unchanged. | 3.3 | — | `scripts/compass_brief/main.py`, replace `sheets_reader.py` | Low | 1d |
| **3.5** | Kill Full-Refresh ETL | `data_import.py` (442 lines truncate + re-insert) becomes unnecessary. Keep as reconciliation tool during transition, then delete. | 3.3 | 4.2 | `app/services/data_import.py` | Low | 0.5d |

**Phase 3 total estimate: 2-3 weeks**

---

### Phase 4: Deploy to GCP + API Migration

NOte : Rotate/decommission legacy SAs: delete compromised key 842794b... on commodities-compass-sheets, replace with Terraform-managed cc-cloud-run-jobs SA for all Sheets/Drive access. Delete old SAs (commodities-compass-sheets, commodities-compass-data) once Cloud Run Jobs are live and validated.

| ID | Task | Description | Depends On | Unblocks | Files | Risk | Est. |
|---|---|---|---|---|---|---|---|
| **4.1** | Deploy Backend + Frontend to Cloud Run | Backend: Cloud Run, min 0/max 2, 512MB/1vCPU. Frontend: Cloud Run, nginx. Scrapers: Cloud Run Jobs + Cloud Scheduler. Cron migration (same times): `0 21`, `10 21`, `20 21`, `30 21` — all `* * 1-5`. | 0.2, 0.3, 3.3 | 4.2, 4.3, 5.1 | Split Dockerfiles, new Terraform modules | Auth0 callback URLs update. Playwright needs 2GB RAM on Cloud Run. | 2-3d |
| **4.2** | API Endpoints Read from New Tables | Update `dashboard_service.py` + `dashboard_transformers.py` to read from `pl_*` tables. API response shapes stay identical — frontend sees no change. | 3.5 | 5.5 | `app/services/dashboard_service.py` (345 lines), `app/services/dashboard_transformers.py` (275 lines) | Low | 2-3d |
| **4.3** | Security Hardening | Rate limiting (slowapi). Strip auth headers from logs. Restrict CORS. Add security headers. Verify HTTPS. | 4.1 | — | `app/main.py`, `app/core/auth.py` | Low | 1-2d |
| **4.4** | Optional Sheets Export for Julien | Cron job exports daily signal to Google Sheet (write-only). Same layout as current TECHNICALS + INDICATOR. Skip if Julien is happy with dashboard only. | 3.3 | — | New export script | Low | 1d |

**Phase 4 total estimate: ~1.5 weeks**

---

### Phase 5: Cutover + Cleanup

| ID | Task | Description | Depends On | Unblocks | Files | Risk | Est. |
|---|---|---|---|---|---|---|---|
| **5.1** | Parallel Run + Validation | Both Railway and GCP run simultaneously (1-2 weeks). Nightly script compares: raw inputs match, indicators match within tolerance, decisions match. Alert on discrepancies. | 4.1 | 5.2, 5.5 | New `backend/scripts/validation/compare_pipelines.py` | Discrepancies require debugging | 1-2w |
| **5.2** | Kill Railway | DNS cutover. Disable Railway crons. Monitor 48h. Keep account 1 month for rollback. | 5.1 | 5.3 | — | Rollback if issues | 1d |
| **5.3** | Kill Google Sheets as Source of Truth | Remove all Sheets read/write code. Delete `app/core/excel_mappings.py`, `app/services/data_import.py`. Clean dependencies. | 5.2 | — | Multiple files deleted | Irreversible — validate thoroughly | 1d |
| **5.4** | Decommission Make.com | Verify and disable remaining scenarios. Implement email sender if needed (`email_sender.py`: Not Yet Implemented). | 3.3 | — | — | Low | 1d |
| **5.5** | Drop Legacy Tables | Backup old tables to GCS. Alembic migration drops `technicals`, `indicator`, `market_research`, `weather_data`, `test_range`. | 4.2, 5.1 | — | Alembic migration | Backup first | 0.5d |

**Phase 5 total estimate: ~2-3 weeks (dominated by parallel run validation)**

---

## Critical Path

```
0.2 → 1.1 → 1.2 → 1.3 → 3.1 → 3.2 → 3.3 → 4.1 → 5.1 → 5.2
```

Any delay on this chain delays the entire project. All other tasks are either parallel or off the critical path.

## Dependency Graph

```
Phase 0: 0.1 ──────────────────────────────────────────────────┐
         0.2 ──┬── 0.3 ── 0.4                                 │
               │                                               │
Phase 1: 1.1 ──┤                                               │
         1.2 ──┤                                               │
         1.3 ──┤                                               │
               │                                               │
Phase 2: 2.1 ──┤ (all 5 parallel after 1.2)                    │
         2.2 ──┤                                               │
         2.3 ──┤                                               │
         2.4 ──┤                                               │
         2.5 ──┤                                               │
               │                                               │
Phase 3: 1.3 → 3.1 → 3.2 → 3.3 → 3.4     (critical path)     │
         2.4 + 2.5 ────────→ 3.3                               │
         3.3 → 3.5                                             │
                                                               │
Phase 4: 3.3 + 0.3 → 4.1                                      │
         3.5 → 4.2                                             │
         4.1 → 4.3                                             │
         3.3 → 4.4 (optional)                                  │
                                                               │
Phase 5: 4.1 → 5.1 → 5.2 → 5.3                               │
         3.3 → 5.4                                             │
         4.2 + 5.1 → 5.5                                      │
```

---

## Timeline Summary

| Phase | Name | Duration | Weeks |
|---|---|---|---|
| 0 | Foundation | ~1 week | W1 |
| 1 | Schema Evolution + Historical Data | ~1 week | W2 |
| 2 | Retarget Scrapers | ~1 week (parallel) | W3 |
| 3 | Computation Engine | 2-3 weeks | W4-W6 |
| 4 | Deploy to GCP + API Migration | ~1.5 weeks | W7-W8 |
| 5 | Cutover + Cleanup | 2-3 weeks | W9-W11 |
| — | Buffer | 1 week | W12 |
| **Total** | | **~10-12 weeks** | |

---

## Task Checklist (Flat List — 24 Tasks)

| # | ID | Task | Phase | Status |
|---|---|---|---|---|
| 1 | 0.1 | Fix P0 Security & Data Issues | 0 | `[x]` |
| 2 | 0.2 | GCP Project + Terraform Bootstrap | 0 | `[x]` |
| 3 | 0.3 | GitHub Actions CI/CD | 0 | `[x]` |
| 4 | 0.4 | Minimal Test Harness | 0 | `[x]` (198 tests, 61% coverage) |
| 5 | 1.1 | Design MVP Schema (~15 tables) | 1 | `[x]` |
| 6 | 1.2 | Alembic Migration | 1 | `[x]` |
| 7 | 1.3 | Seed Reference Data + Migrate Historical Data | 1 | `[x]` |
| 8 | 2.1 | Barchart Scraper → PostgreSQL | 2 | `[x]` |
| 9 | 2.2 | ICE Stocks Scraper → PostgreSQL | 2 | `[x]` |
| 10 | 2.3 | CFTC Scraper → PostgreSQL | 2 | `[x]` |
| 11 | 2.4 | Press Review Agent → PostgreSQL | 2 | `[x]` |
| 12 | 2.5 | Meteo Agent → PostgreSQL | 2 | `[x]` |
| 13 | 3.1 | Python Indicator Computation Engine | 3 | `[x]` (87 tests, 9 bug fixes vs Sheets) |
| 14 | 3.2 | Normalization + Composite Score Engine | 3 | `[x]` |
| 15 | 3.3 | Rewrite Daily Analysis Pipeline (No Sheets) | 3 | `[x]` |
| 16 | 3.4 | Rewrite Compass Brief (No Sheets) | 3 | `[x]` |
| 17 | 3.5 | Kill Full-Refresh ETL | 3 | `[x]` (data_import.py + excel_mappings.py deleted 2026-04-01) |
| 18 | 4.1 | Deploy Backend + Frontend to Cloud Run | 4 | `[x]` |
| 19 | 4.2 | API Endpoints Read from New Tables | 4 | `[x]` (USE_NEW_TABLES removed, pl_* only) |
| 20 | 4.3 | Security Hardening | 4 | `[x]` (rate limiting, security headers, CORS) |
| 21 | 4.4 | Optional Sheets Export for Julien | 4 | `[—]` (skipped — not needed) |
| 22 | 5.1 | Parallel Run + Validation | 5 | `[x]` (dual-write validated 2026-03-24 → 2026-03-30) |
| 23 | 5.2 | Kill Railway | 5 | `[x]` (crons stopped 2026-03-30) |
| 24 | 5.3 | Kill Google Sheets as Source of Truth | 5 | `[x]` (19 files deleted, 3,939 lines removed 2026-04-01) |
| 25 | 5.4 | Decommission Make.com | 5 | `[x]` (already off) |
| 26 | 5.5 | Drop Legacy Tables | 5 | `[ ]` (deferred — dump first, drop later) |

---

## Verification Criteria

| Phase | Criteria |
|---|---|
| 0 | CI green. Cloud SQL accessible. P0 fixes deployed. |
| 1 | New tables exist. Historical data loaded. Row counts match Sheets. |
| 2 | Each scraper writes to PostgreSQL. `--also-sheets` produces identical data. |
| 3 | Python indicators match Sheets within 0.01% for 353 rows. Pipeline runs end-to-end without Sheets. |
| 4 | Dashboard loads all widgets from new tables. Security headers present. |
| 5 | Railway off. Sheets optional. Make.com disabled. Cloud Scheduler running. Sentry green. |

---

## What This Enables Post-12 Weeks

| Capability | Status After 12 Weeks | Next Step |
|---|---|---|
| Contract-centric model | Done | Add contracts for term structure |
| Algorithm versioning | Done | Add cockpit UI |
| LLM call auditing | Done | Add cost tracking |
| Trading calendar | Done | Automate calendar sync |
| Signal decomposition | Done | Add to dashboard UI |
| Wide columns | Done | Migrate to EAV at 100+ indicators |
| Single schema | Done | Split to PG schemas when adding roles |
| Multi-commodity | Foundation ready | Add second commodity |
| Multi-tenant | Not started | Add when first client signs |
| EU compliance | Not started | Add when selling signals |
| Stripe billing | Not started | Add when monetizing |
| Credit-based billing | Not started | Add `output_type` + `credit_ledger` when monetizing (MCD ready) |
| Multi-horizon signals | Foundation ready (`horizon` column exists, default `short_term`) | Add mid/long-term algorithm versions |
| Categorized fundamentals | Foundation ready (`category` column exists) | Add per-category LLM prompts + `grindings_report` table |

---

## Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| Indicator parity failure (3.1) | High — blocks Phase 3+ | Medium | Replicate existing bugs first, fix in second pass. Allow rounding tolerance. |
| MOMENTUM `#REF!` (3.2) | Medium | Certain | Implement correctly, add zero-out flag for parity testing. |
| Cloud SQL connectivity (0.2) | High — blocks deploys | Low | Test SQL Auth Proxy early in Phase 0. |
| Playwright RAM on Cloud Run (4.1) | Medium | Medium | Use 2GB instance for scraper jobs only. |
| Dual-write drift (3.3) | Medium | Medium | `--legacy-sheets` flag + nightly comparison script (5.1). |
| Auth0 callback URLs (4.1) | Low | Certain | Update Auth0 config before DNS cutover. |

---

## Parallel Run Status (updated 2026-03-24)

### Dual-Write Pipeline Audit

| Step | Cron (UTC) | Sheets | DB (`pl_*`) | Dual? |
|---|---|---|---|---|
| Barchart scraper | `0 21 * * 1-5` | Write TECHNICALS A-G | Write `pl_contract_data_daily` | Yes (automatic) |
| ICE stocks scraper | `10 21 * * 1-5` | Write TECHNICALS col H | Write `pl_contract_data_daily` | Yes (automatic) |
| CFTC scraper | `10 21 * * 1-5` | Write TECHNICALS col I | Write `pl_contract_data_daily` | Yes (automatic) |
| Press review agent | `10 21 * * 1-5` | Write BIBLIO_ALL | Write `pl_fundamental_article` | Yes (automatic) |
| Meteo agent | `10 21 * * 1-5` | Write METEO_ALL | Write `pl_weather_observation` | Yes (automatic) |
| Compute indicators | `15 21 * * 1-5` | N/A | Write `pl_derived_indicators` etc. | Added 2026-03-24 |
| Daily analysis (Sheets) | `20 21 * * 1-5` | Write INDICATOR + TECHNICALS AO-AR | N/A | Existing Railway cron |
| Daily analysis (DB) | `25 21 * * 1-5` | N/A | Write `pl_indicator_daily` (LLM fields) | Added 2026-03-24 |
| Compass brief | `30 21 * * 1-5` | Read all 4 sheets | N/A | Reads Sheets only (spot-check `--db`) |
| ETL import | `15 22 * * 1-5` | Read all 5 sheets → legacy tables | N/A | Existing Railway cron |

### Full Parallel Run — ACTIVE (since 2026-03-24)

Both crons added to Railway. The full pipeline now runs nightly in parallel with zero manual intervention.

```
21:00  Barchart scraper        → Sheets + pl_contract_data_daily         (dual-write)
21:10  ICE/CFTC scrapers       → Sheets + pl_contract_data_daily         (dual-write)
21:10  Press review agent      → Sheets + pl_fundamental_article          (dual-write)
21:10  Meteo agent             → Sheets + pl_weather_observation          (dual-write)
21:15  compute-indicators      → pl_derived_indicators + pl_indicator_daily + pl_signal_component
21:20  daily-analysis --sheet  → INDICATOR sheet + TECHNICALS AO-AR      (Sheets formulas, broken computing)
21:25  daily-analysis --db     → pl_indicator_daily (LLM fields)          (Python engine, 9 bug fixes)
21:30  compass-brief           → Google Drive                             (reads Sheets; spot-check --db)
22:15  ETL import              → Legacy Railway tables                    (feeds dashboard API until 4.2)
```

**Two parallel signal pipelines:**

| Dimension | Sheets Pipeline (legacy) | DB Pipeline (new) |
|---|---|---|
| Raw data source | Google Sheets TECHNICALS | `pl_contract_data_daily` (GCP Cloud SQL) |
| Indicator computation | Google Sheets formulas | Python/NumPy engine (`app/engine/`) |
| Known bugs | 9 (Wilder RSI/ATR, Bollinger, Stochastic, look-ahead z-scores) | All 9 fixed |
| Algorithm config | Hardcoded in Sheets formulas | `pl_algorithm_config` rows (legacy v1.0.0, `is_active=true`) |
| LLM analysis | `daily-analysis --sheet` (gpt-4-turbo) | `daily-analysis --db` (gpt-4-turbo) |
| Output | INDICATOR sheet + TECHNICALS AO-AR | `pl_indicator_daily` (decision, confidence, direction, eco) |
| Dashboard reads | Legacy tables (via ETL import at 22:15) | Not yet (blocked by task 4.2) |
| Data integrity | Mutable (STOCK US overwritten by later runs) | Immutable (original scraper values preserved) |

**Only manual step remaining:** contract rolls. When active contract changes (e.g., CAK26 → CAN26), update `ACTIVE_CONTRACT` env var on all scraper services AND the `--contract` arg on the `daily-analysis-db` cron. This happens ~5 times/year (delivery months H/K/N/U/Z).

### Integration Test Report (2026-03-24)

Ran `compass-brief --db --dry-run` and compared output against `compass-brief` (Sheets mode).

**Bugs found and fixed during integration test:**

| Bug | File | Severity | Root Cause | Fix |
|---|---|---|---|---|
| `tokens_input`/`tokens_output` column mismatch | `db_analysis_engine.py` | Blocker | Code used wrong column names vs DB schema | Renamed to `input_tokens`/`output_tokens` |
| FK violation on `aud_llm_call` insert | `db_analysis_engine.py` | Blocker | Missing parent `aud_pipeline_run` row | Added `INSERT INTO aud_pipeline_run` before LLM audit writes |
| Wrong `pl_indicator_daily` row selected | `compass_brief/db_reader.py` | Data integrity | `ORDER BY created_at DESC` picked compute-indicators row (no LLM fields) over daily-analysis row | Added `JOIN pl_algorithm_version WHERE is_active = true` filter |
| Number formatting (`2414.000000`, `0.3634`) | `compass_brief/db_reader.py` | Cosmetic | `_fmt()` was bare `str()` | Added type-aware formatting: int, dec2, pct, etc. |

**Comparison result after fixes:**
- Structure: identical (all sections present in both briefs)
- Formatting: matches (confidence `4/5`, prices as integers, IV as percentage)
- Indicator values: differ as expected (engine fixes 9 Sheets bugs: Wilder's RSI/ATR, symmetric Bollinger, rolling z-scores, correct Stochastic bounds)
- Decision: HEDGE (DB) vs MONITOR (Sheets) — driven by corrected indicator values
- LLM text: different phrasing (expected — different input values, non-deterministic LLM)
- STOCK US data: DB has correct original value (162,851) vs Sheets overwritten value (163,497) — validates immutable raw data principle

### Sheets Dependency Map (for Phase 5.3 deletion)

**Files to DELETE (17 files, ~1,500 lines):**

```
app/services/data_import.py              (442 lines — full-refresh ETL)
app/core/excel_mappings.py               (100+ lines — column mappings)
scripts/barchart_scraper/sheets_writer.py
scripts/barchart_scraper/config.py
scripts/ice_stocks_scraper/sheets_manager.py
scripts/ice_stocks_scraper/config.py
scripts/cftc_scraper/sheets_manager.py
scripts/cftc_scraper/config.py
scripts/press_review_agent/sheets_writer.py
scripts/press_review_agent/sheets_reader.py
scripts/press_review_agent/config.py
scripts/meteo_agent/sheets_writer.py
scripts/meteo_agent/config.py
scripts/daily_analysis/sheets_reader.py
scripts/daily_analysis/indicator_writer.py  (528 lines — formula row-shift)
scripts/compass_brief/sheets_reader.py
scripts/compass_brief/config.py
```

**Files to UPDATE (remove `--sheet` flag, make `--db` default):**

```
scripts/barchart_scraper/main.py
scripts/ice_stocks_scraper/main.py
scripts/cftc_scraper/main.py
scripts/press_review_agent/main.py
scripts/meteo_agent/main.py
scripts/daily_analysis/main.py           (remove Sheets mode entirely)
scripts/compass_brief/main.py            (remove Sheets mode)
app/core/config.py                       (remove SPREADSHEET_ID, Sheets creds)
pyproject.toml                           (remove `poetry run import`)
```

**What STAYS (Google Drive, not Sheets):**

```
scripts/compass_brief/drive_uploader.py  (uploads .txt to Drive for NotebookLM)
app/services/audio_service.py            (streams audio from Drive)
google-api-python-client dependency      (still needed for Drive)
```

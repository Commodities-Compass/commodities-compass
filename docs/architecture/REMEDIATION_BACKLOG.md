# Remediation Backlog — Stale Comments, Doc Drift & Dead Code

> **AUDIT-ONLY** — this is a prioritized to-do list for separate PRs. Nothing here has been fixed. Each item is a verified finding (stale comment, doc drift, dead/obsolete code, or dangling reference) with a recommended action.
>
> Generated: 2026-06-18. Line numbers reflect the state of the codebase at audit time and may shift as files change.
>
> **Kinds**: `doc_drift` (docs/README/docstring contradicts live code) · `stale_comment` (inline comment wrong) · `dead_code` (unreachable / never-raised) · `dangling_reference` (points to a file/doc that doesn't exist) · `incorrect_reference` (points to the wrong source).
>
> **Actions**: `update-doc` (correct the prose) · `fix` (correct comment/code-level naming or value) · `delete` (remove the stale block/file/flag entirely).

---

## HIGH severity

These mislead about production data flows (Sheets-vs-DB, table targets), claim live code is orphaned, or hide a real defensive-check gap. Highest risk of operator/maintainer error.

### `backend/app/models/pipeline.py`

- **L335 / L338** — `doc_drift` — `pl_article_segment` is annotated "MODEL-ONLY … extraction pipeline lives on `feat/pattern-extractor`; can be dropped if branch never merges." That branch doesn't exist and the table is production-live: written daily by `press_review_agent` (19:05 cron), read by `dashboard_service.get_theme_sentiments()` and `compute_sentiment_features`. → **Action: delete the orphan/MODEL-ONLY claim** (per L335 finding); at minimum **update-doc** to describe it as a core production model (per L338 finding). Reconcile the two overlapping comment blocks into one accurate note.

### `backend/app/services/dashboard_service.py`

- **L764** — `stale_comment` — `SIGNAL_THEMES = {"production", "chocolat"}` omits the two other live themes. Press-review config supports 4 (`production`, `chocolat`, `economie`, `transformation`); frontend `sentiment-gauges.tsx` maps all 4. New segments with the missing themes silently get `has_signal=false` with no error or log. → **Action: fix** — add `transformation` and `economie` (verify against `press_review_agent/config.py` as source of truth).

### `backend/scripts/barchart_scraper/validator.py`

- **L18** — `stale_comment` — "Validates scraped data before writing to **Sheets**." Writer (`db_writer.py`) writes to PostgreSQL `pl_contract_data_daily`; Sheets is no longer a data source. → **Action: fix** — change "Sheets" to "`pl_contract_data_daily` (PostgreSQL)".

### `backend/scripts/barchart_scraper/config.py`

- **L18-L20** — `doc_drift` — docstring claims env-var fallback gives "graceful degradation if DB unavailable", but `resolve_active_code()` raises `ContractResolverError` (no active contract) which is NOT caught by the `(OSError, ConnectionError)` / `(OperationalError, InterfaceError)` except clauses (L38, L46-49) — it propagates uncaught before the env-var fallback is reached. The fallback only covers transient network errors. → **Action: update-doc** to state the fallback covers only transient connection errors and that `ContractResolverError` is uncaught (optionally fix the code to also catch it — but the docstring must match actual behavior either way).

### `backend/scripts/barchart_stocks_eu_scraper/backfill.py`

- **L73-L80** — `doc_drift` — docstring says it "UPDATEs the matching rows in `pl_contract_data_daily`", but L97 calls `update_stock_eu()` which writes to `pl_stock_observation` (region='eu') since migration `r2m3n4o5p6q7` (2026-05-27). → **Action: fix** — correct the target table to `pl_stock_observation`.

### `backend/scripts/ice_stocks_scraper/README.md`

- **L3** — `doc_drift` — claims dual-write to "GCP Cloud SQL (`pl_contract_data_daily.stock_us`) **and Google Sheets** column H". Current writer hits only `pl_stock_observation` (region='us', source='ice_us_report41'); no Sheets code. → **Action: update-doc**.
- **L29-L39** — `doc_drift` — directory listing includes `sheets_manager.py` and `run_scraper.sh`; neither exists (actual: `__init__.py`, `config.py`, `db_writer.py`, `main.py`, `README.md`, `scraper.py`). → **Action: fix** — correct the file listing.
- **L45-L55** — `doc_drift` — data-flow steps describe writing to `pl_contract_data_daily.stock_us` and "Google Sheets TECHNICALS column H". Code writes only to `pl_stock_observation` (region='us'). → **Action: update-doc**.
- **L111-L115** — `doc_drift` — claims it "Updates `stock_us` on the most recent `pl_contract_data_daily` row for the active contract (via `ref_contract.is_active`)". Refactored 2026-05-27: writer calls `upsert_stock_observation()` with explicit region/report_date/contract_market on `pl_stock_observation`. → **Action: update-doc**.

### `backend/scripts/cftc_scraper/README.md`

- **L7** — `doc_drift` — "Dual-write: GCP Cloud SQL (`pl_contract_data_daily.com_net_us`) and Google Sheets". Refactored 2026-05-27: UPSERTs one row per real CFTC release into `pl_cot_us_weekly`; the per-weekday overwrite of `com_net_us` is gone; no Sheets. → **Action: delete** the dual-write claim and rewrite the overview to `pl_cot_us_weekly` UPSERT semantics.
- **L45-L53** — `doc_drift` — step list ends with "update `com_net_us` on latest `pl_contract_data_daily` row" + "Update column I" (Sheets). Actual: `upsert_cot_us_weekly()` UPSERT on `(release_date, contract_market)`. → **Action: update-doc**.
- **L127-L130** — `doc_drift` — "Updates `com_net_us` on the most recent `pl_contract_data_daily` row for the active contract (via `ref_contract.is_active`)". Actual: UPSERT to `pl_cot_us_weekly`; no `ref_contract` query, no `pl_contract_data_daily` update. → **Action: update-doc**.

### `CLAUDE.md`

- **L204** — `doc_drift` — "All scrapers write to `pl_contract_data_daily`." Since migration `r2m3n4o5p6q7` (2026-05-27) only Barchart does; others write to `pl_stock_observation`, `pl_cot_*_weekly`, `pl_supply_demand_observation`, `pl_external_indicator`. → **Action: update-doc**.
- **L324-L330** — `doc_drift` — ASCII diagram shows `stock_us` / `com_net_us` columns on `pl_contract_data_daily` with `(update)` semantics. Those columns no longer exist on the model; data lives in `pl_stock_observation` / `pl_cot_us_weekly` with UPSERT-on-report_date semantics. → **Action: update-doc** — redraw the diagram.

### `backend/scripts/daily_analysis/README.md`

- **L5-L6** — `doc_drift` — documents both `--db` and `--sheet` modes as active. `main.py` defines neither; L163 says "DB-first pipeline (no Sheets dependency)" and runs `_run_db_pipeline()` unconditionally. Sheets mode is dead. → **Action: delete** the dual-mode documentation.
- **L116-L137** — `doc_drift` — every CLI example references the non-existent `--sheet` flag (e.g. `--sheet staging --dry-run`) plus other phantom flags (`--inspect`, `--indicator-only`, `--macroeco-bonus`, `--eco`). → **Action: delete/rewrite** examples to the real flags (`--contract`, `--date`, `--dry-run`, `--force`, `--verbose`, `--llm-provider`, `--llm-model`, `--algorithm-version`).
- **L140-L154** — `doc_drift` — CLI flags table lists flags that no longer exist (`--sheet`, `--inspect`, `--indicator-only`, `--macroeco-bonus`, `--eco`). → **Action: delete** the obsolete rows and rebuild the table from current argparse.

### `backend/scripts/compass_brief/README.md`

- **L5** — `doc_drift` — "Default mode (legacy): Reads from Google Sheets." Sheets reader removed in commit `dba4072` (2026-04-01); `main.py` unconditionally uses `DBBriefReader`; no `--db` flag exists. → **Action: delete** — rewrite overview to "reads exclusively from `pl_*` tables; Sheets support removed 2026-04-01".
- **L32** — `doc_drift` — CLI examples use non-existent `--db` flag and a "Sheets mode" variant. → **Action: delete** — replace with current-only examples (`--dry-run`, `--output`, `--verbose`, `--force`, `--target-date`).
- **L45** — `doc_drift` — CLI flags table row `| --db | off | Read from pl_* instead of Google Sheets |`; flag doesn't exist. → **Action: delete** that row; rebuild table from current argparse.
- **L81-L87** — `doc_drift` — pipeline-schedule block uses 21:XX UTC times and Sheets table names (`TECHNICALS`, `BIBLIO_ALL`, `METEO_ALL`, `INDICATOR`). Actual: 19:XX UTC, reads `pl_contract_data_daily` / `pl_indicator_daily` / `pl_fundamental_article` / `pl_weather_observation`. → **Action: update** — fix times and table names, or replace with a reference to CLAUDE.md.
- **L110** — `doc_drift` — module-structure diagram lists `sheets_reader.py` (deleted in `dba4072`, 2026-04-01). → **Action: delete** that line from the diagram.

---

## MEDIUM severity

Wrong-but-bounded: cron mismatches, dangling US-doc references, a real missing runtime check, narrative-routing drift, naming artifacts that confuse navigation, and shared-suffix duplication.

### `backend/scripts/ensemble_compute/main.py`

- **L133-L143** — `missing-defensive-check` — `_resolve_algorithm_version_id()` resolves `ensemble_v1_softgate_wrapper` by name and returns the UUID with **no `compute_enabled=TRUE` check** (contrast `engine/runner.py` `load_compute_enabled_versions()`). Memory note `project_c5_ensemble_compute_enabled_state.md` says this version is intentionally `compute_enabled=FALSE` in prod; this job will write rows even when the algorithm is disabled. → **Action: fix** — validate `compute_enabled` (or document why this job is exempt) before writing. *(Confirm desired behavior against the compute-enabled-state memory note before implementing.)*

### `backend/app/api/api_v1/endpoints/dashboard.py`

- **L335-L339** — `doc_drift` — comment says recommendation narrative "always comes from the legacy LLM job, even when ensemble produced the decision." Superseded by commit `ac85844` (2026-05-27): `cc-ensemble-explainer` (thin wrapper around `DBAnalysisEngine` auto-align) now writes the narrative to the ensemble row and aligns decision to `decision_wrapped`. On ensemble dates both decision and narrative are ensemble-sourced. → **Action: update-doc**.

### `backend/app/services/dashboard_service.py`

- **L138** — `stale_comment` — function named `get_position_from_technicals(...)` but it queries `PlIndicatorDaily` (`pl_*`), not the legacy `Technicals` model — naming artifact from the pre-`pl_*` migration. → **Action: fix** — rename the function (and call sites) to reflect the `pl_indicator_daily` source.

### `backend/app/services/audio_service.py`

- **L28-L31** — duplication — `_VERSION_FILENAME_SUFFIX = {'legacy': '', 'ensemble': '-Ensemble'}` is the only shared source of truth but the `-Ensemble` suffix is independently hardcoded in 4 other places: `endpoints/audio.py` L61 & L233, `endpoints/dashboard.py` L656, `compass_brief_ensemble/config.py` L22. A suffix change would require 5 edits. → **Action: fix** — extract a single shared constant (e.g. `app/services/brief_constants.py: BRIEF_VERSION_SUFFIX`) and import everywhere.

### `backend/app/core/config.py`

- **L58-L60** — config-validation gap — `BRIEF_DEFAULT_VERSION` loaded with `default='legacy'` and **no membership validation**. An invalid value (`'typo'`, `'ensemble_old'`) boots fine and only fails later at the first `/dashboard/audio` request when `_normalize_version()` raises. → **Action: fix** — validate at boot (Pydantic validator or init hook calling `_normalize_version(...)`) so a misconfigured deploy fails loud at startup.

### `backend/scripts/ensemble_explainer/main.py`

- **L118-L139** — fragile raw SQL — pre-flight uses `text(...)` raw SQL. A future rename of `ref_contract.code` / `pl_algorithm_version.name`/`.version` would silently return 0 rows and surface as a misleading `EnsembleRowMissingError` instead of a column-not-found error. → **Action: fix** — convert to an ORM query (join + filter) so column drift is caught at construction, or add explicit migration-dependency comments above the query.

### `backend/app/models/pipeline.py`

- **L69-L71** — `incorrect statement` — "Display date … Dashboard queries **filter by** this column." False: `dashboard.py` `_parse_and_validate_date()` uses `display_date` only as a one-way lookup to resolve `session_date`; all downstream queries key on `session_date`. → **Action: update-doc** — describe `display_date` as a resolution index, not a filter column.

### `backend/scripts/daily_analysis/main.py`

- **L47-L49** — oversimplified comment — "Default: `next_session_date(today)` … writes tagged to the upcoming trading session." Omits the P2b two-step transform: `target_date = next_session`, but `check_date = previous_session(target_date)` and the actual DB writes key to that previous session. → **Action: update-doc** — document the two-step date transform.

### `backend/scripts/enso_scraper/__init__.py`

- **L4** — `dangling_reference` — docstring points to `docs/user-stories/P1-scraper-enso.md`, which doesn't exist; `README.md` is authoritative. → **Action: fix** — repoint to the README (or remove the dangling link).

### `backend/scripts/fx_scraper/__init__.py`

- **L4** — `dangling_reference` — docstring points to `docs/user-stories/P1-scraper-fx.md`, which doesn't exist; `README.md` is authoritative. → **Action: fix** — repoint to the README (or remove the dangling link).

### `backend/scripts/compass_brief/brief_generator.py`

- **L4** — `doc_drift` — docstring "Works with both Sheets and DB data sources." `sheets_reader.py` deleted in commit `dba4072` (2026-04-01); only `db_reader.py` remains. → **Action: fix** — rewrite to "reads exclusively from PostgreSQL (Sheets reader removed 2026-04)".

### `backend/scripts/compass_brief/README.md`

- **L75** — `doc_drift` — cron documented as `30 21 * * 1-5` (9:30 PM UTC). CLAUDE.md (authoritative) has `cc-compass-brief` at 19:30 (7:30 PM UTC). 2-hour drift. → **Action: update** — change to `30 19` / 7:30 PM UTC.
- **L119** — `doc_drift` — documents a `### DB mode (--db)` flag; no `--db` arg exists, `DBBriefReader` is the unconditional default. → **Action: update-doc** — remove the `--db` flag docs; state DB is the only mode.
- **L128-L136** — `doc_drift` — "Legacy Sheets mode" section documents Sheet ranges (`TECHNICALS`, `INDICATOR`, `BIBLIO_ALL`, `METEO_ALL`) the running code never reads (no `sheets_reader.py`). → **Action: delete** the section.

### `backend/alembic/versions/n8i9j0k1l2m3_create_v_contract_data_chained.py`

- **L20-L21** — obsolete statement — "Frontend / dashboard read path is untouched (still queries `pl_contract_data_daily` directly via `contract_id` filters)." Dashboard resolves `display_date → session_date` then keys queries by session date via `resolve_contract_for_date`; it does not query `pl_contract_data_daily` directly by `contract_id` as described. → **Action: update-doc** (migration comment; cosmetic only, the migration itself is correct).

### `backend/app/engine/runner.py`

- **L8-L9** — `stale_comment` — module docstring presents `--all-versions` as "All compute-enabled versions (nightly cron mode)". The documented nightly job (`cc-compute-indicators`, 19:15) does not use `--all-versions`; that mode is for testing/backfill. → **Action: update-doc** — reframe `--all-versions` as a testing/backfill mode, not the nightly production pattern.

### `backend/app/utils/contract_resolver.py`

- **L159-L163** — `doc_drift` — rationale docstring hardcodes "ensemble has only 105 dates (2025-12-15 → 2026-05-21)". As of 2026-06-18 ensemble runs past that end date (active June tuning), so both the row count and the end date are stale. The underlying anti-backfill-bias rationale remains valid. → **Action: update-doc** — drop the point-in-time count/end-date; keep the rationale. *(Two findings, low + medium severity, target the same lines — treated as one edit at the higher severity.)*

### `backend/app/schemas/dashboard.py`

- **L449-L450** — `doc_drift` — docstring lists only `pre-2025-12-15` as the 404 case for the ensemble endpoint and implies a fixed range ending earlier. Ensemble still computes daily as of 2026-06-18; future dates are also a 404 case. → **Action: update-doc** — describe the live lower bound + future-date 404, drop the implied fixed upper bound.

---

## LOW severity

Cosmetic / navigational: wrong counts, imprecise wording, stale defaults, misleading-but-harmless comments.

### `backend/app/engine/README.md`

- **L11** — `doc_drift` — diagram comment says "27 columns" of derived indicators; `types.py` `DERIVED_COLS` has exactly **26** entries. → **Action: update-doc** — correct 27 → 26.

### `backend/app/engine/runner.py`

- **L206** — `stale_comment` — "highest OI = front-month". The query selects max-OI per date (`ORDER BY d.date, d.oi DESC NULLS LAST`); max-OI ≠ front-month during rolls. → **Action: update-doc** — say "highest-OI contract per date" and note it is not necessarily the front-month delivery.

### `backend/scripts/daily_analysis/prompts.py`

- **L249** — `stale_comment` — comment promises vocabulary "(consensus / conviction / safety net / cluster divergence)" but L300-L310 explicitly forbid "filet de sécurité"/"cluster …"; the block never uses those terms. → **Action: delete** the stale comment; the VOCABULAIRE block (L295-L310) is the source of truth.

### `backend/scripts/ensemble_compute/main.py`

- **L149** — `stale_comment` — "Frozen at 2026-04 in v1.0.0; monthly retrains will append new rows." Code (L151-L165) dynamically fetches `MAX(training_month)`, so "frozen" is inaccurate as of 2026-06. → **Action: update-doc** — "Seeded at 2026-04; monthly retrains append new rows, picked via `MAX(training_month)` at runtime."

### `backend/scripts/ensemble_compute/db_loader.py`

- **L31** — `incorrect_reference` — comment cites "CAMPAIGN_4 §4.4" but this is Campaign 5 code; copy-paste artifact. → **Action: update-doc** — repoint to `PIPELINE_ENSEMBLE.md` (MacroSignal) or restate the 90d window rationale without the C4 reference.

### `backend/scripts/barchart_scraper/main.py`

- **L47** — `stale_comment` — log line `"Barchart Scraper - London Cocoa #7 (CA*0)"`; CA*0 is never used (resolved active contract is used). → **Action: fix** — drop the `(CA*0)` suffix.

### `backend/scripts/enso_scraper/README.md`

- **L23** — `doc_drift` — README cron `0 22 20 * 1-5`; actual cron (`main.py` L9, `scheduler.tf` L322) is `0 22 20 * *` (monthly, no weekday restriction). → **Action: fix** — correct the cron string.

### `backend/scripts/seasonal_backtest/main.py`

- **L53** — `stale_comment` — `default=date(2025, 9, 30)` (campaign 2024-2025) is 8+ months stale; users must pass `--target-date` for current campaigns. → **Action: fix** — refresh the default (or compute it dynamically) for the current campaign.

### `backend/scripts/archive/julien_handoff/main.py`

- **L102** — `doc_drift` — comment "rolling 26w z-scores (**full history**)" but L127-L128 apply a `cot_history_days` (default 400) windowed subset, not full history. *(Archived script.)* → **Action: update-doc** — note the 400-day rolling window (configurable via `--cot-history-days`).

### `backend/scripts/contract_resolver.py`

- **L92** — `comment` — `resolve_by_code()` comment says "Used by: Barchart scraper (ACTIVE_CONTRACT env var)" but L115 `resolve_active_code()` says it "replaces ACTIVE_CONTRACT env var" via `ref_contract.is_active`. → **Action: update-doc** — mark `resolve_by_code()` as legacy; note modern code prefers `resolve_active_code()`.

### `backend/app/utils/date_utils.py`

- **L4** — misleading module comment — "Trading-day resolution lives in `trading_calendar.py`." The pipeline's high-level date facade (`get_display_date`, `get_next_session_date`) lives in `scripts/db.py`. → **Action: update-doc** — point readers to `scripts/db.py` for the pipeline date facade.

### `backend/app/api/api_v1/endpoints/dashboard.py`

- **L87-L104** — silent fallback (docstring) — `_resolve_contract_for_request` silently falls back to the active contract when `resolve_contract_for_date` returns None (pre-roll/historical dates), with no log → harder diagnosis. → **Action: update-doc** (and optionally add a warn-level log on fallback).
- **L853-L854** — `doc_drift` — docstring "Returns 404 on dates without an ensemble row (pre-2025-12-15 or future dates)" implies a fixed range; ensemble computes daily past the old end date. → **Action: update-doc** — keep the live lower bound + future-date case, drop the implied fixed range.

### `backend/app/services/macro_panel_service.py`

- **L8** — `doc_drift` — comment "only populated on ensemble dates (≥ 2025-12-15)" — lower bound correct, but omits that ensemble continues producing rows past the originally documented end. → **Action: update-doc** — clarify ensemble is ongoing (no fixed upper bound).

---

## Uncertain — needs Hedi's call

Findings where the verdict is `uncertain`, the action is `leave`, or the right fix depends on intent/architecture decisions. No PR should touch these without a steer.

- **`backend/scripts/meteo_agent/llm_client.py:25`** — `stale_comment` (medium, uncertain) — docstring/config reference model id `gpt-4.1` (`config.py` L9). This isn't a standard OpenAI model id (cf. `gpt-4-turbo`, `gpt-4o`, `o4-mini`). May be a valid alias or may fail at runtime. **Q: is `gpt-4.1` a real/aliased model in use, or a typo?** Needs confirmation before any edit.

- **`backend/scripts/press_review_agent/config.py:8`** — `stale_reference` (low, uncertain) — docstring "Inspired by TogetherCocoa Monitor pattern." Only reference in the codebase; no import/module. Could be valid historical context. Recommended verdict: **leave** unless Hedi wants it scrubbed.

- **`backend/scripts/_shared/publication_calendar.py:9`** — `stale_comment` (low, uncertain) — references `docs/user-stories/P3-fundamental-data-scrapers-grindings.md §2.2` which doesn't exist (referenced from JOBS_AND_SCRAPERS.md but file absent). Logic is live and correct. **Q: was the US doc renamed/removed, or never committed?** If gone, **update-doc** to repoint; if expected, the doc is the gap.

- **`backend/scripts/archive/_analyze_backfill_coverage.py:22`** — `stale_comment` (medium, uncertain) — hardcoded `RND` dict ("from user's screenshot") with no provenance (build/commit/date) and no sync path from `pl_algorithm_config`. Archived analysis script. **Q: keep as a frozen reference, annotate provenance, or delete?**

- **`backend/scripts/watchlist_eval/evaluator.py:20`** — `stale_comment` (medium, uncertain) — forward-fill of `stock_us`/`com_net_us` from dedicated tables (post-`r2m3n4o5p6q7`) with no guard for pre-migration dates → silent NULLs. **Q: confirm NULL-for-pre-migration is acceptable; if so, document it; if not, add a guard.**

- **`backend/scripts/compass_brief/db_reader.py:94`** — `comment` (low, uncertain) — "Active algorithm only … CONTRACT no longer filtered by is_active" conflates two orthogonal filters; L97 DOES filter `algorithm_version.is_active`. Ambiguous wording, not wrong. **Action if pursued: update-doc** to separate the two concepts.

- **`backend/app/utils/contract_resolver.py:38`** — imprecise wording (low, uncertain) — module docstring's "backfill vs live" framing is blurred (the live job resolves a past session date via P2b, not the current moment). Not wrong, just imprecise. Recommended verdict: **leave** (or light reword if touched).

- **`backend/app/services/dashboard_service.py:158 / :322 / :496`** — silent non-date-aware fallback (medium, uncertain) — three functions fall back to `get_active_algorithm_version_id(db)` when `algo_id is None`. Endpoints always pre-resolve `algo_id`, so these paths are never hit in production. Defensive-by-design. Recommended verdict: **leave** unless Hedi wants the dead defensive branches removed.

- **`backend/app/services/audio_service.py:170`** — query construction (low, uncertain) — Drive lookup returns `files[0]` with no sort/uniqueness guard. Safe while NotebookLM emits exactly one file per date/version. **Action if pursued:** sort by creation_time DESC or fail-loud on multiple matches; document the single-file assumption. Recommended verdict: **leave** for now.

- **`backend/scripts/compass_brief_ensemble/main.py:129`** — contract resolution (low, uncertain) — `EnsembleBriefData` has no `contract_code`; the brief template is contract-agnostic. Only a concern if a future brief needs to print the contract code (e.g. CAK26). Recommended verdict: **leave** — extend `db_reader` only when/if needed.

- **`docs/architecture/JOBS_AND_SCRAPERS.md:56`** — output-target discrepancy (low, uncertain) — the doc marks the scraper outputs as changed (now `pl_stock_observation` / `pl_cot_us_weekly`, correct) but doesn't clearly state the change was definitive. Verdict: **leave** (or a one-line clarification that the old `pl_contract_data_daily` columns are gone).

- **`docs/architecture/JOBS_AND_SCRAPERS.md:144`** — schema-keying discrepancy (low, uncertain) — `pl_stock_observation.report_date` is the publisher's date (can lag the session date), not the session date; doc doesn't make this explicit. Code handles it correctly. **Action if pursued: update-doc** to clarify `report_date` = publisher's date with latest-on/before-target lookup semantics.

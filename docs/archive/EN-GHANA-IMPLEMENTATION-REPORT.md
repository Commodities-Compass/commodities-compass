# English / Ghana Edition — Implementation Report & Handoff

**Status: 🚀 SHIPPED TO PRODUCTION — 2026-07-16 (live but DARK, switcher OFF).**

| | |
|---|---|
| **Merged** | PR **#66** → `e84ab3c` (EN/Ghana edition, squash, 22 commits) · PR **#68** → `89923d8` (roll-safety fix, closes issue **#67**) |
| **Deployed** | 2 Deploy runs ✓ green (backend + frontend + 8 Cloud Run Jobs + Sentry release). Migration `43a8a015a3d4` applied on prod via `start.sh`; `api.com-compass.com/health` → **HTTP 200** after both. |
| **Green** | **730 backend + 44 frontend tests**; full ruff + pyright + eslint + tsc clean; prod build compiles. |
| **Exposure** | **None yet** — `VITE_FEATURE_LANG_SWITCHER` is **OFF**. The pipeline writes FR **+ EN** rows nightly; users still see FR only until the flag flips. |
| **Origin branch** | `feat/i18n-english-ghana` (based on `main` @ `15803c7`) — merged, branch deletable. Built in the now-removed `commodities-compass-i18n` worktree. |

> Narrative index over the shipped work. The commits are the durable record; the [EPIC](EPIC-english-edition-ghana.md) + US docs (US-0..4) hold the plans; `MEMORY.md` (`project-english-edition-ghana-i18n`) holds cross-session persistence.
>
> **⚠️ Sections 3–11 below were written *during* the build** (pre-merge) and describe the state at that time — e.g. "pending commit", "18 commits", "725 tests". They are kept as the build narrative. **This header is the authoritative final state**; §7 records what actually shipped vs what remains.

---

## 1. Mission

Ship an **English edition of the Commodities Compass dashboard for the Ghana market** (first anglophone expansion): the dashboard, its LLM-generated content (weather, press review, trading narrative), and — via US-4 — the audio brief, all in English. The founding instruction (Hedi): **"never fall into the trap of literal translation for the critical content"** — generate natively in English, don't translate French.

---

## 2. Locked architecture decisions

| # | Decision | Choice | Why |
|---|---|---|---|
| **D1** | Delivery model | **`language` dimension on the existing app** (`language VARCHAR(5) DEFAULT 'fr'`) | Fastest, lowest-risk; stepping stone to the North Star `tenant.account.locale`. |
| **D2** | MVP scope | EN chrome + EN text; **podcast deferred** → *reopened*: US-4 now in scope before go-live (user call). | Podcast is manual (NotebookLM) + 4×'s daily audio work. |
| **D3** | Content generation | **Deterministic facts + thin native voice LLM + fail-loud accuracy gate.** Press = extractive exception. | "100% accurate" = never let an LLM re-type a number in a second language. |
| **D4** | Audience | **Ghana cocoa exporters/traders** — WA-English register, Ghana-first framing. | Market terms verbatim (OPEN/HEDGE/MONITOR, RSI, tonnes). |
| **D3-EN-rows** | EN `pl_indicator_daily` rows | **Option A: EN agent UPSERTs its own `en` row**, copying language-agnostic numeric columns from the `fr` row + writing only EN prose. | Self-contained; mirrors ensemble_compute's UPSERT. |
| **US-4 scope** | EN podcast track | **Ensemble-EN only** (not legacy+EN); brand hook **"Good morning, Compasteurs!"** (keep coined term); **British/WA register**. | Ensemble is the product direction; +1 (not +2) manual NotebookLM/day. |

### The core insight (D3)
The daily `conclusion` used to be one LLM blob mixing numbers + structure + voice, re-parsed by French regex in backend AND frontend — fragile in FR, broken in EN. **Inverted it**: **facts layer** (every number rendered from the DB per-locale, correct by construction, identical across languages) + **voice layer** (LLM writes only a qualitative headline, no numbers) + **accuracy gate** (fail-loud on ungrounded numbers) + **consumers read structure, not French prose**. "Compute once, present per-locale."

---

## 3. What's implemented — per US

### US-0 — Locale foundation (`51db642`)
`language` dimension end-to-end, retro-compatible (all existing = `fr`). `app/core/i18n.py` (`Language` StrEnum, `resolve_language`, later `expand_languages`/`LANGUAGE_CLI_CHOICES`); migration `43a8a015a3d4` (language col + widened 3 unique constraints, backfilled 'fr', idempotent/reversible); models + 3 services + 3 endpoints filter by language (**never cross-language**); `ensemble_compute/db_writer.py` ON CONFLICT fix; frontend `LanguageContext` + Accept-Language + switcher **flag-gated OFF**.

### US-1 — Facts/voice refactor (`21031de`, `d85b131`, `4e4076f`, `bcfb29e`)
`facts.py` (`FactsPayload`) + `render/{fr,format}.py` (deterministic FR renderer, 8 bullets + à-surveiller pinned S1/R1/RSI) + `accuracy_gate.py`; `voice_prompts.py` (Call#2 emits headline only); `db_analysis_engine.py` assembles conclusion + gates; frontend `recommendation-parser.tsx` split made **structural** (2nd `>` header, language-agnostic). Old Call-2 prompts marked DEPRECATED.

### US-2 + US-2b — Frontend EN-ready (`ca3c405`, `3115a28`, `a1e4947`, `488068e`)
react-i18next + `I18nSync` bridge + `format-locale.ts` (en-GB for Ghana) + FR/EN catalogs (196-key parity, 9 namespaces, Ghana register) + 12 components + 2 utils threaded with `t()`; `indicator-metadata.ts` → catalog-prefix map + gauge tooltips wired.

### US-3a + US-3b-i — EN generation layer (`01351cc`, `08da58c`)
`render/en.py` (EN deterministic renderer, `> TO WATCH TODAY:`, cross-language number-parity test) + `voice_prompts.py` language-parametric (`_ENSEMBLE_DIAGNOSTICS_BLOCK_EN`, conviction labels). **JSON field names stay French** (`confiance`, `confiance_rationale`) + enum values stay (HAUSSIERE/…) — downstream contract.

### US-3b-ii — Engine language wiring + Option-A EN row (`4736030`) ✅ (was paused; now done)
`db_analysis_engine.run(..., language)` threads Call-1/Call-2/renderer/write. **EN `CALL_1_PROMPT_EN`** (native, same JSON shape). `_write_results` branches: **fr** = existing UPDATE **+ new `AND language=:language` filter** (load-bearing — else an fr re-run clobbers the en row); **en** = `_upsert_translated_indicator_row` — one `INSERT…SELECT…ON CONFLICT ON CONSTRAINT uq_indicator_daily DO UPDATE` copying EVERY column from the fr row (column list from the model → self-maintaining; `id`→fresh uuid, `created_at`→server default, 3 prose cols→params) → numbers byte-identical, only eco/conclusion/confidence_rationale are EN. EN run does **not** touch `pl_signal_component` (fr-owned). `--language {fr,en}` CLI. 11 tests.

### US-3c — Native-EN meteo + press agents + job wiring (`3c19c7d`, `ba3b355`, `5f4aa5f`)
- **Meteo** (`3c19c7d`): native EN `SYSTEM_PROMPT_TEMPLATE_EN` + `build_seasonal_context_en` + `_SEASONAL_PROSE_EN` (5 seasons; **numeric thresholds shared** from `SeasonalProfile`); writer dedups on `(date, language)`. JSON keys stay French; `diagnostics` enum stays.
- **Press** (`ba3b355`): native EN `SYSTEM_PROMPT_EN` (extractive/grounded, EN section labels SUPPLY/FUNDAMENTALS/MARKET); dedups on `(date, llm_provider, language)`. **EN run SKIPS `pl_article_segment`** — segments feed the language-agnostic ensemble macro signal → EN would double-count. EN still emits theme_sentiments (shared validator) but discards them.
- **Job wiring** (`5f4aa5f`): user directive = **no new jobs**. `expand_languages(arg)` (fr-first: `both`→[FR,EN]) + `LANGUAGE_CLI_CHOICES`. All 4 agents accept `--language {fr,en,both}`; `both` = fr-first loop, fail-loud on any language, committed language preserved. meteo/press `main()` refactored (fetch once, LLM+write per language; **Harmattan check runs ONCE**). deploy.yml existing 4 jobs → `--language,both`; schedulers unchanged (no Terraform).

### Code review + 5 fixes (`bf396b9`) + press-parser (`83295ea`)
A 4-dimension adversarial review workflow (15 agents) → 11 raised, **5 confirmed** (1 high, 3 med, 1 low), 6 refuted (all matched design intent). The **durable lesson**: adding `language` to the 3 content tables means **every un-filtered read of them double-counts once EN rows exist**. Fixed:
1. **HIGH** — `calculate_ytd_performance` LEFT JOINs pinned `language='fr'` (decisions are language-agnostic). Verifier found **2 sibling sites**: `ensemble_diagnostics_service._compute_running_accuracy` (feeds the Compass wrapper decision gate!) + `compass_brief_ensemble/db_reader.py` (×2 YTD queries) — all fixed.
2. **MED** — `get_stress_history` now threads the request language (else the `LIMIT 7` window collapses).
3. **MED** — `sentiment-gauges.tsx` EN tooltips (added `metadataKey` prop; `INDICATOR_META_KEY` was keyed on FR display strings).
4. **LOW** — EN "US stocks" not bolded → extended the parser regex.
5. **MED** — migration `downgrade()` made regenerable (DELETE non-fr rows before recreating the narrow constraint).
6. **(`83295ea`)** — **press-review tab parser** (`news-card.tsx parseSections`) was French-header-only → EN reviews dumped into one tab; made bilingual (SUPPLY/FUNDAMENTALS/MARKET/MARKET SENTIMENT). *(Found via the local demo, below.)*
+2 regression tests (YTD-invariant, stress-history).

### US-4 — English podcast track (COMPLETE — US-4a/b this session, pending commit)
- **US-4c DONE (`64a5aeb`)**: native-EN NotebookLM prompt `docs/operations/notebooklm-podcast-prompt-en.md` (9-section, redacted, EN forbidden-vocab, "Good morning/See you tomorrow, Compasteurs!", British/WA) + `docs/runbooks/brief-multilingual-management.md` (documents the +1 manual step/day).
- **US-4a DONE (uncommitted)** — native-EN ensemble brief. `specialist_catalog.py`: **14 native-EN `label_en`/`description_en`** (British/WA register, same redaction rules) + `label_for`/`description_for` accessors. `brief_generator.py`: `render_brief(data, language)` — a `_BriefLabels` struct (`_LABELS_FR`/`_LABELS_EN`) for all scaffolding, EN months, `_THEME_LABEL_EN`, grammar-aware theme convergence ("…and…"/"…et…"), aligned field padding (FR output byte-identical). `db_reader.py`: `read_brief_data(..., language)` threads to ensemble/press/meteo/trajectory/technicals reads (`AND language=:language`); **persistence pinned `language='fr'`** (canonical decision series, avoids window collapse). `config.filename_for(stem, lang)` → `-Ensemble-EN.txt`. `main.py`: `--language {fr,en,both}` fr-first loop, fail-loud, **committed-language preserved** (FR ships even if EN read fails → exit 1 flags the gap). `deploy.yml` `cc-compass-brief-ensemble` → `--language,both`. Redaction guard unchanged (language-independent). **19 tests** (`test_brief_ensemble_language.py`: catalog parity + no-French-diacritics, bilingual render + no-leak, theme grammar, filename, `_format_date`, DB language-filter helpers + persistence-pin).
- **US-4b DONE (uncommitted)** — audio `(version, language)` matrix. `audio_service._candidate_suffixes(version, language)` is **language-consistent by construction**: EN = `["-Ensemble-EN", "-EN"]` (ensemble-only, ignores version, **never falls back to an FR file**); FR = exact per-version (unchanged, no cross-version fallback). `get_audio_file_info`/`get_audio_metadata` take `language`, cache keyed `(date, version, language)`, one Drive query over all candidates + preference-ordered pick, title label derived from the resolved filename. `/dashboard/audio` + `/audio/stream` + `/audio/info` take `?language=` (resolve_language: query > Accept-Language > fr); `/dashboard/audio` embeds `?language=` on the returned stream URL so the unauthenticated `<audio>` streams the right edition. Frontend `useAudio` queryKey gains `language` (cache-bust on switch; header carries the edition, URL carries it to the audio element). Runbook §Serving corrected to the language-safe behavior. **11 tests** (`test_audio_language.py`: normalize, candidate order, EN prefers ensemble-EN, **EN query never requests FR names**, EN degrades to no-audio, FR unchanged, cache separation).
- **Local demo (2026-07-16)**: `compass-brief-ensemble --language both --session-date 2026-07-15 --dry-run --force` rendered both briefs from real synced data. EN is genuinely native: headline "Long-cycle specialist", "Other reads converge on this verdict — a macro read and a technical read", EN press (SUPPLY/FUNDAMENTALS/MARKET/MARKET SENTIMENT, independently generated), EN weather (4/10 vs FR 3/10 — the accepted per-language divergence), EN "TO WATCH TODAY". Filenames `-Ensemble.txt` / `-Ensemble-EN.txt`.
- **Known blemish (open)**: the weather trajectory line renders the season **slug** verbatim (`Campaign trajectory — grande saison pluies:`) — `pl_seasonal_score.season_name` is a stored FR data value; only the surrounding prose is per-language (documented in `db_reader._read_seasonal_trajectory`). It's read aloud in the EN podcast. Left as data (translating DB slugs is scope-creep + risks other consumers); revisit if the FR slug in the EN audio is unacceptable — a small `season_name → EN` map in the renderer would fix it.

---

## 4. Local FR/EN demo — what we ran + what it proved
Ran the full stack locally on **branch as-is** (no merge to main):
1. Copied `.env` into the worktree (verified `DATABASE_URL`/`DATABASE_SYNC_URL` → **localhost:5433**, not prod — the branch's `language`-filtered queries need the column prod lacks).
2. `db-prod.sh up` (bastion IAP tunnel) → `sync_from_gcp.py` (data-table subset, FK-safe) + a targeted copy of `pl_orchestrator_decision`/`pl_specialist_prediction` for July 3–15 (not in the sync's table set). Tore the tunnel down after.
3. Ran the 4 EN agents for **2026-07-15** (`--language en --session-date … --force`) → real native-EN content (legacy=OPEN, ensemble=MONITOR, weather, press). Meteo Harmattan check fired **once** (off-season skip) — confirmed the both-mode refactor.
4. Backend :8000 + frontend :5173 (switcher on). Verified serving applies `WHERE language=…` on every content query — **FR→FR, EN→EN, no cross-leak** — via the service layer.

**Prod-vs-local comparison (screenshots) sorted into 4 buckets:**
- **A. Local served LEGACY, prod ENSEMBLE** — root cause of ~all top-section diffs (signal OPEN vs MONITOR, YTD, horizon, conviction). NOT i18n → see the resolver finding (§6). Corrected locally (demo hack).
- **B. One real i18n bug** — the press-tabs parser (fixed, `83295ea`).
- **C. Demo artifacts** — weather/press content differs because the EN agents re-ran **today** on a fresh web fetch (different day than prod's July-15 run); EN stress-history bars short (only 1 EN weather day generated).
- **D. By-design** — weather/press are **independently generated per language** (native, not translated), so qualitative judgments (weather impact 3/10 vs 4/10, sentiment) can legitimately diverge FR↔EN even in prod's single `--language both` run. **User decision: keep independent LLM calls**, revisit fine-tuning after a period.

---

## 5. US-4a/b — DONE this session (see §3 for the detail)

Both are implemented, tested (30 new tests), lint/type-clean, and demoed end-to-end on local data. Nothing remains in US-4a/b except **committing** them and the shared go-live steps (§7). The one open sub-item is the season-slug blemish (§3, last bullet) — a content call, not a blocker.

**Key design decisions locked in the implementation:**
- **Language is a hard filter, never a fallback dimension** — the audio candidate list is language-consistent by construction; an EN request can never resolve to an FR file (degrade to no-audio instead). Mirrors the D3/D4 "never mislabel" guarantee.
- **Persistence/YTD/running-acc stay pinned `'fr'`** — decisions/numbers are language-agnostic; the FR row is the canonical always-present series. Filtering those by request-language would collapse the window once EN rows are sparse.
- **fr-first, committed-language-preserved** — `--language both` uploads FR before attempting EN; an EN failure still exits 1 (visible Sentry gap) without unshipping FR.
- **FR renderer output is byte-identical** — the `_field` padding + `_LABELS_FR` reproduce the prior FR brief exactly (verified in the demo).

---

## 6. ⚠️ Bonus finding (NOT i18n) — resolver picks newest version by created_at
`_get_version_id_by_name` (`contract_resolver.py`) resolves an algo id via `ORDER BY created_at DESC LIMIT 1`. Origin: **PR #10 / branch `feat/c5-frontend-integration`** (`9d131e4`) — a proxy for "current version of a name," valid for a monotonic **config bump** (legacy 1.0.0→1.0.1, newest is is_active) but **wrong for a shadow parallel version**. The moment `ensemble 1.0.1` shadow (branch `feat/c5-ensemble-v1.0.1-shadow`) lands on prod, the resolver picks the newer shadow (no live rows) → the dashboard **silently falls back to legacy for every date**, dropping the ensemble track. **Fix belongs in that C5 context** (resolve the version-with-rows / use `is_active`, not newest) — confirm the design with that session first. Left untouched on the i18n branch.

---

## 7. 🚦 Go-live — what shipped vs what remains

### ✅ Done (2026-07-16)
1. **US-4a/b committed + merged** — `18e998b` (US-4a) + `9158176` (US-4b), shipped in PR #66.
2. **Dead-prompt deletion** — `0557afc`: removed the 4 deprecated Call-2 blobs from `prompts.py` (**671 → 349 lines**), keeping `ENSEMBLE_DIAGNOSTICS_BLOCK` / `_format_optional` / `_qualitative_conviction` (imported by `voice_prompts.py`) + fixed 3 stale comments pointing at the deleted builders.
3. **ONE PR, everything coupled** — migration + `ensemble_compute` writer + `deploy.yml` shipped together in #66, as required.
4. **Migrations via main only** — respected: the migration reached prod only through the #66 merge (`start.sh` → `alembic upgrade head`).
5. **Local demo hacks reverted** — `ensemble 1.0.0 created_at` bump restored to its true ordering (v1.0.0 < v1.0.1); both bg dev servers stopped; the copied `.env` files disappeared with the i18n worktree.
6. **#65 ↔ #66 conflict resolved** — the YTD/running-acc scoring now combines #65's roll-safe decision-aware front-month **with** the `language='fr'` pin, centralised in one shared helper.
7. **Issue #67 fixed** — PR #68: the brief's sync YTD/running-acc copies now use a sync mirror of the same decision-aware series, so the podcast number stays in lock step with the dashboard across a roll.

### ⬜ Remains before flipping the switcher
1. **Validate the EN rows** written by the first nightly pipeline (2026-07-16 evening onward): `pl_indicator_daily` / `pl_fundamental_article` / `pl_weather_observation` where `language='en'`.
2. **Generate the EN NotebookLM audio** from `YYYYMMDD-CompassBrief-Ensemble-EN.txt` on Drive → rename to `YYYYMMDD-CompassAudio-Ensemble-EN.m4a`. Prompt: [notebooklm-podcast-prompt-en.md](../operations/notebooklm-podcast-prompt-en.md). See [brief-multilingual-management.md](../runbooks/brief-multilingual-management.md).
3. **Adversarial review of US-4a/b** — US-0..3c got a 4-dimension review; **US-4a/b never did**.
4. **Full "no FR leak in EN mode" audit** + human review of the EN register (incl. the native-EN specialist catalog).
5. **Then flip `VITE_FEATURE_LANG_SWITCHER=true`** — this is the only step that actually exposes EN to users.

### ⚠️ Deviations from the plan (accepted knowingly)
- **Not merged off-window.** The plan said merge outside 18:30–22:10 UTC; the actual merge was **17:56 UTC** (~34 min before the window) to catch that night's pipeline. Deploy completed ~18:06, well before the first language-consuming job (19:00 meteo). No incident — but it was a deliberate risk, not the documented procedure.
- **secops scan of the `deploy.yml` CI/CD change was offered and skipped.**

---

## 8. How to resume / run locally
- **Resume US-4:** everything in `MEMORY.md` + §5 above. Start with the native-EN specialist catalog + `render_brief` bilingual, then `db_reader` threading, then audio matrix.
- **Run locally:** the worktree has all deps installed. Copy `.env` (force **local** DB URLs), `pnpm db:up`, confirm `alembic current` = `43a8a015a3d4`, sync from GCP for recent data, run the EN agents (`--language both --session-date T --force`), then `poetry run dev` + `VITE_FEATURE_LANG_SWITCHER=true pnpm dev`. Prod sync needs `.local/db-prod.sh up` (bastion; creds in-file). Only dates you ran EN agents for have EN content.
- **Verify:** backend `poetry run pytest` + `poetry run lint`; frontend `pnpm type-check && pnpm lint && pnpm test`; `pnpm build`.

---

## 9. Key gotchas & patterns
- **Numbers are never re-typed by an LLM** — facts → `FactsPayload` → per-locale renderer. Add a metric → `facts.py` + both `render/{fr,en}.py` + shared `format.py`.
- **JSON field names + enum values stay French** across languages (parser/DB contract).
- **Every un-filtered read of the 3 content tables double-counts once EN exists** — the #1 review lesson. Pin decision/number reads to `'fr'`; thread request-language for prose reads.
- **Frontend parsers must be structural/bilingual, not French-keyed** — recommendation split (2nd `>`) and news tabs (both languages' headers).
- **Constraint-widening breaks column-based `ON CONFLICT`** — include `language` or use `ON CONFLICT ON CONSTRAINT <name>`.
- **weather/press are independently generated per language** — qualitative judgments can diverge FR↔EN by design (user-accepted).
- **`.env` must point at the LOCAL DB** — prod lacks the `language` column until the PR merges.

## 10. Commit log (base `main` @ `15803c7`, 18 commits)
```
64a5aeb docs(i18n): US-4c — native-EN NotebookLM prompt + multilingual brief runbook
83295ea fix(i18n): parse EN press-review section headers in news tabs
bf396b9 fix(i18n): review findings — language-filter YTD/running-acc/brief/stress + EN tooltips + regenerable downgrade
5f4aa5f feat(i18n): US-3c job wiring — --language both on all 4 agents + existing jobs (no new jobs)
ba3b355 feat(i18n): US-3c press — native-EN press review (own row, segments fr-owned)
3c19c7d feat(i18n): US-3c meteo — native-EN weather bulletin (own row, shared thresholds)
4736030 feat(i18n): US-3b-ii — engine language wiring + Option-A EN-row UPSERT + --language CLI
08da58c US-3b-i — EN voice prompts (language-parametric)
01351cc US-3a — EN deterministic renderer + number-parity test
488068e US-2b — gauge tooltips → indicators.* catalog
a1e4947 US-2 — t() through ensemble-explanation + weather/shared
3115a28 US-2 — component chrome + FR/EN catalogs (parity)
ca3c405 US-2 — react-i18next foundation + locale-aware dates
bcfb29e chore — mark legacy Call#2 prompts deprecated
4e4076f US-1e — structural conclusion watch-split
d85b131 US-1c — Call#2 voice-only + engine assembles conclusion + gate
21031de US-1 — deterministic facts layer + FR renderer + gate
51db642 US-0 — locale foundation across schema, API, serving, frontend
```

## 11. Verification status
- **Backend:** **725 tests pass** (695 + 30 new US-4a/b); ruff + pyright clean; migration applied + reversible on local DB.
- **Frontend:** 44 tests pass; tsc + eslint clean (0 errors); prod build compiles.
- **Live LLM + brief:** validated end-to-end on the local demo — real native-EN meteo/press/narrative for 2026-07-15 **and** the native-EN ensemble brief rendered from that data (`--language both` dry-run) — not just mocks.
- **Review:** 4-dimension adversarial review complete; all 5 confirmed findings fixed + regression-tested. *(US-4a/b not yet through an adversarial review — a candidate for the go-live audit, §7.3.)*

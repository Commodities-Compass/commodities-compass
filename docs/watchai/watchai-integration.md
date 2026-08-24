# WatchAI → Compass Integration — Design

> **Status (updated 2026-08-24): SHIPPED, and the entitlement flag is now ON.** Phase 1 ingestion (#93), the cube, the balance service, both endpoints, the entitlement keys and Section VI "Marché physique" (#94) are on `main`. **`ENTITLEMENTS_ENFORCED=true` since 2026-08-24** — the section is no longer hidden by the flag, so the `read:watchai:*` keys are what gate it. The six grandfathered logins are on the `internal` tier, which resolves to the *full* catalogue at read time, so **Section VI is now visible to them**; it renders empty until `pl_origin_*` is loaded in prod by a manual run — see [watchai-ingestion.md](../runbooks/watchai-ingestion.md). All five block ② rows are now built: destinations/ports, benchmark and nominative flows shipped for the three export tiers, with `tenant_account.exporter_entity_id` (migration `p1q2r3s4t5u6`) as the benchmark's identity link. Supersedes the "WatchAI (②) is a separate product, not modeled" note in [entitlement-and-tenancy-for-USERS.md](../architecture/entitlement-and-tenancy-for-USERS.md) §Appendix B.
> **Scope**: the **data** of block ② of the commercial matrix ("Matrice de versioning par blocs", July 2026), ingested into Compass Postgres and exposed under the Compass brand and Compass entitlements. **Narrative is explicitly out of scope** — it stays Compass-native (decision #4).
> **Companion docs**: [port-inventory.md](port-inventory.md) (what moves, what dies) · [business-rules.md](business-rules.md) (the semantics that must not drift).
> **Reference source**: `plakoplister/watch-ai` @ **`11336ef`**, branch **`refonte-da-v2`** (2026-08-14). WatchAI has been rebuilt as FastAPI + DuckDB + Next.js; the v2 `api/app/` is the port reference and `Webapp/webapp_tax.py` is historical. ⚠️ Active branch — this spec is **pinned to a SHA**. Re-sync deliberately and re-run the reconciliation; never follow `HEAD`.
> **Guardrails**: [north-star-alignment](../../.claude/rules/north-star-alignment.md) · [timeseries-uniqueness](../../.claude/rules/timeseries-uniqueness.md) · [migrations-prod-via-main-only](../../.claude/rules/migrations-prod-via-main-only.md) · [pipeline-error-handling](../../.claude/rules/pipeline-error-handling.md) · [no-workaround-without-asking](../../.claude/rules/no-workaround-without-asking.md).

---

## 0. Locked decisions

| # | Fork | Decision | Consequence |
|---|---|---|---|
| 1 | Integration model | **Full replication into Compass Postgres** | Compass holds its own copy. WatchAI Streamlit stays alive for Julien's direct clients (13 `GEPEX-*` accounts). **No runtime coupling** — the OVH VPS is never in a request path. |
| 2 | Code reuse | **Port semantics, not code** | ~250 lines of business rules + `Entity_Mappings.xlsx` move. **Zero** lines of code. Unchanged by the v2 rewrite, but for a different reason: v2 is well-built and built for a *different runtime* (DuckDB-over-parquet, JWT cookies, Next.js). Lifting it would import a second data engine and a second auth model. What we take is its **explicit, tested specification**. See [port-inventory](port-inventory.md). |
| 3 | Rendering | **Compass editorial identity** (Playfair/Inter/IBM Plex Mono, Recharts, signal palette) | The WatchAI look (turquoise `#2DBDB6`, Montserrat, Plotly) is **not** reproduced. A visibly foreign section undercuts the "impact tarifaire nul, muscle la valeur" narrative. |
| 4 | **Narrative** (§7 Revue de Presse, §8 Note Stratégique of the WatchAI monthly report) | **Out of scope — not ingested, not ported** | Those two sections encroach directly on Compass CC's product (press review, signal, hedge decision). Two engines issuing contradictory hedging advice inside one commercial bundle is a governance liability. Compass produces its own from `pl_article_segment` + the signal. Kills the Perplexity dependency and the `narrative_as_of` freshness problem outright. |
| 5 | Acquisition | **Local `watch-ai` checkout of `refonte-da-v2`, provenance by content hash** | The CLI reads a path on disk — no deploy key, no clone, no GCS bucket, no credential. **`main` is not the source**: it is frozen at 2026-06-05 (May data). The July 2026 data lives only on `refonte-da-v2`. Because a branch moves and data commits are an *optional* step in Julien's procedure (which ends at `scp` to the VPS, not `git push`), the batch identity is the **sha256 of each source file**, with the commit SHA kept as optional metadata. Verify `data_as_of` after every pull — git being current is never assumed. |
| 6 | Cadence | **Manual CLI. No cron, no Cloud Run Job, no scheduler.** | Julien's lag is variable (J+3 to J+11 after month end). An operator runs the command when a new month lands. Same family as `set-farmgate-price`, `seed-gcp`, `seed-trading-calendar`, `sync_from_gcp.py`. |
| 7 | Landing granularity | **Line-level, reduced projection — 9 of 18 columns** | We own the transform (so we fix the taxonomy bugs and publish a volume-weighted CAF), but we drop every column no matrix row justifies: `DECLARANT*`, `DESTINATAIRE*`, `DECLARATION`, raw `EXPORTATEUR`, `TAX %`, `CAF/kg`. ~⅓ less sensitive surface, nothing recomputable lost. |
| 8 | Batch semantics | **Full snapshot replace + restatement diff** | Julien's `consolidate_achats.py` and `consolidate_broyage.py` **rebuild their masters from scratch** each month, so history can move between batches; `Entity_Mappings` grows and rebinds old rows retroactively. Append is therefore wrong. Full replace also disposes of the line-identifier problem: `DECLARATION` was `NULL` on 100 % of rows on `main` and is **populated on only 101 113 of 172 712 (58,5 %)** on `refonte-da-v2` — partially populated is *less* usable as a natural key than uniformly empty. |
| 9 | Serving granularity | **Endpoints read the cube only** | `pl_origin_flow_monthly` is the only table the API touches. The line table is never served, never exported. |
| 10 | Time dimension | **Separate season/month selector** | Origin data is monthly. It does **not** join the daily `DashboardDateContext`. Folding a monthly dimension into the daily context is the collision class [timeseries-uniqueness](../../.claude/rules/timeseries-uniqueness.md) exists to prevent. |
| 11 | Entitlement | **New `read:watchai:*` domain, 6 keys** | Merged into the existing catalogue in `app/core/entitlements.py`. Same mechanism, no new machinery. Depends on `feat/per-client-entitlement` landing first. |
| 12 | Official farmgate prices | **Delete WatchAI's `PRIX_OFFICIELS`** | Compass already owns this (`pl_official_farmgate_price` + `/dashboard/farmgate-price` + `poetry run set-farmgate-price`). Porting the hardcoded dict would create a second source of truth for the CCC barème. |
| 13 | Watermarking | **Dropped**, replaced by access logging | WatchAI injects ±0.3 % deterministic noise on tonnages. An exporter reconciling their own volumes against a noised figure files a bug — incompatible with the Benchmark row. |
| 14 | GEPEX membership | **Config as data** | The hardcoded 11-name `GEPEX_MEMBERS` list becomes `ref_origin_entity.is_gepex_member`. |
| 15 | Freshness signalling | **`data_as_of` surfaced in the payload and the UI. No watchdog job.** | With manual ingestion there is no execution log to alert on. Staleness is made *visible to the user* (`Données au <mois>`) rather than alerted to ops. Revisit if/when ingestion is automated. |
| 16 | Fiscal analyses | **Out of scope** | Block ② has no tax row. WatchAI's 7 `create_tax_*` views are not part of the Compass offer. `valcaf` / `duties_taxes` still land (they cost nothing and back the stabilisation analytic), but no fiscal UI is built. |

**Open** (needs a call before the Benchmark slice):

- **`tenant_account.exporter_entity_id`** must be filled by hand and reviewed. A mis-mapping shows a client a competitor's book. No fuzzy matching, ever.
- Whether Origin Desk's `s/ CdC` grants are à-la-carte per contract (assumed yes, mirroring the podcast `option²` treatment).

---

## 1. What WatchAI actually is

| | `main` (frozen 2026-06-05) | `refonte-da-v2` @ `11336ef` (2026-08-14) |
|---|---|---|
| App | Streamlit monolith, `Webapp/webapp_tax.py`, 6 610 lines | **Next.js (app router) + FastAPI + DuckDB**, served under `/v2` |
| Storage | 3 parquet on disk | same 3 parquet — DuckDB is a query engine over them, **not** a database |
| API | **None** | **14 routes** — `/api/overview`, `/api/entities`, `/api/entity/{type}/{name}`, `/api/transformation`, `/api/report`, `/api/query`, `/api/ask`, export xlsx |
| Auth | `users.json` + bcrypt, Streamlit session | `users.json` + bcrypt behind a **JWT httpOnly cookie** |
| Tests | none | `test_bilan_matiere.py`, `test_multiseries.py`, `test_report.py` |
| Type hints | none | typed throughout |
| Infra | 1 VPS OVH, 1 Docker container, manual SCP deploy | unchanged |
| Cadence | Monthly, 7-step manual procedure, J+3 to J+11 after month end | unchanged |

Datasets (on `refonte-da-v2`):

| File | Rows × cols | Coverage |
|---|---|---|
| `Db_Master_Tax.parquet` | 172 712 × 18 | 2013-10-01 → **2026-07-31** — nominative customs export declarations |
| `Db_Master_Achats.parquet` | 3 245 × 7 | 2020-10-01 → **2026-07-01** — monthly purchases per exporter |
| `Db_Master_Broyage.parquet` | 163 × 12 | 2012-10-01 → **2026-04-01** ⚠️ — GEPEX-aggregated grindings (STATSER) |
| `Entity_Mappings.xlsx` | 588 aliases | Exporter / destinataire / déclarant / destination canonicalization |
| `Baremes/Baremes_Consolidés.xlsx` | 2012 → 2026 | **New** — full CCC barème, all postes, official format (see §11) |

19 MB total. **Data volume is a non-issue.** The cost is in the transform, the entitlements and the UI.

**The grinding gap is structural**: STATSER stops three months behind the other two sources. v2 solves it by *deriving* grinding from transformed exports rather than reading STATSER ([business-rules.md](business-rules.md) §4) — adopt that, do not try to fill the gap.

**Decision #1 is unaffected by v2.** A real API technically reopens "consume WatchAI's API", but the objection stands: it would make a single unmonitored OVH VPS a runtime dependency of a GCP product. What v2 changes is the **port reference**, not the integration model.

---

## 2. Port inventory — summary

Full detail: [port-inventory.md](port-inventory.md).

v2 `api/app/` — the port reference:

| Module / route | Verdict |
|---|---|
| `saison.py` — 3 DuckDB views over the parquet | **Adopt verbatim as our canonical schema** ([business-rules.md](business-rules.md) §0) |
| `data.transformation()` | **Port — highest value.** Material balance, `RENDEMENT_BROYAGE`, STATSER confrontation, per-source YTD |
| `data.overview()` · `entity()` · `entities()` | Port → `campaign`, `market-views`, `exporters` |
| `api/tests/test_bilan_matiere.py` | **Port as assertions**, not as prose |
| `bareme.py` + `Master_Data/Baremes/` | New asset, out of current scope (§11) |
| `auth.py` (JWT cookie, `users.json`) | Drop — Auth0 + `tenant_*` |
| `query.py` · `ai/ask.py` · `ai/report.py` | Drop — free-form querying + narrative, out of scope |
| `export.py` (xlsx) | Drop — `export_service.py` (CSV) is our pattern |
| `ai/destinataires.py` + `kb_destinataires.json` | N/A — `DESTINATAIRE*` not ingested (decision #7) |

v1 Streamlit — historical, ~3 000 of its 6 610 lines are auth/UI/Plotly/document-generation, all dropped. Only two rules remain v1-only and still need porting: `calc_growth` (250 t noise floor) and the stabilisation écart. Everything else is superseded by v2.

**Business semantics to port: ~250 lines. Code: zero.**

---

## 3. Data model

Domain: `pl_*` for observations, `ref_*` for reference. Nothing is contract-keyed — this is physical-origin data, not market data. No `tenant_id` anywhere (North Star: isolation is a read-time filter, never a row column).

```
pl_origin_ingest_batch            -- provenance of one manual load
  id UUID PK
  source VARCHAR                  -- "git" | "files"
  source_ref VARCHAR NULL         -- watch-ai commit SHA, when the source is a checkout
  source_branch VARCHAR NULL      -- e.g. "refonte-da-v2" — main is NOT the source
  source_committed_at TIMESTAMPTZ NULL
  ingested_at TIMESTAMPTZ
  ingested_by VARCHAR             -- operator handle (manual load = named human)
  row_counts JSONB                -- {"declarations": 172712, "purchases": 3245, "grindings": 163}
  source_hashes JSONB             -- sha256 per source file — the real batch identity
  data_as_of DATE                 -- newest period present → what the UI stamps
  restatement_summary JSONB NULL  -- months whose totals moved vs previous batch
  is_current BOOL                 -- exactly one true row

ref_origin_entity                 -- canonical exporters / destinations
  id UUID PK
  entity_type VARCHAR             -- exporter | destination
  source_name VARCHAR             -- WatchAI's *_SIMPLE value (their canonical)
  canonical_name VARCHAR          -- OURS — second normalization layer
  country_code VARCHAR NULL       -- destinations only (ISO-2)
  is_gepex_member BOOL
  UNIQUE(entity_type, source_name)

pl_origin_export_declaration      -- line-level, reduced projection
  id UUID PK
  ingest_batch_id UUID FK -> pl_origin_ingest_batch
  declaration_date DATE
  season VARCHAR(9)               -- "2025-2026", derived Oct→Sep
  exporter_entity_id UUID FK -> ref_origin_entity
  destination_entity_id UUID FK NULL
  port VARCHAR                    -- ABIDJAN | SAN PEDRO
  postar VARCHAR
  product_code VARCHAR            -- OUR canonical taxonomy, business-rules §2
  net_weight_kg BIGINT
  valcaf NUMERIC NULL             -- FCFA, absolute
  duties_taxes NUMERIC NULL       -- FCFA, absolute
  -- NO unique constraint: snapshot semantics, duplicates are legitimate data

pl_origin_purchase_monthly
  id UUID PK
  ingest_batch_id UUID FK
  period_date DATE                -- first of month
  season VARCHAR(9)
  exporter_entity_id UUID FK
  net_weight_kg NUMERIC

pl_origin_grinding_monthly        -- GEPEX-aggregate, no exporter dimension
  id UUID PK
  ingest_batch_id UUID FK
  period_date DATE
  season VARCHAR(9)
  tons_ground NUMERIC

pl_origin_flow_monthly            -- THE CUBE. The only table the API reads.
  id UUID PK
  ingest_batch_id UUID FK
  period_date DATE
  season VARCHAR(9)
  exporter_entity_id UUID FK
  product_code VARCHAR
  destination_entity_id UUID FK NULL
  port VARCHAR
  export_tonnes NUMERIC
  valcaf NUMERIC NULL
  duties_taxes NUMERIC NULL
  UNIQUE(ingest_batch_id, period_date, exporter_entity_id, product_code,
         destination_entity_id, port)
```

Expected cube size: ~1 100 declarations/month collapse into ~400–700 distinct cells × ~150 months ≈ **60–100 k rows**. The cube covers 100 % of the matrix; the line table exists so *we* own the transform, not because a feature needs it.

Migration: one Alembic revision, `down_revision = "r2m3n4o5p6q7"` (current head). Idempotent, shipped **via `main` only**.

---

## 4. Ingestion — `poetry run watchai-sync` (manual)

`backend/scripts/watchai_sync/` — `main.py`, `acquire.py`, `transform.py`, `db_writer.py`, `tests/`. Registered as `watchai-sync = "scripts.watchai_sync.main:main"`.

```bash
poetry run watchai-sync --source ../watch-ai --dry-run     # inspect, no write
poetry run watchai-sync --source ../watch-ai               # local DB
poetry run watchai-sync --source ../watch-ai --skip-compute  # land only, no cube
```

Flow:

1. **Acquire** — read `<source>/Master_Data/*.parquet` + `Entity_Mappings.xlsx` from the checkout. Batch provenance is the **sha256 of each file**; `git rev-parse HEAD` + commit date are recorded as optional metadata when the source is a checkout. **Refuse to run on a dirty working tree.** **Print `data_as_of` (max period per source) before writing** — git lagging the app is the normal case, not the exception (decision #5).
2. **Canonicalize** — upsert `ref_origin_entity` from `Entity_Mappings`. New aliases appear every month. `EXPORTATEUR` raw is degraded (contains literal `0`), so we start from `EXPORTATEUR_SIMPLE` and apply *our* normalization on top.
3. **Transform** — port `api/app/saison.py`'s three views to our schema: season derived (**including for `achats`**, where v2 takes it from the source file), product resolution with the digit-stripped POSTAR fallback, kg→tonnes, per-tonne ratios. See [business-rules.md](business-rules.md) §0–§3.
4. **Write** — insert the full snapshot under a new `ingest_batch_id`, then flip `is_current`. Previous batch retained until the next run, then pruned (keep N=2 for diffing).
5. **Diff** — compare per-month totals against the previous current batch. Any month whose totals moved is written to `restatement_summary` **and printed**. A silent restatement of a season a client has already seen is unacceptable.
6. **Compute the cube** — same command by default; `--skip-compute` separates.
7. **Fail loud** — unmapped entity, unknown POSTAR prefix, negative tonnage, or a total row-count regression → non-zero exit, no partial write.

### Governance of the prod write

A manual CLI writing 170 k rows into prod Cloud SQL through the IAP bastion sits in the third branch of [migrations-prod-via-main-only](../../.claude/rules/migrations-prod-via-main-only.md) §3 — *"un ordre direct du user, en pleine conscience qu'il sort du process"*. Two obligations follow:

- It needs a **runbook** (`docs/runbooks/watchai-ingestion.md`) so it is a repeatable documented operation, not an ad-hoc `psql`.
- **`pl_origin_ingest_batch` is the audit trail.** With no Cloud Run execution to point at, the DB must carry who loaded what, from which commit, when. That row is not optional bookkeeping — it is the only record the operation happened.

Default target is the **local** DB. Prod requires an explicit `--target prod` plus the bastion tunnel, and is a deliberate act.

---

## 5. Cube compute

Aggregates the three observation tables into `pl_origin_flow_monthly`. Runs inside `watchai-sync` by default.

- Assert one row per natural key before write (the [timeseries-uniqueness](../../.claude/rules/timeseries-uniqueness.md) guard — the balance ratios are cross-series; a fan-out corrupts them silently).
- Purchases (exporter×month) and grindings (GEPEX-aggregate×month) live at coarser grains than exports. **Do not join them into the export grain** — carry them separately, combine at query time.
- **The material balance is bean-equivalent arithmetic, not a subtraction of raw tonnages.** Transformed exports are a *product* weight and must be converted back via `RENDEMENT_BROYAGE = 0.80` before entering the balance. Adding them raw was the v1 bug that produced a 124 % `taux de sortie`. **The two "invariants" (`0 ≤ taux_sortie ≤ 100`, `solde ≥ 0`) are not invariants** — 2021-2022 legitimately reaches 108,1 % because 34 exporters shipping 102 829 t are absent from the purchase master. They ship as the publishable flag `outflow_exceeds_purchases`, never as an assertion. Full spec and the correction: [business-rules.md](business-rules.md) §4.3.
- **Grinding is derived, not read.** STATSER is no longer an input — it is compared against the derived figure, and the gap is published as a consistency signal ([business-rules.md](business-rules.md) §5). This removes the GEPEX-perimeter bias from the balance and recovers the three months STATSER lags by.

---

## 6. API surface ↔ commercial matrix

`app/services/origin_flow_service.py` + `origin_flow_transformers.py`, mirroring the `dashboard_service` / `dashboard_transformers` split. Routes under `/v1/dashboard/origin/*`.

| Matrix row ② | Endpoint | Entitlement key | Tiers | WatchAI source |
|---|---|---|---|---|
| Point campagne mensuel | `GET /dashboard/origin/campaign` | `read:watchai:campaign_monthly` (+ `:push`) | all 7 | Rapport Mensuel — Synthèse + YTD |
| Vues marché agrégées | `GET /dashboard/origin/market-views` | `read:watchai:market_views` | CP, EE, EP, XP, S+, OD | Analyse Volume/Saison, Achat/Saison, Transformation |
| Destinations & ports agrégés | `GET /dashboard/origin/destinations` | `read:watchai:destinations` | EE, EP, XP, S+, OD | `create_destinations_map` + `create_ports_distribution` |
| Benchmark « vos flux vs marché » | `GET /dashboard/origin/benchmark` | `read:watchai:benchmark` | EP, XP only | **net-new — does not exist in WatchAI** |
| Flux nominatifs & solde apparent | `GET /dashboard/origin/exporters` | `read:watchai:nominative` | EP, XP, S+ ; OD à la carte | `create_top_exporters` + Analyse Transformation |

All take `?season=YYYY-YYYY` and optionally `?month=YYYY-MM`. None take the daily `date` param (decision #10). Every payload carries `data_as_of` (decision #15).

### The Benchmark row is not a port

WatchAI has **no per-tenant view** — its `gepex_only` toggle is a global filter, not an identity. "Votre part, votre rang, vos destinations" is net-new and needs `tenant_account.exporter_entity_id`, a read-time filter (never a column on the cube), and `n/a` semantics for Signal+/Origin Desk: those tenants have no exporter identity, so the endpoint returns "not applicable", not `403`. The matrix distinguishes *not sold* (`—`) from *meaningless* (`n/a`) and the API must too.

---

## 7. Entitlement diff

Additions to `app/core/entitlements.py` (on top of `feat/per-client-entitlement`):

```python
# --- WatchAI (matrix block ②) — origin physical flows ------------------------
WATCHAI_CAMPAIGN = "read:watchai:campaign_monthly"
WATCHAI_CAMPAIGN_REDUCED = "read:watchai:campaign_monthly:reduced"  # reduced variant
WATCHAI_MARKET_VIEWS = "read:watchai:market_views"
WATCHAI_DESTINATIONS = "read:watchai:destinations"
WATCHAI_BENCHMARK = "read:watchai:benchmark"
WATCHAI_NOMINATIVE = "read:watchai:nominative"

WATCHAI_KEYS: frozenset[str] = frozenset({...})
ALL_ENTITLEMENT_KEYS = SECTION_KEYS | CHROME_KEYS | FEATURE_KEYS | DECISION_KEYS | EXPORT_KEYS | WATCHAI_KEYS
VARIANT_PAIRS[WATCHAI_CAMPAIGN] = WATCHAI_CAMPAIGN_PUSH
```

| Tier | WatchAI keys added |
|---|---|
| `coop_essentiel` | `campaign_monthly:reduced` |
| `coop_premium` | `campaign_monthly`, `market_views` |
| `export_essentiel` | `campaign_monthly:reduced`, `market_views`, `destinations` |
| `export_premium` | `campaign_monthly`, `market_views`, `destinations`, `benchmark`, `nominative` |
| `export_pro` | same as `export_premium` |
| `signal_plus` | `campaign_monthly`, `market_views`, `destinations`, `nominative` (no benchmark — n/a) |
| `origin_desk` | `campaign_monthly`, `market_views`, `destinations` ; `nominative` à la carte (`s/ CdC`) |

The `_EXPORT_PRO_KEYS = _EXPORT_PREMIUM_KEYS` alias still holds (they coincide on block ②), but its code comment — *"differ only in WatchAI/Formation/seats"* — must be rewritten, because the reason it held is no longer "WatchAI isn't modeled".

**Block inclusion is derived from the held key set**, never from a hardcoded edition list and never from a user toggle. WatchAI's `SECTIONS DU RAPPORT` multiselect is an ops control; reproducing it would let a Coop Essentiel user tick "Flux nominatifs".

---

## 8. Frontend — Section VI

**`ORIGIN FLOWS`** in [dashboard-page.tsx](../../frontend/src/pages/dashboard-page.tsx), after `WeatherUpdateCard`.

- `DashboardErrorBoundary` + `SectionHeader` roman numeral **VI** — same as sections I–V.
- `EditorialTabs`: `Campagne` / `Marché` / `Destinations` / `Benchmark`, each rendered only if its key is held.
- Recharts, monochrome + signal palette. Reuse `Eyebrow`, `DataValue`, `DotSeparator`.
- New `OriginPeriodSelector` (season + optional month) — **not** `DateSelector`, not wired to `DashboardDateContext`.
- `Données au <mois>` stamp from `data_as_of`, always visible.
- `useOriginFlows.ts` — React Query, 24 h stale time.
- `n/a` empty state (benchmark without an exporter identity) distinct from the 403 state.

Historical deep-dive tables go on `/dashboard/historical`.

---

## 9. Rollout

| Phase | Scope | Gate |
|---|---|---|
| **0** | Merge `feat/per-client-entitlement` to `main`, flip `ENTITLEMENTS_ENFORCED` | Prerequisite — the WatchAI keys have nowhere to live otherwise |
| **1** | Migration (via `main`) + models + `watchai-sync` CLI + reconciliation test — **local DB only** | July 2026 golden values reproduced exactly |
| **2** | First prod load via bastion + runbook | `pl_origin_ingest_batch` row exists, totals verified |
| **3** | Service + 4 endpoints + entitlement keys | Backend `403`s correctly per tier |
| **4** | Section VI + tabs + hooks | Ships dark behind the keys; grant per tenant |
| **5** | Benchmark: `tenant_account.exporter_entity_id`, mapping review, endpoint, tab | Manual mapping signed off per client |

**Reconciliation gate on Phase 1** — golden values from the published July 2026 report. Scope: **all operators** (GEPEX toggle OFF), all products, all ports. Season Oct→Sep, YTD at equivalent period (Oct→Jul both seasons).

```
Juillet 2026    exports      147 866 t     achats        81 582 t
                VALCAF       326 784 M     taxes         40 765 M FCFA
YTD 2025-2026   exports    1 710 347 t     achats     2 087 867 t
YTD 2024-2025   exports    1 428 071 t     achats     1 622 077 t
Mix produit YTD 2025-2026 (t) :
  FEVES 1 236 439 · MASSE 180 891 · HORS GRADE 133 840
  BEURRE 109 329 · CHOCOLAT 38 793 · POUDRE 11 055
Mix produit YTD 2024-2025 (t) :
  FEVES   948 931 · MASSE 159 761 · HORS GRADE 151 436
  BEURRE  110 085 · CHOCOLAT 44 303 · POUDRE  13 556
```

> ✅ **VERIFIED 2026-08-17** against `refonte-da-v2` @ `11336ef` — **8/8 exact**, to the tonne and to the million FCFA, including both product mixes. The transform spec ([business-rules.md](business-rules.md) §1–§3, §6) is proven correct *before* any Compass code exists: season Oct→Sep, YTD equivalent period, kg→tonnes, `PRODUIT SIMPLE` taxonomy, all-operator perimeter, VALCAF/taxes sums, achats from `POIDS_NET_KG`.
>
> Phase 1's job is to **reproduce a verified result**, not to discover one. Any divergence is a bug in our implementation, never a reason to adjust the fixture.

**Two derived figures deliberately diverge from the published report** — assert them explicitly rather than tolerating a mismatch:

| Figure | WatchAI report | Compass | Why |
|---|---:|---:|---|
| `TOTAL TRANSFORMÉ` | 473 907 t (27,7 %) | **340 068 t (19,9 %)** | HORS GRADE is bean-equivalent ([business-rules.md](business-rules.md) §2). Assert `473 907 − 133 840 = 340 068`; the delta must be exactly the HORS GRADE line. |
| `taux de sortie` / `solde` | v1 double-counted | bean-equivalent (÷ 0,80) | v1 bug, fixed in v2 ([business-rules.md](business-rules.md) §4) |

The six product lines match exactly; only these derived aggregates move. Pinning the delta to a single known cause is a stronger test than tolerating an approximate match.

### Sizing

> Estimate as written before the build, kept for calibration. Actual: Phase 1 + cube + service + endpoints + entitlements + Section VI landed in two PRs (#93, #94). The benchmark line remains unbuilt.

| Lot | Effort |
|---|---|
| **Phase 1** — migration + 6 models + `watchai-sync` + reconciliation test | **1.5 wk** |
| Cube compute + service + 4 endpoints + tests (≥80 %) | 2 wk |
| Entitlement extension (assumes Phase 0 done) | 0.5 wk |
| Section VI + 4 tabs + hooks + tests | 2 wk |
| Benchmark (net-new + identity mapping) | 1 wk |
| **Total** | **≈ 6 wk, 1 engineer** |

Literal porting is ~3 days of that.

---

## 10. Risks

1. **Spec drift against a moving branch.** `refonte-da-v2` is under active development (155 files, 22 561 lines, last commit 3 days before this writing). We are pinned to `11336ef`; every re-sync must re-run the reconciliation and diff `data.py` / `saison.py` for changed constants. `RENDEMENT_BROYAGE` moving from 0,80 silently would restate every balance we publish. **Now the top risk** — it displaced taxonomy, which is settled.
2. **Product taxonomy** — settled for HORS GRADE (business-rules §2, three independent confirmations), but the `COQUES`/`LIQUEUR` fallback hole remains dormant. The fail-loud in the transform is the guard.
3. **Unit mixing** — kg vs tonnes vs FCFA/kg vs FCFA/t, plus the new bean-equivalent conversion (÷ 0,80). Adding a product weight to bean tonnages is the exact bug v1 shipped.
4. **Silent restatement** — history moves between batches by design (decision #8). Without the diff in §4 step 5, a client's saved figure changes under them with no trace.
5. **Git lags the app, silently** — data commits are optional in Julien's procedure (it ends at `scp`, not `git push`), and the July data landed only on a feature branch. `main` was 2 months stale when we first looked. Mitigated by printing `data_as_of` before every write (§4 step 1) — never assume the checkout is current.
6. **Manual ingestion has no automated staleness signal** (decision #15). Mitigated by surfacing `data_as_of` to the user, not by alerting ops.
7. **Manual prod write** sits outside the normal migration process. Mitigated by the runbook + `pl_origin_ingest_batch`. Never a `psql` one-off.
8. **Identity mis-mapping on benchmark** — showing a client a competitor's book. Manual review, no fuzzy matching, and a test asserting `exporter_entity_id IS NULL → n/a`.
9. **Published transformation rate.** Compass will show 19,9 % where WatchAI shows 27,7 %. Both are defensible arithmetic on different definitions; ours is the correct one, and it is *lower*. Brief the commercial side before a client asks — this is a politically sensitive figure in Côte d'Ivoire.
10. **Residual, unrelated**: `Db_Master_Tax.xlsx` / `Db_Master_Achats.xlsx` are tracked in the `watch-ai` git history. Our ingestion now *depends* on that (decision #5) — a future `git filter-repo` on that repo breaks this pipeline. Coordinate before any history rewrite.

---

## 11. Out of current scope — the consolidated barème

`refonte-da-v2` adds `Master_Data/Baremes/Baremes_Consolidés.xlsx` + `api/app/bareme.py`: the **full CCC barème 2012→2026, all postes, official format**, queryable (`saisons()`, `campagne()`, `poste()`, `find_postes()`), rebuilt from WORKINGS + CAYAT + the official FR publication.

This is materially richer than `pl_official_farmgate_price`, which holds farmgate reference prices for CIV/Ghana — not the full cost decomposition. It backs the reversement/soutien analysis end-to-end.

**Not in this scope**, and deliberately so: no row of matrix block ② requires it, and decision #12 (one source of truth for the CCC barème) must not be re-opened casually. But it is the strongest candidate for a follow-up, and it would upgrade the stabilisation analytic ([business-rules.md](business-rules.md) §9) from "average vs one reference price" to a real cost-structure comparison. Flag for a separate decision, do not smuggle it in.

---

## Appendix — implementation checklist

**DB / migrations**
- [ ] Alembic revision (`down_revision = "r2m3n4o5p6q7"`): `pl_origin_ingest_batch`, `ref_origin_entity`, `pl_origin_export_declaration`, `pl_origin_purchase_monthly`, `pl_origin_grinding_monthly`, `pl_origin_flow_monthly`.
- [ ] Later revision: `tenant_account.exporter_entity_id` (Phase 5).

**Backend**
- [ ] `app/models/origin.py` — 6 SQLAlchemy models.
- [ ] `scripts/watchai_sync/` — `acquire.py` (git checkout, dirty-tree refusal), `transform.py`, `db_writer.py`, `main.py` with `--source` / `--dry-run` / `--skip-compute` / `--target`.
- [ ] Restatement diff + printed summary.
- [ ] Cube compute + uniqueness assert.
- [ ] `app/services/origin_flow_service.py` + `origin_flow_transformers.py`.
- [ ] `app/schemas/origin.py` — response models, all carrying `data_as_of`.
- [ ] `app/api/api_v1/endpoints/origin.py` + router registration.
- [ ] `entitlements.py` — 6 keys, `VARIANT_PAIRS` entry, 7 tier deltas.
- [ ] `pyproject.toml` — `watchai-sync` script.
- [ ] **No** `Dockerfile.jobs` change, **no** `deploy.yml` job, **no** Cloud Scheduler entry.

**Frontend**
- [ ] `src/components/origin/` — section VI + 4 tab components.
- [ ] `src/hooks/useOriginFlows.ts`, `OriginPeriodSelector`, `src/types/origin.ts`.
- [ ] `n/a` empty state distinct from the 403 state.

**Testing**
- [ ] Unmapped entity → fail; unknown POSTAR → fail; dirty tree → refuse.
- [ ] Re-run of the same commit → identical state.
- [ ] Restatement detected and reported when a prior month's total moves.
- [ ] Cube uniqueness assert; grain-mixing regression (grinding must not fan out across exporters).
- [ ] Service: tier → 200/403 matrix for all 6 keys × 7 tiers.
- [ ] Benchmark: `exporter_entity_id IS NULL` → n/a, never a global view.
- [ ] **Reconciliation against the July 2026 golden values above.**

**Ops**
- [ ] `docs/runbooks/watchai-ingestion.md` — pull the checkout, run dry, run local, verify, then prod via bastion.

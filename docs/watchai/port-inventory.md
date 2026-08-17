# WatchAI Port Inventory — what moves, what dies

> Companion to [watchai-integration.md](watchai-integration.md).
>
> **Reference source (2026-08-17)**: `plakoplister/watch-ai` @ **`11336ef`**, branch **`refonte-da-v2`**. WatchAI has been rebuilt as **FastAPI + DuckDB + Next.js**; the v2 `api/app/` is typed, tested and current, and is now the **port reference**. `Webapp/webapp_tax.py` @ `36d8f89` (6 610 lines, Streamlit, frozen 2026-06-05, carries a known material-balance bug) is **historical** — marked *(v1)* below.
>
> ⚠️ Active branch. Pinned to `11336ef`. Re-sync deliberately, never follow `HEAD`.
>
> **Verdicts**: `PORT` = the logic moves (rewritten in our idiom) · `REPLACE` = we already have an equivalent · `DROP` = no Compass counterpart, do not rebuild · `SKIP` = out of commercial scope · `N/A` = source columns not ingested (reduced projection, [watchai-integration.md](watchai-integration.md) decision #7).

---

## Headline

**We port ~250 lines of semantics and zero lines of code.**

That conclusion survived the v2 rewrite, but the *reason* changed. Against v1 the argument was that the code was unportable — Streamlit widgets, Plotly figures and 3-line `groupby`s interleaved in one 6 610-line file. Against v2 the argument is different and stronger: **v2 is well-built, and built for a different runtime.** FastAPI + DuckDB-over-parquet + JWT cookies + Next.js is a coherent stack that is not ours (FastAPI + Postgres + Auth0 + React/Vite). Lifting it would mean importing a second data engine and a second auth model into Compass.

What we take from v2 is what it is genuinely good at: **an explicit, tested specification** of the origin-flow semantics. See [business-rules.md](business-rules.md).

---

## 1. v2 API surface → Compass mapping

`api/app/main.py` exposes 14 routes. Mapped against matrix block ②:

| v2 route | Module | Compass verdict |
|---|---|---|
| `GET /api/health` | `main` | DROP |
| `POST /api/auth/login` · `logout` · `GET /me` | `auth` | **DROP** — Auth0 + `tenant_*`. v2 keeps `users.json` + bcrypt behind a JWT cookie; no convergence to seek |
| `GET /api/overview` | `data.overview()` | **PORT** → `/dashboard/origin/campaign` + `market-views` |
| `GET /api/entities` | `data.entities()` | **PORT** (partial) → feeds `ref_origin_entity`; the listing UI is not a matrix row |
| `GET /api/entity/{type}/{name}` | `data.entity()` | **PORT** → `/dashboard/origin/exporters` (gated `nominative`) and the raw material for `benchmark` |
| `GET /api/transformation` | `data.transformation()` | **PORT — highest value.** The material balance. Spec in [business-rules.md](business-rules.md) §4–§5 |
| `GET /api/report` · `POST /api/report/generer` | `report`, `report_store`, `ai/report` | **PORT metrics only**; narrative DROP (decision #4) |
| `GET /api/export/entity.xlsx` · `POST /api/export.xlsx` | `export` | **DROP** — `export_service.py` (CSV) is our pattern |
| `POST /api/ask` | `ai/ask` | **DROP** — free-form LLM querying, out of scope |
| `POST /api/query` | `query` | **DROP** — spec-driven ad-hoc query engine; our endpoints are fixed-shape |
| `GET /api/destinataires/{country}` | `ai/destinataires`, `kb_destinataires.json` | **N/A** — `DESTINATAIRE*` not ingested |

`api/app/saison.py` is **the transform spec** — its three DuckDB views are adopted verbatim as our canonical schema ([business-rules.md](business-rules.md) §0). `api/app/bareme.py` + `Master_Data/Baremes/` is a **new asset, out of current scope** — see [watchai-integration.md](watchai-integration.md) §11.

### v2 tests — take these as tests, not as prose

| Test | Why it matters |
|---|---|
| `api/tests/test_bilan_matiere.py` | Encodes the material-balance invariants (`0 ≤ taux_sortie ≤ 100`, `solde ≥ 0`, mode-independence, bean-equivalent arithmetic). **Port mode-independence and the bean-equivalent arithmetic as assertions; do NOT port the two range invariants** — they fail on our own history (2021-2022 = 108,1 %), see [business-rules.md](business-rules.md) §4.3. |
| `api/tests/test_multiseries.py` | Multi-series engine — DROP with `query.py` |
| `api/tests/test_report.py` | Report builder — partially relevant to the metrics |

---

## 2. v1 Streamlit — what remains relevant

| Slice | ~Lines | Verdict |
|---|---:|---|
| Streamlit auth / sessions / CSS / header | 1 000 | DROP |
| Superadmin console, user CRUD, log viewer | 500 | DROP — Sentry + Cloud Logging + provisioning CLI |
| 20 Plotly `create_*` builders | 600 | DROP — rewrite in Recharts |
| Excel-with-charts + PDF report generator | 700 | DROP |
| Perplexity + Claude Opus monthly narrative | 400 | **DROP — out of scope** (§4) |
| Parquet loading + `st.cache_data` | 150 | REPLACE — superseded by `saison.py`, then by SQL |
| `data_watermarking.py` | 203 | DROP — **v2 dropped it too** |
| `db_sync.py` | 116 | DROP — dead code |
| **Business semantics still v1-only** | ~80 | **PORT** — `calc_growth` (L5486), stabilisation (L5552+) |

`Webapp/vue_ensemble.py`, `constructeur.py`, `prototype_explorer.py` (new on this branch): superseded by their v2 API equivalents. Read `api/app/data.py` instead.

---

## 3. Aggregations → SQL

Each v1 `create_*` builder is 3–6 lines of pandas plus 30+ of Plotly. v2 already expresses the same cuts as DuckDB SQL. Both are specs for a `GROUP BY` on `pl_origin_flow_monthly`; neither is code we import.

| Cut | v1 | Serves |
|---|---|---|
| by season | `create_season_evolution` L2015 | market-views |
| by month, season-ordered | `create_monthly_pattern` L2060 | market-views |
| top exporters | `create_top_exporters` L2103 | exporters *(nominative)* |
| by destination | `create_destinations_map` L2140 | destinations |
| by port | `create_ports_distribution` L2178 | destinations |
| product mix | `create_products_mix` L2207 | market-views |
| monthly timeline | `create_monthly_timeline` L2239 | market-views |
| top declarants | `create_top_declarants` L2546 | **N/A** |

**SKIP** — no matrix row (decision #16): the six `create_tax_*` builders (L2270–L2546).

**N/A by projection** — the reduced column set drops `DECLARANT*`, `DESTINATAIRE*`, `DECLARATION`, raw `EXPORTATEUR`, `TAX %`, `CAF/kg`. The transitaire ranking and the destinataire cuts (including v2's `/api/destinataires/{country}` and `kb_destinataires.json`) are therefore **not rebuildable in Compass** — reversing that means re-opening decision #7.

---

## 4. Narrative — out of scope, not consolidated

| v1 symbol | Line |
|---|---:|
| `fetch_market_context_from_perplexity` | 1112 |
| `get_or_refresh_market_context` (+ `load/save`, `log_api_call`) | 1263 |
| `fetch_opus_strategic_analysis` (+ `load/save`) | 1326 |
| v2 equivalents | `api/app/ai/ask.py`, `ai/report.py` |

Two reasons, the second load-bearing:

1. We already run `cc-press-review-agent`, `cc-daily-analysis`, `cc-ensemble-explainer`, `cc-compass-brief`, `cc-compass-brief-ensemble`. A fourth parallel LLM path with its own JSON cache is duplication. Dropping it removes `PERPLEXITY_API_KEY` entirely.
2. **These sections encroach on Compass CC's product.** §8 of the WatchAI monthly report issues futures-hedging instructions (entry zones, hedge ratios, stops) from a generic LLM over a Perplexity dump, disconnected from any computed signal — and in the July 2026 edition, cached from a run two months earlier, contradicting its own tables by 20 % on volumes and 3× on the CAF gap. Two engines issuing hedging advice inside one bundle is a governance liability, not a feature to migrate.

**Nothing from §7–§8 of the monthly report is ingested.** Compass takes only the computed data of §1–§6.

`PRIX_OFFICIELS` *(v1 L5259, hardcoded inside a function body)*: DROP. `pl_official_farmgate_price` + `/dashboard/farmgate-price` + `poetry run set-farmgate-price` already own the CCC barème.

---

## 5. What actually ships

| Asset | Source | Destination |
|---|---|---|
| **`Entity_Mappings.xlsx`** — 588 aliases, 4 sheets | `Master_Data/` | `ref_origin_entity` |
| Canonical schema (3 DuckDB views) | `api/app/saison.py` | ingestion transform |
| Product resolution + POSTAR fallback | `saison.py` `_TAX_SQL` | transform (fail-loud on the `ELSE`) |
| `FEVES_PRODUITS` / `TRANSFO_PRODUITS` | `api/app/data.py:282-283` | `is_bean_equivalent` |
| **`RENDEMENT_BROYAGE = 0.80`** | `api/app/data.py:292` | material balance |
| Material balance + 3 ratios + 2 invariants | `data.transformation()` | `origin_flow_service` |
| STATSER confrontation (`ecart_t`) | `data.transformation()` | `origin_flow_service` — new analytic |
| Per-source YTD blocks (`_bloc`) | `data.transformation()` | `origin_flow_service` |
| `part_transfo_pct` per exporter | `data.transformation()` | `/origin/exporters` |
| `GEPEX_MEMBERS` (11 names) | `api/app/auth.py` | `ref_origin_entity.is_gepex_member` |
| `COUNTRY_NAMES` (ISO-2 → FR) | *(v1 L1021)* | `ref_origin_entity.country_code` |
| `calc_growth` + 250 t floor | *(v1 L5486)* | `origin_flow_service` |
| Écart CAF réel vs barème | *(v1 L5552+)* | `origin_flow_service` |
| Bilan-matière invariants | `api/tests/test_bilan_matiere.py` | our test suite |

Everything else: DROP, REPLACE, SKIP or N/A.

---

## 6. What v2 changed since the first inventory

Written against v1, corrected 2026-08-17:

| Claim (v1-era) | Status |
|---|---|
| "No API — zero endpoints" | **False for v2** — 14 FastAPI routes |
| "No tests, no CI" | **False for v2** — 3 pytest modules |
| "No type hints anywhere" | **False for v2** — `from __future__ import annotations`, typed throughout |
| "No database" | Still true in substance — DuckDB is a query engine **over the same parquet**, no persistence. Our ingestion source is unchanged. |
| "Material balance: `Achats − Exports_fèves − Broyage`" | **Superseded** — v1 double-counted; v2 derives grinding from transformed exports ÷ 0,80 |
| "Common month window across the 3 series" | **Superseded** — per-source YTD windows |
| "Grain-mixing guard mandatory" | **Reduced** — the balance no longer reads STATSER, so the GEPEX bias only affects the confrontation |

Still true, and unaffected by v2:

1. **No per-tenant view.** The `gepex_only` toggle is a global filter, not an identity. `read:watchai:benchmark` remains net-new and needs `tenant_account.exporter_entity_id`.
2. **No weather, ENSO, signal or technical indicators.** Block ② adds nothing there.
3. **Decision #1 stands.** The existence of an API technically reopens "consume WatchAI's API", but the objection is unchanged: it would make the OVH VPS a runtime dependency of a GCP product. What changed is the **port reference**, not the integration model.

### Convergence worth tracking

v2 ships `report.build(saison_sel, audience="gepex")` and a `_masque(nom, i)` helper — **editions by audience and nominative masking**, the same model as our entitlement design. Worth coordinating with Julien rather than diverging: if both products settle on the same audience vocabulary, the commercial matrix stays legible across the two.

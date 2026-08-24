# Per-Client Entitlement & Tenancy — Design

> **Status**: **LIVE AND ENFORCED IN PRODUCTION since 2026-08-24** (`ENTITLEMENTS_ENFORCED=true`, revision `backend-00255-mqs`). Full stack shipped: backend gates, frontend gating, audio signed URLs. Six Auth0 logins seated on the `internal` account. Tiers reconciled to the commercial matrix "Compass CC block, July 2026".
> **Day-to-day operations → [docs/runbooks/entitlement-enforcement.md](../runbooks/entitlement-enforcement.md)** (onboarding a client, rollback, the backfill CLI, symptom→cause). This document is the design; the runbook is the procedure.
> **Short-term goal**: per-client **display entitlement** (show/hide sections, features, export series).
> **Long-term goal**: **commodity isolation** (one client subscribes to cocoa *and/or* coffee in a single solution), designed-for-now so it is zero-rework later.
> **Guardrails**: [north-star-alignment](../../.claude/rules/north-star-alignment.md) · [timeseries-uniqueness](../../.claude/rules/timeseries-uniqueness.md) · [migrations-prod-via-main-only](../../.claude/rules/migrations-prod-via-main-only.md) · North Star MCD ([The-North-Star.md](../../The-North-Star.md)).

---

## 0. Locked decisions

| # | Fork | Decision | Consequence |
|---|---|---|---|
| 1 | Nature of "hide" | **Hard security boundary** | Real `403` on every gated endpoint + **signed URLs** for the unauthenticated `/audio/stream`. The frontend hide is cosmetic-only. |
| 2 | Source of truth | **DB config-as-data** | 3 small tables + a `_current` view, temporal append-only (the `pl_algorithm_config` pattern). Auth0 stays a pure IdP. |
| 3 | Provisioning | **Manual CLI/SQL** | No admin UI. `poetry run` seed scripts, in the spirit of `set-farmgate-price`. |
| 4 | Scope (iteration 1) | **Sections + CSV export** | Gate the 6 sections + audio + ticker + the 7 export series. |
| 5 | Default for a login with no tenant row | **Default-deny** | Every existing login must be seeded before enforcement is flipped on (§9 backfill is mandatory). |
| 6 | Ticker / SignalHero | **Gateable** (not a free baseline) | No always-on content teaser; only true chrome + auth + calendar stay ungated. |
| 7 | Provisioning unit | **Tier templates** | Ops assign a tier; the template expands into per-key grant rows. Raw per-key grants still possible. |
| 8 | Entitlement cache TTL | **10 minutes** | Bounds staleness of a downgrade; avoids a DB hit per request; still tighter than Auth0's 6h JWKS revocation latency. |
| 9 | Tier catalogue | **7 tiers from the commercial matrix** | `coop_essentiel · coop_premium · export_essentiel · export_premium · export_pro · signal_plus · origin_desk` (COOP / EXPORT orientations). Replaces the placeholder starter/pro/enterprise. |
| 10 | Reduced variants | **Sub-keys** | Weather full (`read:section:weather`) vs weekly `…:summary`; hedge full vs `…:initiation`. A tier holds one; endpoints serving both accept either (any-of). |
| 11 | Seat counts | **`max_seats`, soft cap** | Contracted dashboard seats (1/2/2/3/4/4/4) stored on `tenant_account`. `link-seat` WARNS past the cap, never blocks. |
| 12 | Coop Essentiel | **1-seat minimal dashboard** | A real tier with `max_seats=1`; its dashboard shows only the guaranteed-price reference (Section II = farmgate block). (Was push-only/0-seat; bumped to 1 for the minimal dashboard.) |
| 13 | Existing users / staff | **`internal` full-access marker** | A non-commercial tier that resolves to the COMPLETE catalogue **at read-time** (`resolve_principal` short-circuit), so it always includes future keys with no re-backfill. Used to grandfather the current base into "the whole app" before the flip. |

**Core principle** (North Star): *pipelines are shared, tenants subscribe.* Entitlement/isolation lives entirely in the **serving layer** — the pipeline (`app/engine/`, scrapers) never sees a tenant.

---

## Part 1 — Short-term: entitlement

### 1. The entitlement vocabulary (keys)

Finite, opaque, hierarchical. Naming: `read:<domain>:<name>` (scope-style, keeps it Auth0-migratable).

**Sections** — map ~1:1 to the six `DashboardErrorBoundary` blocks in [dashboard-page.tsx](../../frontend/src/pages/dashboard-page.tsx):

| Key | Frontend block | Backend endpoint(s) to gate |
|---|---|---|
| `read:section:signal` | `SignalHero` | `/dashboard/position-status`, `/dashboard/recommendations` |
| `read:section:podcast` | `PodcastPlayer` | `/dashboard/audio`, `/audio/info`, **`/audio/stream` (signed)** |
| `read:section:market` | `MarketAnalysis` | `/dashboard/indicators-grid`, `/dashboard/recommendations` |
| `read:section:chart` | `PriceChart` | `/dashboard/chart-data` |
| `read:section:news` | `NewsCard` | `/dashboard/news`, `/dashboard/news/sentiment` |
| `read:section:weather` | `WeatherUpdateCard` (full) | `/dashboard/weather` (gate = any-of full **or** summary) |
| `read:section:weather:summary` | `WeatherUpdateCard` (weekly "résumé hebdo") | `/dashboard/weather` — frontend renders the reduced variant when only this key is held |

**Decisions** — product features from the matrix's Compass CC block. Catalogue keys today (they gate no built endpoint yet; the gate attaches when the feature ships):

| Key | Matrix row |
|---|---|
| `read:decision:physical_sale` | Décision de vente physique (calc "vendre ou stocker") |
| `read:decision:hedge` | Décision de couverture forward (full) |
| `read:decision:hedge:initiation` | …reduced "initiation" variant |

**Chrome** — the live band lives in [dashboard-layout.tsx](../../frontend/src/components/dashboard-layout.tsx), not the page:

| Key | Frontend block | Backend endpoint(s) |
|---|---|---|
| `read:chrome:ticker` | `LiveSignalStrip` + `MastheadPulse` | `/dashboard/position-status`, `/dashboard/chart-data`, `/dashboard/indicators-grid` (shared with `signal`) |

**Features** — ensemble/premium panels that already `404` on non-ensemble dates (reuse that exact 404/hide shape):

| Key | Gates |
|---|---|
| `read:feature:ensemble_diagnostics` | `/dashboard/ensemble-diagnostics` |
| `read:feature:specialist_votes` | `/dashboard/specialist-votes` |
| `read:feature:judge_overlay` | `/dashboard/judge-diagnostics` |
| `read:feature:macro_panel` | `/dashboard/macro-panel` |
| `read:feature:positioning` | `/dashboard/positioning` |
| `read:feature:farmgate` | `/dashboard/farmgate-price` |

**Export series** — the 7 keys of `EXPORT_SERIES` ([export_service.py](../../backend/app/services/export_service.py)):

`read:export:ohlcv` · `read:export:indicators` · `read:export:fx` · `read:export:cot_eu` · `read:export:cot_us` · `read:export:stocks` · `read:export:weather`

> CSV export is **not** in the packaged Compass CC matrix (that's the separate "Enterprise API" co-construct). These keys stay in the catalogue (the endpoint exists and is gated per-series) but are granted by **no tier by default** — grant à la carte.

**Ungated baseline** (functional necessity + identity only): `/auth/*`, `/dashboard/non-trading-days` (calendar/date-picker must work), and static chrome (masthead title, colophon). **Everything content-bearing is gateable** (decision #6).

### 2. Tier templates (Compass CC commercial matrix, July 2026)

Named bundles that expand into per-key grants at provisioning time. The **stored truth stays per-key rows** — tiers are just a shortcut. Source: internal "Matrice de versioning par blocs", ① COMPASS CC block. WatchAI (②) and Formation (③) are separate products, not modeled here.

`CE`=coop_essentiel · `CP`=coop_premium · `EE`=export_essentiel · `EP`=export_premium · `XP`=export_pro · `S+`=signal_plus · `OD`=origin_desk.

| Key / matrix row | CE | CP | EE | EP | XP | S+ | OD |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **max_seats** | 1¹ | 2 | 2 | 3 | 4 | 4 | 4 |
| `read:decision:physical_sale` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `read:decision:hedge` (initiation on CE) | init | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `read:section:signal` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| conviction (`ensemble_diagnostics`+`specialist_votes`+`judge_overlay`) | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `read:section:podcast` | ✅ | ✅ | ✅ | ✅ | ✅ | opt² | opt² |
| `read:feature:farmgate` (prix garantis) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `read:section:weather` (full / **:summary**) | sum | full | sum | full | full | full | full |
| technique+FX (`section:market`+`feature:macro_panel`)³ | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `read:feature:positioning` | — | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| `read:section:news` (press) | — | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| `read:section:chart` (historique+S/R) | — | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| `read:chrome:ticker` | ✅ réduit¹ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `read:watchai:campaign_monthly` | `:reduced`⁴ | ✅ | `:reduced`⁴ | ✅ | ✅ | ✅ | ✅ |
| `read:watchai:market_views` | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `read:watchai:destinations` | — | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| `read:watchai:benchmark` | — | — | — | ✅ | ✅ | n/a | n/a |
| `read:watchai:nominative` | — | — | — | ✅ | ✅ | ✅ | ✅ |

⁵ **Three ways of saying "not by default", and they are not interchangeable.**
`—` = not sold (403). `n/a` = meaningless — Signal+ and Origin Desk have no
exporter identity, so `/origin/benchmark` is simply absent from their template.
`s/ CdC` = sold separately, so Origin Desk's nominative key is grantable per
account but not in the default bundle. A test that expects 200 for Origin Desk on
`/origin/exporters` is asserting the wrong thing.

The benchmark is the **only per-tenant view in the product**. Its identity lives
on `tenant_account.exporter_entity_id`, is filled by hand (`poetry run
map-exporter`) and is applied **at read time** — never a column on `pl_origin_*`,
which stays tenant-free. The endpoint reads it from the authenticated principal
and accepts no exporter parameter: a client-supplied id would let any Export
Premium account open a competitor's book.

¹ **Corrected 2026-08-17.** Coop Essentiel was specified as push-only with 0 seats and no ticker; it is now a **1-seat dashboard** and holds `chrome:ticker` like everyone else. The band is *chrome* — the rows sold inside it are gated **per cell** by `LiveSignalStrip` against `read:section:market` (Volume·OI·RSI·MACD·%K·ATR·V/OI), `read:feature:positioning` (Stock EU/US·COT MM EU/US) and `read:feature:macro_panel` (FX DXY). What is left when a tier holds none of the three is `Signal · ICE LDN · DoD · YTD · Session`. There is deliberately **no `chrome:ticker:summary` variant**: a reduced band falls out of the keys a tier already holds, and the same filter closed a real leak where Export Essentiel — which does not buy "Positionnement fonds & fondamentaux" — was seeing stocks and COT in the band. The queries behind an ungated cell are skipped (`enabled: false`), not merely unrendered, so an unentitled viewer no longer generates a 403 per page load.
² Podcast is **"option"** on Signal+/Origin — à la carte, so **not** in the default template; grant separately.
³ ENSO (matrix "prix garantis + ENSO") travels with `macro_panel`, so Coop Essentiel gets `farmgate` but not the ENSO sub-panel.

⁴ `read:watchai:campaign_monthly:reduced` — the campaign row **without** the market views, so Section VI renders a single untabbed panel. Named `:push` until 2026-08-17, when the push channel was dropped in favour of the 1-seat dashboard. Renaming an entitlement key needs **no data migration**: `resolve_principal` selects keys without validating them against the catalogue, so a stale grant is inert; re-template the account with `poetry run set-tier` to pick the new key up.

`export_pro` == `export_premium` on the Compass CC surface (they differ only in WatchAI/Formation/seats). Source of truth: `TIER_TEMPLATES` + `TIER_MAX_SEATS` in [entitlements.py](../../backend/app/core/entitlements.py) (a code constant; promote to a `tenant_tier_template` table if ops need to edit bundles without a deploy).

### 3. Data model — 3 tables + 1 view

Domain = `reference` today (eventual `tenant` PG schema per North Star). Reuse the temporal append-only shape verbatim from `pl_algorithm_config` (`effective_from` / `active` + a `_current` view).

```
tenant_account            -- the client / org
  id UUID PK
  code VARCHAR UNIQUE               -- "acme": stable handle for CLI
  name VARCHAR
  tier VARCHAR                      -- one of the 7 matrix tiers (provenance of the grant set)
  locale VARCHAR                    -- North Star tenant.account.locale
  max_seats INTEGER                 -- contracted dashboard seats (soft cap; 0 = push-only)
  algorithm_version_id UUID FK NULL -- North Star knob #1 (legacy vs ensemble); NULL = latest stable
  is_active BOOL
  created_at TIMESTAMPTZ

tenant_user               -- the SEAT: maps an Auth0 identity to an account
  id UUID PK
  account_id UUID FK -> tenant_account
  auth0_sub VARCHAR UNIQUE          -- the JWT `sub`
  email VARCHAR
  role VARCHAR                      -- future: admin | viewer (unused at MVP)
  is_active BOOL
  created_at TIMESTAMPTZ

tenant_entitlement        -- temporal, append-only (NEVER UPDATE/DELETE)
  id UUID PK
  account_id UUID FK -> tenant_account
  entitlement_key VARCHAR          -- e.g. "read:section:weather"
  effective_from DATE
  active BOOL                       -- revoke = INSERT active=false tombstone
  UNIQUE(account_id, entitlement_key, effective_from)

v_tenant_entitlement_current        -- latest active row per (account_id, key); the ONLY thing the runtime reads
```

**Why `tenant_user`**: it makes "N seats per client" real (today it is honor-system — see [multi-account-seats.md](../runbooks/multi-account-seats.md)). Entitlements hang on the **account**, so all of a client's logins share one view. If you truly have 1 login per client at first, `tenant_user` *can* be deferred (key entitlements by `sub` directly) — but adding it now is ~1 table and avoids a rename later.

**North Star note**: these three map cleanly onto the future `tenant.account` / `tenant.user` / a subset of `tenant.subscription`. Nothing here diverges from the MCD.

### 4. Backend — enforcement (the real boundary)

1. **`app/core/tenancy.py`** (new) — `resolve_principal(sub) -> TenantPrincipal{account_id, tier, entitlements: frozenset, locale, algo_version}`. One query on `v_tenant_entitlement_current`, **cached in-memory, 10-min TTL** (mirror the JWKS 6h / audio 1h cache pattern), keyed by `sub`. Immutable object (coding-style: no mutation).
2. **Extend [`get_current_user`](../../backend/app/core/auth.py)** to attach the principal at the single identity-materialization point (`auth.py:131`).
3. **`require_entitlement(key)`** — FastAPI dependency wrapping `get_current_user`; raises the codebase's **first `403`** when `key not in principal.entitlements`. Apply per-route in [dashboard.py](../../backend/app/api/api_v1/endpoints/dashboard.py); router-level `dependencies=[…]` for `/data` in [api.py](../../backend/app/api/api_v1/api.py).
4. **Export filter** — validate requested `series` against the principal's `read:export:*` set *before* `EXPORT_SERIES`; `403` on a non-entitled series.
5. **Default-deny (decision #5)** — a valid token with **no `tenant_user` row → deny everything** (`403`). The only hard-boundary-consistent default. Forces the §9 backfill.

### 5. Audio hardening — the one real cost of "hard boundary"

[`/audio/stream`](../../backend/app/api/api_v1/endpoints/audio.py) is **unauthenticated by design** (the HTML `<audio>` element cannot send an `Authorization` header). Params are guessable → a client whose podcast is "hidden" can still fetch the bytes. Fix = **signed URLs**:

- `/dashboard/audio` returns a stream URL **only if** the client has `read:section:podcast`, embedding a short-lived HMAC token: `sign({account_id, date, version, exp})`.
- `/audio/stream` **validates the signature** instead of being open (still no Auth0 header → `<audio>` keeps working).
- HMAC secret in GCP Secret Manager; expiry ~1h (matches existing audio cache TTL).

> This is the single biggest hidden cost of the whole effort — budget for it explicitly.

### 6. Frontend — gating (cosmetic layer)

- **Surface entitlements**: extend `UserResponse` on `/auth/me` (or a new `/auth/entitlements`) to return the key set. Consumed once at login.
- **`EntitlementsProvider`** at App root — copy [`LanguageContext.tsx`](../../frontend/src/contexts/LanguageContext.tsx) verbatim; expose `useEntitlements()`.
- **Gate the six blocks** in [dashboard-page.tsx](../../frontend/src/pages/dashboard-page.tsx): `hasEntitlement('read:section:x') && <Block/>`.
- **Gate the ticker** (`LiveSignalStrip` + `MastheadPulse`) in [dashboard-layout.tsx](../../frontend/src/components/dashboard-layout.tsx) behind `read:chrome:ticker`, and **its cells individually** inside [live-signal-strip.tsx](../../frontend/src/components/live-signal-strip.tsx) — see note ¹ under the tier table.
- **403 handling** in [api/client.ts](../../frontend/src/api/client.ts) — a **new interceptor branch distinct from 401**: a 403 must **not** log the user out (today the only non-200 handled is `401 → logout`). Render a "not included in your plan" state or silently hide.
- **Export UI**: show only entitled series.

> ⚠️ Sections are page-level lazy-loaded, **not** per-section code-split — a hidden section's JS still ships. The **API `403` is the boundary**; the UI hide is only tidiness.

### 7. Auth0 — almost nothing

Because the source of truth is the DB, Auth0 stays a pure IdP. **No RBAC, no permissions, no Actions, no custom claims.** All that is relied on is a stable `sub`. (This is a real advantage of the DB choice over the Auth0-metadata approach — less vendor config, one source of truth.)

### 8. Provisioning — CLI (manual, append-only)

Poetry scripts, in the spirit of `set-farmgate-price`:

- `poetry run create-tenant --code acme --name "Acme" --tier export_premium` (expands the tier template into grant rows + sets `max_seats` from the tier)
- `poetry run link-seat --account acme --auth0-sub "auth0|abc" --email x@acme.com` (WARNS if active seats ≥ `max_seats`; never blocks)
- `poetry run grant-entitlement --account acme --key read:section:weather` (INSERT — old value preserved = provenance)
- `poetry run revoke-entitlement --account acme --key read:section:weather` (INSERT `active=false` tombstone — never UPDATE/DELETE)
- `poetry run set-tier --account acme --tier export_pro` (re-expand template; does NOT auto-revoke keys outside the new tier)

> Cache caveat: the API caches the principal per-instance for 10 min, and a CLI run against the DB cannot bust a running instance's cache. Grants/revokes take up to the TTL to bite (acceptable for manual ops). For an emergency immediate revoke, restart the service or add an optional `invalidate_principal(sub)` admin endpoint later.

### 9. Testing (fail-loud, default-deny)

- **Backend unit**: `require_entitlement` → 200 vs 403; `resolve_principal` incl. **no-row → empty set → deny**; export series filter; signed-URL sign/verify + expiry + tamper.
- **Backend integration**: seeded entitled account → 200; un-entitled account → 403 on the same route; unknown `sub` → 403 everywhere.
- **Frontend**: `EntitlementsProvider`, gated render, 403-not-logout interceptor.
- **The critical test**: authenticated-but-no-tenant-row → **denied**, not allowed.
- Target coverage ≥ 80% (testing rule).

### 10. Rollout — ✅ COMPLETED 2026-08-24

Kept as the historical record of how the flip was actually done. **For operations from here on, use
[docs/runbooks/entitlement-enforcement.md](../runbooks/entitlement-enforcement.md).**

1. ✅ **Shipped dark** — PR #91 merged the 3 tables + view with `ENTITLEMENTS_ENFORCED` unset (false). Zero user impact; the farmgate and WatchAI features were built on top of it in that window.
2. ✅ **Backfilled** — PR #112 added `poetry run seed-internal-tenants` (idempotent, `--dry-run` as the readiness gate). It created account `internal` and seated the **6** existing Auth0 logins on it (28 grants). Grandfathering onto `internal` rather than a commercial tier was deliberate: `export_pro` holds no CSV-export keys and would have silently revoked an export that was open to everyone.
3. ✅ **Signing secret** — `AUDIO_URL_SECRET` created in Secret Manager (`europe-west9`, user-managed replication) and injected by `deploy.yml` on the backend service only. `cc-cloud-run-api` already held `secretmanager.secretAccessor` at project level, so no IAM change was needed.
4. ✅ **Verified** — a second `--dry-run` through the bastion returned `0 would be seated, 6 already here, 0 on another account`.
5. ✅ **Flipped** — `ENTITLEMENTS_ENFORCED=true` via the GitHub var consumed by `deploy.yml`. Smoke-tested: `/audio/stream` without a signed token → `403` (the hard boundary is live), gated routes → `401` not `500`, `/health` → `200`. Browser-validated by Hedi.

**What the flip actually revealed**: before step 2, `tenant_account` / `tenant_user` /
`tenant_entitlement` were **0 rows in production**. Flipping without the backfill would have blanked
every single login. The `--dry-run` gate is the entire safety net — treat it as mandatory, not
advisory.

**Two flag locations.** The value lives both in the GitHub repo variable and on the Cloud Run
service. A rollback must change **both**, or the next deploy re-applies `true`. GCP:
`--update-env-vars`, never `--set-env-vars`. Locally, `PRINCIPAL_CACHE_TTL=0` makes tier changes
reflect on the next request (demos).

---

## Part 2 — Long-term: multi-commodity isolation

Your "one client wants cocoa **and** coffee, ideally in a single solution" is **native** to the North Star model — *if* a few invariants are protected today.

### 11. Invariants to protect NOW (so the future is free)

1. **Entitlement stays in the serving layer** — never in `app/engine/` or scrapers. The pipeline must never see a tenant. (The MVP already respects this.)
2. **Never put `tenant_id` / `commodity_scope` on a `pl_*` computation table.** Data stays contract-centric and shared. A scope column on a loader-joined table = the [timeseries-uniqueness](../../.claude/rules/timeseries-uniqueness.md) fan-out corruption that the `language` dimension already caused. **Isolation is a read-time filter, not a row column.**
3. **No new hardcoded "cocoa".** Keep resolving from the ref hierarchy ([contract_resolver.py](../../backend/app/utils/contract_resolver.py)).
4. **Entitlement ≠ subscription.** Two distinct concepts: *entitlement* = which sections/features (Part 1); *subscription* = which commodities' data (Part 2). Do **not** fold commodity into entitlement keys while there is one commodity.

### 12. The clean seam for the 2nd commodity

`exchange → commodity → contract` already exists ([reference.py](../../backend/app/models/reference.py)). When coffee is onboarded, add **one** table (the North Star `subscription`):

```
tenant_subscription
  account_id UUID FK -> tenant_account
  commodity_id UUID FK -> ref_commodity   -- cocoa AND/OR coffee
  effective_from DATE, active BOOL
  UNIQUE(account_id, commodity_id, effective_from)
```

- The serving layer filters `pl_*` reads by the client's subscribed commodities (`WHERE contract_id IN (contracts of subscribed commodities)`), commodity → all its contracts via `ref_contract.commodity_id`.
- **"Cocoa + coffee in one solution" = two subscription rows for one account.** One dashboard, one login, a **commodity switcher** (a `currentCommodity` context alongside the existing `DashboardDateContext`; every section hook takes `commodityId` the way it takes `targetDate` today). No separate deployments — the flexibility is the default, not a special case.

### 13. Migration map

| Phase | Trigger | Add |
|---|---|---|
| **Now** | first paying clients | `tenant_account` + `tenant_user` + `tenant_entitlement` + view; serving-layer 403; signed audio |
| **2nd commodity** | you sell coffee | `tenant_subscription(account, commodity)` + commodity-aware serving + commodity switcher UI |
| **Scale** | dozens of tenants / metered billing / compliance isolation | `credit_ledger`, per-account quotas, self-serve signup, Postgres **RLS** + `tenant_api_role` (North Star Phase 4) |

### 14. North Star alignment check

- `tenant_account.algorithm_version_id` = North Star per-tenant **knob #1** ✅
- `locale` (+ future `delivery_config`) = **knob #2** ✅
- Everything in the access layer, pipeline shared ✅ — nothing built now gets unwound later.

---

## Appendix A — Implementation checklist (detailed "what we need")

**DB / migrations**
- [ ] Alembic migration: `tenant_account`, `tenant_user`, `tenant_entitlement`, `v_tenant_entitlement_current` (idempotent; via `main`).
- [ ] Backfill script: one account for the current client, seat rows for every existing login, full grants.

**Backend**
- [ ] `app/models/` — 3 SQLAlchemy models (+ view mapping or raw select).
- [ ] `app/core/tenancy.py` — `TenantPrincipal`, `resolve_principal(sub)` + 10-min TTL cache.
- [ ] `app/core/auth.py` — attach principal in `get_current_user`.
- [ ] `require_entitlement(key)` dependency (+ first `403`).
- [ ] Apply gates: 6 sections, ticker, 5 features, `/data` export filter.
- [ ] Audio: HMAC signer/verifier; `/dashboard/audio` returns signed URL gated on `podcast`; `/audio/stream` validates signature.
- [ ] `ENTITLEMENTS_ENFORCED` env flag (default `false`).
- [ ] Tier template constant + expansion logic.
- [ ] CLI: `create-tenant`, `link-seat`, `grant-entitlement`, `revoke-entitlement`, `set-tier`.
- [ ] `UserResponse` / `/auth/entitlements` exposes the key set.

**Frontend**
- [ ] `EntitlementsProvider` + `useEntitlements()` (copy `LanguageContext`).
- [ ] Gate 6 section blocks in `dashboard-page.tsx`.
- [ ] Gate ticker in `dashboard-layout.tsx`.
- [ ] 403 interceptor branch in `api/client.ts` (distinct from 401).
- [ ] Export UI shows only entitled series.

**Testing**
- [ ] Unit + integration per §9; the no-tenant-row → deny test is mandatory.

**Ops / rollout**
- [ ] Dark deploy → seed → verify via bastion → flip flag.

---

## Appendix B — Open items

- ✅ Tier bundles aligned to the commercial matrix (§2) — done.
- `read:decision:physical_sale` / `…:hedge` gate no built endpoint yet — wire the gate when those features ship.
- Weather `:summary` variant: backend gate accepts it; the reduced weekly render is a **frontend** job (Slice 6). Backend payload trimming for summary tiers is deferred.
- Whether tier templates should become a DB table (`tenant_tier_template`) vs the current code constant — promote if ops need to edit bundles without a deploy.
- Emergency immediate-revoke path (restart vs an `invalidate_principal` admin endpoint) — defer until needed.
- WatchAI (②) + Formation (③) matrix blocks are separate products — not modeled as dashboard entitlements.

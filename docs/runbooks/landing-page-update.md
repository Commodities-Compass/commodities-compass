# Landing Page Update — Operational Runbook

> Maintenance procedures for the marketing landing (`com-compass.com`, codebase under `landing/`). Add a new section per recurring task. Each task is self-contained — Prereqs · Procedure · Verify · Notes.

## When to use this runbook

The landing is a static Astro 5 site served from GCS+Cloud CDN behind the existing LB. Most "updates" are content edits done directly in `landing/src/i18n/strings.ts`. This runbook covers the **non-obvious** recurring tasks where context is easy to lose between updates.

## Stack ownership map

Bookmark this before you spend an hour finding the right admin :

| Layer | Where | Who has access |
|---|---|---|
| Domain registrar | Squarespace Domains (inherited from Google Domains, migrated 2024-07) | Julien |
| DNS records | Same Squarespace Domains UI — `account.squarespace.com/domains/managed/com-compass.com/dns` | Julien |
| DNS zone hosting (nameservers `ns-cloud-*.googledomains.com`) | Google Cloud DNS (Squarespace-owned project, not ours) | N/A — read-only for us |
| Static hosting (Cloud Storage + CDN) | GCP project `cacaooo` (`cacaooo-landing` bucket + `cc-backend-landing`) | Hedi via `gcloud`/console |
| Load balancer + SSL cert | GCP project `cacaooo` (`cc-url-map`, `cc-ssl-landing-apex`) | Hedi via Terraform |
| Deploy pipeline | GitHub Actions (`deploy-landing.yml`, WIF auth to GCP) | Hedi |
| Content (Astro codebase) | `landing/` in this repo | Hedi (+ any contributor) |

For DNS changes, **do not go looking in GCP Cloud DNS** — the zone is not there. Ping Julien with the specific record changes needed (`docs/runbooks/landing-dns-change-template.md` — TBD).

## Task index

| # | Task | Cadence | Last applied |
|---|---|---|---|
| 1 | Refresh sparkline real close data (Section IV) | Monthly or after a roll | 2026-06-22 |

---

## Task 1 — Refresh sparkline real close data

The mini-chart under the audio card in Section IV ("Distribution") shows the last 30 trading-day closes of the active cocoa contract. The series is **hardcoded** in the Astro frontmatter (no runtime fetch) — refresh is manual.

### When to apply

- **Monthly** (cheap insurance against staleness — visitors should never see a chart that's 6 months old)
- **After a contract roll** — when `ref_contract.is_active` flips to a new code (e.g. CAU26 → CAZ26), the chart eyebrow + dataset must reflect the new front-month
- **After a sharp market move** — if cocoa is trending hard up or down and the static chart contradicts the news, refresh sooner so the landing doesn't look out of touch
- **Before a high-traffic event** — press release, investor demo, etc.

### Prereqs

- Local Postgres up: `pnpm db:up`
- Local DB recently synced from GCP (see [db-sync-from-gcp.md](db-sync-from-gcp.md))
- Working tree on `feat/landing-v2` (or `main` after launch)

If you don't want to sync locally, query GCP directly via the IAP bastion — same query, just replace the local connection string with the bastion-tunnelled one (see [db-sync-from-gcp.md](db-sync-from-gcp.md) Steps 1-2).

### Procedure

#### 1. Pull the 2 data points you need

Last 30 trading-day closes from the chained front-month series:

```bash
PGPASSWORD=password psql -h localhost -p 5433 -U postgres -d commodities_compass -c "
  SELECT date, close
  FROM v_contract_data_chained
  ORDER BY date DESC
  LIMIT 30;
"
```

Active contract code (for the chart eyebrow + caption):

```bash
PGPASSWORD=password psql -h localhost -p 5433 -U postgres -d commodities_compass -c "
  SELECT code FROM ref_contract WHERE is_active = true;
"
```

**No "today" / "current price" / "D/D change" needed** — the chart shows scale only (`Échelle : £2 850 – £3 500`), derived automatically from the array's min/max. This is intentional: prevents the static landing from claiming up-to-the-tick freshness it can't deliver. See the `chartScaleLabel` rationale in the frontmatter of `BriefAudio.astro`.

#### 2. Update the 30-value array

File: [landing/src/components/sections/BriefAudio.astro](../../landing/src/components/sections/BriefAudio.astro), look for the `prices = [...]` block in the frontmatter.

**Crucial** : the query returns DESC (newest first), but the array must be **ASC (oldest first)** so the sparkline reads left → right = past → present. Reverse before pasting.

Update the inline comment with the new refresh date and contract code:

```js
/* ... 30 last trading-day closes for the active contract
   (currently CAU26 / Sep 2026), sourced from v_contract_data_chained.
   Last refresh : 2026-06-22 — see ... */
const prices = [
  /* ASC chronological */
  3484, 3431, /* ... */, 3475,
];
```

The range (`Échelle £X – £Y`) is recomputed automatically from min/max of this array, rounded down/up to the nearest 50 — no manual update needed.

#### 3. Update the 3 strings (×2 locales) — only if the contract code rolled

File: [landing/src/i18n/strings.ts](../../landing/src/i18n/strings.ts), in both `fr.brief` and `en.brief` blocks. **If the active contract code is unchanged since the last refresh, skip this step entirely.**

| Key | FR | EN |
|---|---|---|
| `chartEyebrow` | `<CODE> · 30 séances` | `<CODE> · 30 sessions` |
| `chartScaleLabel` | `Échelle` | `Range` |
| `chartCaption` | `Closes officiels <CODE> · ICE Europe` | `Official <CODE> closes · ICE Europe` |

Replace `<CODE>` with the active contract code from query #2.

#### 4. Build + verify

```bash
cd landing
pnpm exec astro check    # 0/0/0 expected
pnpm exec astro build    # 5 pages
pnpm exec astro dev      # http://localhost:4321/#brief
```

Visual check on the chart : the line should match the new shape, eyebrow says the current contract code, scale band ("Échelle £X – £Y") reflects the new min/max.

#### 5. Commit + deploy

```bash
git add landing/src/components/sections/BriefAudio.astro landing/src/i18n/strings.ts
git commit -m "chore(landing): refresh chart closes (<CODE>, J=YYYY-MM-DD)"
git push   # GHA deploy-landing fires on push to main with landing/** changes
```

### Verify (post-deploy)

```bash
curl -sS https://com-compass.com/ | grep -oE '<CODE> · 30 séances'
curl -sS https://com-compass.com/ | grep -oE 'class="price"[^>]*>£[0-9 ]+ – £[0-9 ]+'
```

Both should return non-empty matches.

### Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Chart line is flat / weird | Reversed the array (DESC not ASC) | Reverse before pasting |
| Range label is wrong | Outliers in the series skewed min/max | Sanity-check the SQL output (no NULL closes, no zero rows) |
| Eyebrow shows old contract code | Forgot to update `chartEyebrow` strings | Re-edit FR + EN |
| Less than 30 points returned | Recent roll, new contract has < 30 days | Use `v_contract_data_chained`, not `pl_contract_data_daily` filtered by `is_active` — chained view stitches across rolls |

### Notes

- **Why `v_contract_data_chained` and not `pl_contract_data_daily`** : the active contract changes (rolls) every ~2 months. Querying current-active-only would return a partial series right after a roll. The chained view stitches the front-month (by OI) across rolls so the series is always continuous.
- **Why not auto-refresh** : a cron-driven refresh + redeploy was scoped out for V1 (see [P1 user story discussion](../../) for the architectural tradeoff between hardcoded / cron-refresh / live-fetch). Re-evaluate when the landing has > 1k UV/month or when manual cadence becomes the limiter.
- **The brief preview in the same section** (HEDGE example with CLOSE 2 975 → 2 964) is intentionally **decoupled** from the chart data — it's an illustrative editorial sample, not a real brief. The chart caption stays neutral ("Closes officiels … · ICE Europe") so the chart speaks to factual prices without claiming to align with the brief signal.

---

## Task N — [next recurring update goes here]

(Template for future tasks: when / prereqs / procedure / verify / failure modes / notes.)

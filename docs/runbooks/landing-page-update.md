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
| 2 | Republish a legal page after a revision from counsel | On each delivery | 2026-08-31 |

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

## Task 2 — Republish a legal page after a revision from counsel

The five published legal pages exist in both locales — ten Markdown files under
`landing/src/pages/` and `landing/src/pages/en/`. **Their body is a byte-for-byte
copy of counsel's delivery**, cut at the `⛔ FIN DU TEXTE À PUBLIER` /
`⛔ END OF PUBLISHED TEXT` line. That is deliberate: it makes the next revision a
diff instead of a re-transcription, and it means anyone can verify the published
page against the delivered document without reading Astro.

| Key | FR | EN |
|---|---|---|
| `legalNotice` | `/mentions-legales/` | `/en/legal-notice/` |
| `terms` | `/cgv/` | `/en/terms/` |
| `privacy` | `/confidentialite/` | `/en/privacy/` |
| `pricing` | `/tarifs/` | `/en/pricing/` |
| `methodology` | `/methodologie/` | `/en/methodology/` |

### Procedure

1. Drop the new delivery in `.local/Juridique Compass/` (gitignored — the folder
   also holds working notes that must never be published).
2. Replace everything **below** the frontmatter in the target page with the text
   **above** the `⛔` line. Keep the frontmatter as it is: `layout`, `title`,
   `description`, `eyebrow`, `pathname`, `legalKey`, and `locale` for EN.
3. `grep '«' landing/src/pages/*.md landing/src/pages/en/*.md` — **must return
   nothing**. Counsel leaves `«…»` markers wherever a value is ours to supply
   (author name, indicator distribution, ombudsman). A `«` reaching production
   is a placeholder published as if it were text.
4. Do the FR and the EN **in the same commit**. A revision applied to one locale
   only leaves two versions of a contract in the wild.
5. `pnpm --dir landing type-check && pnpm --dir landing build`, then read the
   page at 390 px: the wide tables must scroll inside themselves and the page
   body must not scroll sideways.

### What is ours, not counsel's

Three values in `/methodologie/` come from us and must be re-checked at each
revision:

- **§ 1 author** — name *and role* of a natural person. Required by art. 2 of
  delegated regulation (EU) 2016/958; a desk name does not satisfy it.
- **§ 3 meaning of OPEN / MONITOR / HEDGE**, and the horizon. The horizon is
  **J+1** — the served regime track's, not the `~4 sessions` inherited from the
  retired ensemble. If the served horizon ever changes, this page and the hero
  card (`statHorizonValue`) both change with it.
- **§ 5 distribution over twelve months.** Re-run against prod and republish the
  window with the figures — the percentages mean nothing without their period:

  ```sql
  WITH servie AS (
    SELECT DISTINCT ON (d.date) d.date, d.decision
      FROM pl_indicator_daily d
      JOIN pl_algorithm_version v ON v.id = d.algorithm_version_id
     WHERE d.language = 'fr' AND d.decision IS NOT NULL
       AND v.serving_rank IS NOT NULL
       AND d.date >= CURRENT_DATE - INTERVAL '12 months'
     ORDER BY d.date, v.serving_rank)
  SELECT decision, count(*),
         round(100.0*count(*)/sum(count(*)) OVER (), 1) AS pct
    FROM servie GROUP BY 1 ORDER BY 2 DESC;
  ```

  `DISTINCT ON … ORDER BY serving_rank` is what makes this the **published**
  recommendation for each date rather than one track's opinion — over twelve
  months the served row changes producer (regime took over on 2026-08-19), and
  MAR asks what was published, not what any one model thought.

### Notes

- **No performance figure is published anywhere.** Removed 2026-08-31: the
  landing's `+90 %` aggregated back-test with live publication, which
  mechanically overstates reliability. Do not reintroduce one without a real,
  documented, closed-period figure — and never under a `YTD` label, which is
  false the day after it is frozen.
- **Enabling analytics is a legal change.** § 8 of the privacy policy states in
  the affirmative that no non-exempt tracker is set. Read the header of
  `landing/src/components/Analytics.astro` before setting
  `PUBLIC_PLAUSIBLE_DOMAIN`.
- **The published phone number lives in five places** and they must move
  together: legal notice § 2 (FR + EN) and the Publisher block of the pricing
  page (FR + EN) — all four inside the Markdown, so a fresh delivery from
  counsel will drop it unless it is re-inserted — plus the footer, from
  `contact.phone` in `strings.ts`. It is **plain text everywhere, never a
  `tel:` link**: art. 1er-1 LCEN requires the number to be made available, not
  to be dialable, and the link is what harvesters target.
- **Email addresses are plain text too, and that takes a build step.** Markdown
  autolinks any bare address, so every mention of `contact@`, `privacy@` or
  `support@` in the legal corpus rendered as a harvestable `mailto:`.
  `rehypeUnlinkEmails` in `astro.config.mjs` unwraps them. It is scoped to
  Markdown on purpose: the commercial CTA in `Contact.astro` ("Contacter le
  Pôle commercial") keeps its mailto, because that one is a conversion action
  and not a legal mention. The site should therefore show **exactly one**
  `mailto:` per home page and **none** on a legal page — `grep -rc 'href="mailto:' dist`
  is the check.
- One value is still owed and the page carries an honest interim statement
  instead: the **ombudsman** (terms art. 28).

---

## Task N — [next recurring update goes here]

(Template for future tasks: when / prereqs / procedure / verify / failure modes / notes.)

# Landing Page Update — Operational Runbook

> Maintenance procedures for the marketing landing (`com-compass.com`, codebase under `landing/`). Add a new section per recurring task. Each task is self-contained — Prereqs · Procedure · Verify · Notes.

## When to use this runbook

The landing is a static Astro 5 site served from GCS+Cloud CDN behind the existing LB. Most "updates" are content edits done directly in `landing/src/i18n/strings.ts`. This runbook covers the **non-obvious** recurring tasks where context is easy to lose between updates.

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

#### 1. Pull the 3 data points you need

Last 30 trading-day closes from the chained front-month series:

```bash
PGPASSWORD=password psql -h localhost -p 5433 -U postgres -d commodities_compass -c "
  SELECT date, close
  FROM v_contract_data_chained
  ORDER BY date DESC
  LIMIT 30;
"
```

Active contract code (for the chart eyebrow):

```bash
PGPASSWORD=password psql -h localhost -p 5433 -U postgres -d commodities_compass -c "
  SELECT code FROM ref_contract WHERE is_active = true;
"
```

Day-over-day change (for the chart meta line):

```bash
PGPASSWORD=password psql -h localhost -p 5433 -U postgres -d commodities_compass -c "
  WITH s AS (
    SELECT date, close, LAG(close) OVER (ORDER BY date) AS prev
    FROM v_contract_data_chained
    ORDER BY date DESC LIMIT 2
  )
  SELECT date, close, prev,
         ROUND(((close - prev) / prev * 100)::numeric, 2) AS pct_change
  FROM s WHERE prev IS NOT NULL;
"
```

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

#### 3. Update the 4 strings (×2 locales)

File: [landing/src/i18n/strings.ts](../../landing/src/i18n/strings.ts), in both `fr.brief` and `en.brief` blocks :

| Key | FR | EN |
|---|---|---|
| `chartEyebrow` | `<CODE> · 30 derniers jours` | `<CODE> · Last 30 days` |
| `chartCurrentPrice` | `£3 475` (espace insécable optionnel) | `£3,475` (virgule milliers) |
| `chartCurrentChange` | `+5,49 %` (espace avant %) | `+5.49%` (sans espace) |
| `chartCaption` | `Closes officiels <CODE> · ICE Europe` | `Official <CODE> closes · ICE Europe` |

Replace `<CODE>` with the active contract code from query #1.

#### 4. Update dot color + change sign-class if direction flipped

In [BriefAudio.astro](../../landing/src/components/sections/BriefAudio.astro), if today's D/D moved opposite direction since last refresh :

- `fill="var(--color-signal-open)"` (vert) vs `fill="var(--color-signal-hedge)"` (rouge) on the SVG `<circle>` for the dot
- `class="change up"` vs `class="change down"` on the change span in the chart-meta block

Up day → `signal-open` + `up`. Down day → `signal-hedge` + `down`. The CSS already maps both classes to the right colors.

#### 5. Build + verify

```bash
cd landing
pnpm exec astro check    # 0/0/0 expected
pnpm exec astro build    # 5 pages
pnpm exec astro dev      # http://localhost:4321/#brief
```

Visual check on the chart : the line should match the new shape, dot color matches D/D direction, eyebrow says the current contract code, meta line shows new price + percent.

#### 6. Commit + deploy

```bash
git add landing/src/components/sections/BriefAudio.astro landing/src/i18n/strings.ts
git commit -m "chore(landing): refresh chart closes (<CODE>, J=YYYY-MM-DD, latest £<price> <±X.XX%>)"
git push   # GHA deploy-landing fires on push to main with landing/** changes
```

### Verify (post-deploy)

```bash
curl -sS https://com-compass.com/ | grep -oE '<CODE> · 30 derniers jours'
curl -sS https://com-compass.com/ | grep -oE 'AUJOURD.{0,3}HUI[^<]{0,40}£[0-9 ]+[^<]{0,40}%'
```

Both should return non-empty matches.

### Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Chart line is flat / weird | Reversed the array (DESC not ASC) | Reverse before pasting |
| Dot is on the wrong end | Same as above | Same |
| Dot color contradicts the change | Forgot to flip both `fill=` and `class=` | Update both in lockstep |
| Eyebrow shows old contract code | Forgot to update `chartEyebrow` strings | Re-edit FR + EN |
| Less than 30 points returned | Recent roll, new contract has < 30 days | Use `v_contract_data_chained`, not `pl_contract_data_daily` filtered by `is_active` — chained view stitches across rolls |

### Notes

- **Why `v_contract_data_chained` and not `pl_contract_data_daily`** : the active contract changes (rolls) every ~2 months. Querying current-active-only would return a partial series right after a roll. The chained view stitches the front-month (by OI) across rolls so the series is always continuous.
- **Why not auto-refresh** : a cron-driven refresh + redeploy was scoped out for V1 (see [P1 user story discussion](../../) for the architectural tradeoff between hardcoded / cron-refresh / live-fetch). Re-evaluate when the landing has > 1k UV/month or when manual cadence becomes the limiter.
- **The brief preview in the same section** (HEDGE example with CLOSE 2 975 → 2 964) is intentionally **decoupled** from the chart data — it's an illustrative editorial sample, not a real brief. The chart caption stays neutral ("Closes officiels … · ICE Europe") so the chart speaks to factual prices without claiming to align with the brief signal.

---

## Task N — [next recurring update goes here]

(Template for future tasks: when / prereqs / procedure / verify / failure modes / notes.)

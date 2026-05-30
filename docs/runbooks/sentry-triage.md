# Sentry Triage Runbook — Terminal-First Error Investigation

> Companion to [P1-sentry-cli-triage.md](../user-stories/P1-sentry-cli-triage.md).
> When prod breaks, this is the playbook. Read top-to-bottom on first use; cherry-pick later.

## TL;DR for Claude

You are triaging a production error reported by Hedi or by a Sentry alert. Workflow:

1. Resolve org slug (`commodities-compass`) + project (`commodities-compass`).
2. List unresolved issues from the last N hours with `curl` against the Sentry HTTP API. Filter by `service:<frontend|fastapi|<job-slug>>` if scope is known.
3. For each candidate issue, fetch the latest event → extract top stack frame → `filename:lineno`.
4. Open the local file at that line, read context (±20 lines), propose a fix.
5. Never call any endpoint that writes (no resolve, no assign, no comment, no merge). Read-only triage only.
6. Time budget: **first fix proposal within 30 s** of receiving the prompt.

---

## Setup (one-time, Hedi side)

### Local user token (read-only)

1. Sentry → Settings (user, top-right) → Account → API → Auth Tokens → Create New Token.
   Scopes: `event:read`, `project:read`, `org:read`. **No `*:write`.**
2. Add to `~/.zshrc`:
   ```bash
   export SENTRY_AUTH_TOKEN="sntryu_..."  # starts with sntryu_ for user tokens
   ```
3. Verify: `echo "${SENTRY_AUTH_TOKEN:0:8}..."` should print `sntryu_...`.

### Optional: install sentry-cli

```bash
brew install getsentry/tools/sentry-cli
sentry-cli info  # should resolve org + project from $SENTRY_AUTH_TOKEN
```

Note: `sentry-cli` is convenient but not required. The HTTP API via `curl` + `jq` is faster for triage queries and easier to script inside Claude.

---

## CLI vs HTTP API — when to pick which

| Need | Tool | Why |
|---|---|---|
| List recent issues / events | `curl` + `jq` | Direct, scriptable, no extra dep |
| Inspect one event in detail | `curl` + `jq` | Returns full JSON |
| Sanity check `auth_token`/org/project | `sentry-cli info` | One-liner |
| Source map debugging / release confusion | `sentry-cli releases list/info` | Built-in formatting |
| Anything that mutates Sentry state | **None** | Not authorized for this token (and intentionally so) |

---

## Tag conventions

Every event in this org carries the following tags. Use them to scope queries.

| Tag | Set by | Values |
|---|---|---|
| `service` | `init_sentry(slug)` in backend, `Sentry.setTag('service', 'frontend')` in PR-B | `fastapi`, `frontend`, `barchart-scraper`, `ice-stocks-scraper`, `cftc-scraper`, `press-review-agent`, `meteo-agent`, `compute-indicators`, `daily-analysis`, `compass-brief`, `enso-scraper`, `fx-scraper`, `ice-cot-eu-scraper`, `barchart-stocks-eu-scraper`, `ensemble-bootstrap-artifacts`, `ensemble-compute`, `eca-grindings-scraper`, `nca-grindings-scraper`, `publication-calendar-watchdog`, `ensemble-explainer`, `compass-brief-ensemble` |
| `environment` | `init_sentry` reads `ENVIRONMENT` env var (default `production`) | `production`, `development` |
| `release` | `init_sentry` reads `GIT_COMMIT_SHA` env var (CI injects `${{ github.sha }}`) | Full commit SHA (40 hex chars) |
| `user.id`, `user.email` | `sentry_sdk.set_user` (backend) / `Sentry.setUser` (frontend, after Auth0 login) | Auth0 `sub` / email |

---

## The Claude triage loop (pseudocode)

```
INPUT: error context (URL, user description, Sentry issue link, or "what blew up today?")

1. PARSE
   - Extract issue ID from Sentry URL if present, else broad list query
   - Identify scope: backend / frontend / specific job slug

2. FETCH (always read-only)
   - GET /api/0/organizations/commodities-compass/issues/?statsPeriod=24h&query=is:unresolved [+service:<X>]
   - Pick top 1-3 candidates by `count` × recency

3. DRILL
   - For each candidate: GET /api/0/issues/{id}/events/latest/
   - Extract: `metadata.title`, `tags[release]`, `tags[service]`, top stack frame
     (filename, lineno, function, in_app=true)

4. LOCATE + READ
   - Map Sentry filename to repo path (strip leading `/app/` or `webpack:///` prefix)
   - Open file at lineno ± 20 lines (Read tool)

5. PROPOSE FIX
   - Hypothesis (one sentence)
   - Concrete code diff (Edit tool — only if Hedi confirms)
   - NEVER auto-resolve the issue in Sentry. Hedi resolves after merge + observation.
```

---

## Ready-to-run commands

### `curl` + `jq` — recent unresolved errors (last 24h)

Backend FastAPI:
```bash
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/organizations/commodities-compass/issues/?statsPeriod=24h&query=is:unresolved+service:fastapi&limit=10" \
  | jq -r '.[] | "[\(.count)] \(.id) — \(.title) — last seen \(.lastSeen)"'
```

Frontend:
```bash
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/organizations/commodities-compass/issues/?statsPeriod=24h&query=is:unresolved+service:frontend&limit=10" \
  | jq -r '.[] | "[\(.count)] \(.id) — \(.title) — last seen \(.lastSeen)"'
```

Specific job (e.g., `compute-indicators`):
```bash
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/organizations/commodities-compass/issues/?statsPeriod=24h&query=is:unresolved+service:compute-indicators&limit=10" \
  | jq -r '.[] | "[\(.count)] \(.id) — \(.title)"'
```

### Top 3 across all services

```bash
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/organizations/commodities-compass/issues/?statsPeriod=24h&query=is:unresolved&sort=freq&limit=3" \
  | jq -r '.[] | "[\(.count)x] \(.title) (service:\(.tags // [] | map(select(.key=="service")) | .[0].value // "n/a")) — \(.permalink)"'
```

### Drill into one issue's latest event

```bash
ISSUE_ID=<paste from list>
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/issues/$ISSUE_ID/events/latest/" \
  | jq '{
    title: .metadata.title,
    release: (.tags // [] | map(select(.key=="release")) | .[0].value),
    service: (.tags // [] | map(select(.key=="service")) | .[0].value),
    environment: (.tags // [] | map(select(.key=="environment")) | .[0].value),
    user: .user,
    top_frame: (.entries // [] | map(select(.type=="exception")) | .[0].data.values[0].stacktrace.frames | last | {filename, lineno, function, in_app})
  }'
```

### Verify a release exists (after a CI deploy)

```bash
SHA=$(git rev-parse origin/main)
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/organizations/commodities-compass/releases/$SHA/" \
  | jq '{version, dateCreated, dateReleased, commitCount, deployCount, lastEvent}'
```

If `commitCount` is non-zero and `dateReleased` is set, the `getsentry/action-release` CI step worked.

### Get release range (what landed in this prod deploy?)

```bash
SHA=$(git rev-parse origin/main)
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/organizations/commodities-compass/releases/$SHA/commits/" \
  | jq -r '.[] | "\(.id[:8]) — \(.message | split("\n")[0])"'
```

---

## Mapping Sentry filenames to local paths

Sentry stack frames carry paths from the build system, not your local repo. Translation rules:

| Sentry prefix | Local path |
|---|---|
| `/app/backend/...` | strip `/app/` → `backend/...` (Cloud Run container puts backend at `/app/`) |
| `/app/app/...` | strip `/app/` → `backend/app/...` (some traces collapse this) |
| `webpack:///src/...` (frontend, pre-Vite) | strip `webpack:///` → `frontend/src/...` |
| `app:///assets/index-<hash>.js` (frontend, Vite + uploaded maps) | The map resolves to `frontend/src/...` automatically in the Sentry UI. The local frame already includes the resolved path. |
| `vendor.<hash>.js`, `auth.<hash>.js`, etc. | Third-party — fix is in our wrapper code, not the vendor file. |

---

## Anti-patterns (do not do)

- ❌ Auto-resolve issues from CLI/curl. Resolution belongs to Hedi after merge + observation.
- ❌ `echo $SENTRY_AUTH_TOKEN` in logs, shared shells, or pasted commands. Always reference `$SENTRY_AUTH_TOKEN` indirectly.
- ❌ Read `event.request.body` or expand PII fields. Backend + frontend both set `send_default_pii=False`; respect that.
- ❌ Use `sentry-cli releases new` / `finalize` / `set-commits` from local terminal. That's the CI's job; if a release is missing it means the CI failed and that's the bug to fix.
- ❌ Mix the CI org token (`sntrys_...`, write scope) and the local user token (`sntryu_...`, read scope). Never put the org token in `~/.zshrc`; never put the user token in GitHub Secrets.
- ❌ Issue triage by reading the Sentry UI when terminal works. UI is for visual sanity checks; CLI is for grep + jq + edit loops.

---

## Common triage shortcuts

### "What blew up today?" (Hedi's most common prompt)

```bash
# Top 3 across all services, last 24h, by frequency
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/organizations/commodities-compass/issues/?statsPeriod=24h&query=is:unresolved&sort=freq&limit=3" \
  | jq -r '.[] | "[\(.count)x] \(.title) — \(.permalink)"'
```

Then drill into top issue, fetch latest event, propose fix.

### "Did the latest deploy break anything?"

```bash
SHA=$(git rev-parse origin/main)
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/organizations/commodities-compass/issues/?statsPeriod=24h&query=release:$SHA+is:unresolved+firstSeen:-24h" \
  | jq -r '.[] | "[\(.count)x] \(.title) — first seen \(.firstSeen) — \(.permalink)"'
```

If empty → all good. If non-empty → those errors started after this release.

### "Cron job X failed last night"

```bash
# Example: compute-indicators
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/organizations/commodities-compass/issues/?statsPeriod=24h&query=is:unresolved+service:compute-indicators" \
  | jq -r '.[] | "[\(.count)x] \(.title) — last seen \(.lastSeen) — \(.permalink)"'
```

Cross-check the cron monitor in Sentry UI: Crons → `cc-<slug>` card should be red if the last execution failed.

---

## Sentry quotas — when triage costs become a problem

Free tier: 5K errors/month, separate cron pings. With backend `traces_sample_rate=0.2` + frontend `tracesSampleRate=0.1`, projected usage is ~1-2K/month under normal load. Spike scenarios:

- Frontend error loop (e.g., infinite re-render with a thrown error inside) — can burn 5K in hours.
- Backend retry loop without backoff — same.

If quota is exceeded:
1. Sentry drops new events silently — triage becomes blind.
2. Fix: in `backend/app/core/sentry.py`, lower `traces_sample_rate` to `0.05` and redeploy. Same in `frontend/src/sentry.ts` for `tracesSampleRate`.
3. Don't add `beforeSend` filters as a band-aid — fix the loop instead.

---

## When the runbook itself is wrong

If a `curl` here returns 401 / 403:
- Token might be revoked. Recreate per **Setup**.
- Token might be the org token (write scope) instead of user token. Check prefix: `sntryu_` vs `sntrys_`.

If a query returns empty when you expect events:
- Wrong service tag spelling (case-sensitive).
- Wrong `statsPeriod` (Sentry accepts `1h`, `24h`, `7d`, `14d`, `30d`, `90d`).
- Frontend events: the user might not have visited the app recently — frontend Sentry is event-driven, not heartbeat.

If you can't tell whether an issue is in our code or a library: check `tags[].framework` and the `in_app` flag on stack frames. `in_app:false` = vendor code, not ours.

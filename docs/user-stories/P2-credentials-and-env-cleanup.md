# User Story: Credentials & Environment Variables Cleanup

## Epic

As the **CTO/sole operator**, I need to consolidate duplicated credentials, reduce the number of service accounts, and clean up environment variables, so that secret rotation is simple and there's no confusion about which credential does what.

---

## Context

**Current state — credentials sprawl:**

### Google credentials duplication

Three separate credential env vars that may point to the same (or different) service account keys:

| Env var | Used by | SA |
|---------|---------|-----|
| `GOOGLE_SHEETS_CREDENTIALS_JSON` | ETL import, scrapers (Sheets write) | `commodities-compass-sheets@` |
| `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON` | Scraper dual-write to Sheets | `commodities-compass-data@` (?) |
| `GOOGLE_DRIVE_CREDENTIALS_JSON` | Audio streaming, compass-brief upload | Falls back to `GOOGLE_SHEETS_CREDENTIALS_JSON` if not set |

**Problem:** It's unclear which SA each credential belongs to, whether they're the same key, and which permissions each actually needs. During Phase 4 deploy, `GOOGLE_DRIVE_CREDENTIALS_JSON` was an empty Secret Manager shell with 0 versions — populated by copying Sheets credentials. This suggests they might be the same SA.

### Service accounts audit needed

Multiple SAs exist in the GCP project. Some were created during experimentation, some for specific purposes:

| SA | Purpose | Still needed? |
|----|---------|---------------|
| `commodities-compass-sheets@` | Legacy Sheets access | Audit |
| `commodities-compass-data@` | Scraper data access | Audit |
| `cc-cloud-run-api@` | Cloud Run API service | Yes |
| `cc-cloud-run-jobs@` | Cloud Run Jobs service | Yes |
| `cc-github-actions@` | CI/CD via Workload Identity | Yes |

Need to verify: which SAs are actually used, which keys exist, and whether we can consolidate.

### Env var duplication across systems

Same values stored in multiple places:

| Value | GitHub Vars | Secret Manager | Cloud Run env | Railway |
|-------|-------------|----------------|---------------|---------|
| `SPREADSHEET_ID` | ✓ | ✗ | ✓ | ✓ |
| `GOOGLE_DRIVE_AUDIO_FOLDER_ID` | ✓ | ✗ | ✓ | ✓ |
| `GOOGLE_DRIVE_BRIEFS_FOLDER_ID` | ✓ | ✗ | ✓ | ✓ |
| Auth0 values | ✓ (vars) | ✓ (Secret Manager) | ✓ (backend secrets) | ✓ |
| `ACTIVE_CONTRACT` | ✓ | ✗ | ✓ (barchart only) | ✓ |

Auth0 values are in both GitHub Vars (frontend build) AND Secret Manager (backend runtime) — this is correct (different consumers), but should be documented to avoid confusion.

---

## User Stories

### US-1: Consolidate Google credentials to one SA

**As** the pipeline operator,
**I want** a single service account for all Google API access (Sheets, Drive, Audio),
**So that** there's one key to rotate and one set of permissions to manage.

**Acceptance criteria:**
- Audit current SAs: list all keys, check last usage date, identify permissions
- Pick one SA (likely `cc-cloud-run-jobs@` since it already has the right IAM bindings)
- Grant it: Sheets editor on the spreadsheet, Drive access on audio + briefs folders
- Consolidate to one Secret Manager secret: `GOOGLE_CREDENTIALS_JSON`
- Remove `GOOGLE_SHEETS_CREDENTIALS_JSON`, `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON`, `GOOGLE_DRIVE_CREDENTIALS_JSON`
- Update all scraper/agent code to read from `GOOGLE_CREDENTIALS_JSON`
- Delete unused SA keys (after migration verified)

### US-2: Audit and delete unused service accounts

**As** the CTO,
**I want** to audit all GCP service accounts and delete the ones that are no longer needed,
**So that** there's no dangling access and the IAM surface is minimal.

**Acceptance criteria:**
- `gcloud iam service-accounts list` — document each SA's purpose
- `gcloud iam service-accounts keys list --iam-account=...` — check key age and count
- Delete SAs with no recent activity and no active consumers
- Delete old keys on retained SAs (keep only the latest)
- Document retained SAs in a runbook

### US-3: Clean up Secret Manager

**As** the pipeline operator,
**I want** Secret Manager to have exactly the secrets that are needed, with clear names,
**So that** `gcloud secrets list` is self-documenting.

**Acceptance criteria:**
- Remove duplicate/unused secrets
- Rename if needed for clarity (e.g., `GOOGLE_CREDENTIALS_JSON` instead of 3 separate ones)
- Every secret has at least 1 active version
- Document which secrets are consumed by which Cloud Run service/job
- After consolidation, expected secrets:

| Secret | Consumer |
|--------|----------|
| `DATABASE_URL` | Backend API, all jobs |
| `DATABASE_SYNC_URL` | Backend API, all jobs |
| `GOOGLE_CREDENTIALS_JSON` | All jobs (Sheets + Drive) |
| `OPENAI_API_KEY` | daily-analysis, press-review |
| `ANTHROPIC_API_KEY` | press-review |
| `GEMINI_API_KEY` | press-review |
| `SENTRY_DSN` | Backend API, all jobs |
| `AUTH0_DOMAIN` | Backend API |
| `AUTH0_CLIENT_ID` | Backend API |
| `AUTH0_API_AUDIENCE` | Backend API |
| `AUTH0_ISSUER` | Backend API |

### US-4: Remove Railway env vars after kill

**As** the pipeline operator,
**I want** to remove all Railway-specific environment variables after Railway is killed,
**So that** there's no confusion about which system is the source of truth.

**Acceptance criteria:**
- After Phase 5 (Railway killed): remove `SPREADSHEET_ID` from Railway
- Remove all Railway env vars
- Remove `*.up.railway.app` from CSP in `index.html`
- Remove `*.up.railway.app` from Auth0 allowed callbacks/origins
- Remove Railway-specific CORS origins from `BACKEND_CORS_ORIGINS`

---

## Technical Design

### Audit commands

```bash
# List all SAs
gcloud iam service-accounts list --project=cacaooo

# List keys per SA
gcloud iam service-accounts keys list --iam-account=SA_EMAIL --project=cacaooo

# Check key last usage (requires IAM Activity Analyzer)
gcloud policy-intelligence query-activity --activity-type=serviceAccountKeyLastAuthentication --project=cacaooo

# List secrets and versions
gcloud secrets list --project=cacaooo
for s in $(gcloud secrets list --format="value(name)" --project=cacaooo); do
  echo "$s: $(gcloud secrets versions list $s --format='value(name)' --limit=1 --project=cacaooo) versions"
done
```

### Code changes for credential consolidation

| File | Change |
|------|--------|
| `app/core/config.py` | Replace 3 Google credential vars with `GOOGLE_CREDENTIALS_JSON` |
| `scripts/barchart_scraper/config.py` | Read `GOOGLE_CREDENTIALS_JSON` |
| `scripts/ice_stocks_scraper/config.py` | Same |
| `scripts/cftc_scraper/config.py` | Same |
| `scripts/press_review_agent/config.py` | Same |
| `scripts/meteo_agent/config.py` | Same |
| `scripts/compass_brief/config.py` | Same |
| `app/services/audio_service.py` | Same |
| `.github/workflows/deploy.yml` | Update `--set-secrets` to use new secret name |

---

## Out of Scope

- Workload Identity for Cloud Run (using SA keys attached to service, not JSON keys) — good idea for Phase 6+, eliminates key rotation entirely
- Vault / external secret manager — overkill at current scale

## Dependencies

- Phase 5 (Kill Railway) should complete first — no point cleaning Railway vars while it's still running
- SA audit requires `iam.serviceAccounts.list` permission (CTO has Owner role)

## Migration Plan

1. Audit SAs and keys (document current state)
2. Create consolidated `GOOGLE_CREDENTIALS_JSON` secret in Secret Manager
3. Update all code to read from new var (with fallback to old vars during transition)
4. Deploy and validate all jobs work with new credential
5. Delete old secrets from Secret Manager
6. Delete unused SA keys
7. Delete unused SAs

# User Story: Security Hardening Post-Launch

**Date:** 2026-04-01
**Priority:** P1 (first sprint after custom domain go-live)
**Source:** secops audit 2026-04-01 — findings not blocking go-live but required before stable

---

## Context

Security review identified 5 HIGH, 6 MEDIUM, and 4 LOW findings. The two go-live blockers (C-1: Cloud SQL `0.0.0.0/0`, H-1: Swagger docs in prod) are fixed. This user story tracks the remaining items.

---

## HIGH

### H-2: Cloud Scheduler OAuth scope too broad
**File:** `infra/terraform/scheduler.tf:69`
**Current:** `scope = "https://www.googleapis.com/auth/cloud-platform"`
**Fix:** Change to `https://www.googleapis.com/auth/cloud-run`
**Effort:** 5 min + terraform apply
- [ ] Update scope in scheduler.tf
- [ ] `terraform plan` — verify no unintended changes
- [ ] `terraform apply`

### H-3: Jobs SA has `roles/run.developer` (can redeploy services)
**File:** `infra/terraform/iam.tf:78-82`
**Current:** `roles/run.developer`
**Fix:** Replace with `roles/run.invoker`
**Effort:** 5 min + terraform apply
- [ ] Update role in iam.tf
- [ ] Verify Cloud Scheduler can still trigger jobs after apply
- [ ] Verify deploy.yml uses `cc-github-actions` SA (not `cc-cloud-run-jobs`) for deploys

### H-4: CI/CD SA has project-wide `secretmanager.secretAccessor`
**File:** `infra/terraform/iam.tf:104-108`
**Fix:** Replace project-level binding with per-secret `google_secret_manager_secret_iam_member` bindings for only the 13 secrets deploy.yml references.
**Effort:** 1h — need to create 13 IAM bindings + remove project-level role
- [ ] List exact secrets referenced in deploy.yml
- [ ] Create per-secret IAM bindings in Terraform
- [ ] Remove project-level `secretAccessor` role
- [ ] Verify deploy workflow still passes

### H-5: Rename `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON` to `GOOGLE_DRIVE_CREDENTIALS_JSON`
**Files:** `deploy.yml:171`, `compass_brief/config.py:13`, `infra/terraform/variables.tf:97`
**Fix:** Consolidate to single `GOOGLE_DRIVE_CREDENTIALS_JSON` secret for all Drive access (audio + briefs).
**Effort:** 30 min
- [ ] Update `compass_brief/config.py` env var name
- [ ] Update `deploy.yml` jobs secrets line
- [ ] Update GCP Secret Manager (create new secret or rename)
- [ ] Remove `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON` from Secret Manager
- [ ] Remove both Sheets secrets from `variables.tf` secret_ids list
- [ ] Verify compass-brief `--dry-run` works with new env var

---

## MEDIUM

### M-1: Add Content-Security-Policy header
**File:** `backend/app/main.py:67-76`
**Fix:** Add CSP to the security headers middleware.
- API (returns JSON only): `Content-Security-Policy: default-src 'none'`
- Frontend: configure in nginx/serve config once custom domain is known
- [ ] Add CSP header to backend middleware
- [ ] Add CSP meta tag or header to frontend serving config (post-domain setup)

### M-2: Remove manual localStorage token double-write
**Files:** `frontend/src/api/client.ts:28,37`, `frontend/src/hooks/useAuth.ts:15`
**Fix:** Remove `localStorage.setItem('auth0_token', token)` and the `cachedToken` fallback. Let Auth0 SDK handle token storage exclusively.
- [ ] Remove manual token caching in Axios interceptor
- [ ] Remove `cachedToken` fallback in useAuth
- [ ] Test login/logout flow, verify 401 handling still works

### M-3: Fix Sentry release tag (dead Railway env var)
**File:** `backend/app/core/sentry.py:27`
**Current:** `release=os.getenv("RAILWAY_GIT_COMMIT_SHA")`
**Fix:** Replace with `os.getenv("GIT_COMMIT_SHA")` and pass `--set-env-vars=GIT_COMMIT_SHA=${{ github.sha }}` in deploy.yml for both API and jobs.
- [ ] Update sentry.py
- [ ] Add `GIT_COMMIT_SHA` to deploy.yml env vars (API + jobs)
- [ ] Verify Sentry receives release tag after deploy

### M-4: Enable Point-in-Time Recovery on Cloud SQL
**File:** `infra/terraform/cloudsql.tf:39`
**Fix:** Set `point_in_time_recovery_enabled = true`
**Cost:** Negligible on db-f1-micro.
- [ ] Update cloudsql.tf
- [ ] terraform apply
- [ ] Verify PITR enabled in GCP console

### M-5: Fix rate limiting key function for Cloud Run proxy
**File:** `backend/app/core/rate_limit.py`
**Fix:** Use `X-Forwarded-For` header (first IP) instead of `request.client.host` which is always the load balancer IP behind Cloud Run.
- [ ] Create custom key function reading `X-Forwarded-For`
- [ ] Update limiter initialization
- [ ] Test rate limiting works per-client (not globally)

### M-6: Rate-limit `/health` and `/` endpoints
**File:** `backend/app/main.py:88-100`
**Fix:** Add `@limiter.limit("30/minute")` to both endpoints, or remove DB query from `/health`.
- [ ] Add rate limit decorator to both endpoints
- [ ] Consider static health response (no DB hit) to prevent connection pool exhaustion

---

## LOW

### L-1: OpenAPI schema uses deprecated implicit flow
**File:** `backend/app/main.py:151-163`
**Fix:** Change to `authorizationCode` with PKCE, or remove the custom OpenAPI override entirely (docs are disabled in prod anyway — H-1 already fixed).
- [ ] Simplify or remove `custom_openapi()` function

### L-2: Delete orphaned Sheets secrets from Secret Manager + Terraform
**Files:** `infra/terraform/variables.tf:96-97`
**Fix:** Remove `GOOGLE_SHEETS_CREDENTIALS_JSON` and `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON` from `secret_ids` list. Delete from GCP Secret Manager.
- [ ] Remove from variables.tf
- [ ] Delete secrets from GCP console or `gcloud secrets delete`
- [ ] terraform apply

### L-3: Delete dead Railway config files
**Files:** `backend/railway.toml`, `backend/nixpacks.toml`
- [ ] `git rm` both files

### L-4: Remove committed SQLite test file
**File:** `backend/test_seed.db`
- [ ] Add `*.db` to `.gitignore`
- [ ] `git rm --cached backend/test_seed.db`

---

## Execution order

| Sprint | Items | Effort | Priority |
|--------|-------|--------|----------|
| Day 1 | H-2, H-3, M-4 (Terraform batch — plan + apply once) | 1h | Highest |
| Day 1 | M-3, M-6 (quick code fixes) | 30 min | High |
| Day 2 | H-5, L-2 (credential consolidation) | 1h | High |
| Day 2 | M-1, M-5 (security headers + rate limiting) | 1h | Medium |
| Day 3 | M-2 (frontend auth token cleanup) | 1h | Medium |
| Day 3 | H-4 (per-secret IAM bindings) | 1h | Medium |
| Anytime | L-1, L-3, L-4 (cleanup) | 15 min | Low |

**Total: ~6h across 3 days.**

---

## Acceptance criteria

- [ ] `terraform plan` shows no `0.0.0.0/0` in any resource
- [ ] Cloud Scheduler OAuth scope is `cloud-run` (not `cloud-platform`)
- [ ] Jobs SA role is `run.invoker` (not `run.developer`)
- [ ] CI/CD SA has per-secret bindings (not project-wide)
- [ ] Zero references to `GOOGLE_SHEETS_*` in deploy.yml or config
- [ ] CSP header present on all API responses
- [ ] Sentry release tag shows commit SHA
- [ ] PITR enabled on Cloud SQL
- [ ] Rate limiting works per-client IP (not globally)
- [ ] No `railway.toml`, `nixpacks.toml`, or `test_seed.db` in repo

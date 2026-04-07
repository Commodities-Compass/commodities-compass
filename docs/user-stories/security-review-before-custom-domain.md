# User Story: Security Review Before Custom Domain Go-Live

## Epic

As the **CTO**, I need a comprehensive security review before pointing `com-compass.com` (or final custom domain) to the GCP infrastructure, so that the production system is hardened before public exposure.

---

## Context

**Current state (updated 2026-04-01):** The app runs on `*.run.app` URLs — obscure, low-traffic, not indexed. Phase 5 complete: Railway killed, Google Sheets removed, all data flows through GCP. Security hardening (Phase 4.3) added rate limiting, CORS restriction, and security headers.

**Dependency audit (2026-04-01):**
- Backend (Python): `pip-audit` — **0 known vulnerabilities**
- Frontend (Node): `pnpm audit` — **16 vulnerabilities** (11 high, 5 moderate), all in dev-only transitive deps (rollup via vite, minimatch via eslint, picomatch via tailwindcss). None ship to production bundle. All resolved by major version upgrades planned in `dependency-major-upgrades.md` (vite 8, eslint 10, tailwind 4).

**Trigger:** Before DNS cutover to custom domain, the app becomes "real" — indexed, bookmarked, targeted. This is the last checkpoint before public exposure.

**Risk areas identified but not yet audited:**
- Auth0 configuration (token expiry, scopes, API permissions)
- Cloud SQL network exposure (`0.0.0.0/0` — verify removed after Railway kill)
- Secret Manager IAM bindings (who/what can read secrets)
- Cloud Run IAM (allow-unauthenticated on both services)
- CSP policy completeness
- Terraform state security
- OWASP Top 10 check against API endpoints

---

## User Stories

### US-1: Infrastructure security audit

**As** the CTO,
**I want** a full audit of GCP IAM, networking, and secret management,
**So that** there are no misconfigurations before the app goes public.

**Acceptance criteria:**
- [ ] Cloud SQL: `0.0.0.0/0` removed from authorized networks (Phase 5 prerequisite)
- [ ] Cloud SQL: only VPC connector can reach the DB (private IP only)
- [ ] Secret Manager: only `cc-cloud-run-api@` and `cc-cloud-run-jobs@` can read secrets
- [ ] Cloud Run: review `--allow-unauthenticated` — required for frontend (SPA) and backend (API behind Auth0), but verify no admin endpoints are exposed
- [ ] Service account keys: no dangling keys, all rotated since last exposure (done 2026-03-30, verify)
- [ ] Terraform state: stored securely (GCS bucket with versioning + encryption)
- [ ] VPC connector: egress set to `private-ranges-only`
- [ ] Cloud Scheduler: OAuth token scoped correctly, SA has minimal permissions

### US-2: Application security audit (OWASP Top 10)

**As** the CTO,
**I want** the API endpoints reviewed against OWASP Top 10,
**So that** common vulnerabilities are caught before public exposure.

**Acceptance criteria:**
- [ ] **Injection:** All DB queries use parameterized SQLAlchemy (no raw SQL) — verify
- [ ] **Broken auth:** Auth0 JWT verification — check token expiry, audience validation, JWKS rotation
- [ ] **Sensitive data exposure:** No secrets in logs, error messages don't leak stack traces to client
- [ ] **Rate limiting:** All endpoints rate-limited (done in 4.3 — verify coverage)
- [ ] **Security headers:** HSTS, X-Frame-Options, X-Content-Type-Options (done in 4.3 — verify)
- [ ] **CORS:** Only frontend origin allowed, no wildcards
- [ ] **CSRF:** Not applicable (token-based auth, no cookies) — verify no cookie-based auth paths
- [ ] **SSRF:** No user-controlled URLs passed to backend fetch — verify audio streaming endpoint
- [ ] **Dependency vulnerabilities:** `pip audit` + `pnpm audit` — zero critical/high

### US-3: Auth0 hardening

**As** the CTO,
**I want** Auth0 configuration reviewed and tightened,
**So that** token theft or misconfiguration can't compromise user accounts.

**Acceptance criteria:**
- [ ] Access token expiry: reasonable (e.g., 1 hour, not 24 hours)
- [ ] Refresh token rotation enabled with absolute lifetime
- [ ] Allowed callback URLs: only production + localhost (remove Railway URLs after kill)
- [ ] Allowed logout URLs: same
- [ ] Allowed web origins: same
- [ ] API permissions: scoped correctly (no admin scopes on SPA client)
- [ ] Brute force protection enabled
- [ ] Bot detection enabled (if available on plan)
- [ ] MFA considered (not blocking, but documented as recommendation)

### US-4: Dependency audit

**As** the CTO,
**I want** all Python and Node dependencies scanned for known vulnerabilities,
**So that** no CVEs ship to production.

**Acceptance criteria:**
- `pip audit` on backend — zero critical/high
- `pnpm audit` on frontend — zero critical/high
- Playwright pinned to specific version (not `^1.58.0` which auto-upgrades)
- Add `pip audit` and `pnpm audit` to CI pipeline as non-blocking checks
- Document any accepted risks (e.g., dev-only deps with known issues)

### US-5: Custom domain setup

**As** a dashboard user,
**I want** to access the app at `app.com-compass.com` (or chosen domain),
**So that** it looks professional and is easy to bookmark.

**Acceptance criteria:**
- DNS: A/CNAME records pointing to Cloud Run
- SSL: managed by Cloud Run (automatic)
- Cloud Run domain mapping configured for both frontend and backend
- Auth0 callback URLs updated with custom domain
- CORS updated with custom domain
- CSP updated with custom domain
- Old `*.run.app` URLs still work (redirect or parallel access — TBD)
- HSTS preload submitted (after stable for 1+ month)

---

## Approach

### Option A: secops agent review (recommended)

Delegate to the `secops` agent for a structured review:
1. Infrastructure scan (Terraform + GCP config)
2. Application scan (code + endpoints)
3. Dependency scan (pip audit + pnpm audit)
4. Auth0 config review
5. Report with findings classified as CRITICAL/HIGH/MEDIUM/LOW

### Option B: Manual checklist

Walk through each US acceptance criteria manually. Faster but less thorough.

### Recommended timeline

| Step | When | Blocker for domain? | Status |
|------|------|---------------------|--------|
| Phase 5 (kill Railway) | — | Yes | **DONE** (2026-04-01) |
| Security blockers (C-1, H-1) | — | Yes | **DONE** (2026-04-01) |
| Custom domain setup (US-5) | — | — | **DONE** (2026-04-07) — `app.com-compass.com` + `api.com-compass.com` live |
| Dependency major upgrades | Next sprint | No (dev-only CVEs) | Planned — see `dependency-major-upgrades.md` |
| Post-launch security hardening | Next sprint | No | Planned — see `security-hardening-post-launch.md` |

---

## Out of Scope

- Penetration testing by external firm — consider for Series A prep
- SOC 2 compliance — future, if enterprise customers require it
- WAF (Web Application Firewall) — Cloud Armor available but overkill at current scale
- DDoS protection beyond Cloud Run auto-scaling — revisit at scale

## Dependencies

- ~~Phase 5 complete (Railway killed, `0.0.0.0/0` removed)~~ **DONE 2026-04-01**
- Custom domain purchased and DNS accessible
- Auth0 plan supports required features (brute force, bot detection)

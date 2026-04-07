# Custom Domain Setup — com-compass.com

**Date:** 2026-04-01 → Completed 2026-04-07
**Status:** DONE
**URLs:** `https://app.com-compass.com` (frontend), `https://api.com-compass.com` (backend)

---

## Target Configuration

| Subdomain | Service | Cloud Run |
|-----------|---------|-----------|
| `app.com-compass.com` | Frontend (React SPA) | `frontend-229076583962.europe-west9.run.app` |
| `api.com-compass.com` | Backend (FastAPI) | `backend-229076583962.europe-west9.run.app` |

- SSL: managed by Cloud Run (automatic)
- DNS: Google Cloud DNS (nameservers already at `ns-cloud-a*.googledomains.com`)
- Old `*.run.app` URLs: will stop working after mapping (no redirect needed)

---

## Step 1: Verify domain ownership in GCP

```bash
# Check if domain is already verified
gcloud domains list-user-verified

# If not listed, verify it:
gcloud domains verify com-compass.com
# This opens a browser — follow the steps (TXT record or meta tag)
```

If the domain is under the `com-compass.com` organization and you're org admin, it should auto-verify.

---

## Step 2: Create Cloud Run domain mappings

```bash
# Frontend
gcloud run domain-mappings create \
  --service=frontend \
  --domain=app.com-compass.com \
  --region=europe-west9

# Backend
gcloud run domain-mappings create \
  --service=backend \
  --domain=api.com-compass.com \
  --region=europe-west9
```

After running these, GCP will tell you what DNS records to create. Typically:
- **CNAME** `app` → `ghs.googlehosted.com.`
- **CNAME** `api` → `ghs.googlehosted.com.`

---

## Step 3: Add DNS records in Google Cloud DNS

Find your DNS zone:
```bash
gcloud dns managed-zones list --project=cacaooo
```

If the zone exists:
```bash
# Get the zone name (e.g., "com-compass-com")
ZONE="<zone-name-from-above>"

# Add CNAME for frontend
gcloud dns record-sets create app.com-compass.com \
  --zone=$ZONE \
  --type=CNAME \
  --ttl=300 \
  --rrdatas="ghs.googlehosted.com."

# Add CNAME for backend
gcloud dns record-sets create api.com-compass.com \
  --zone=$ZONE \
  --type=CNAME \
  --ttl=300 \
  --rrdatas="ghs.googlehosted.com."
```

If the zone doesn't exist in project `cacaooo`, check the Google Workspace admin — the DNS zone might be managed there or in another project.

---

## Step 4: Wait for SSL provisioning

Cloud Run automatically provisions a managed SSL certificate. This can take 15-60 minutes.

```bash
# Check certificate status
gcloud run domain-mappings describe \
  --domain=app.com-compass.com \
  --region=europe-west9

gcloud run domain-mappings describe \
  --domain=api.com-compass.com \
  --region=europe-west9
```

Look for `certificateStatus: ACTIVE`. Until then, HTTPS will show a certificate error.

---

## Step 5: Update Auth0 configuration

In Auth0 Dashboard (https://manage.auth0.com):

### Application Settings (SPA client)

**Allowed Callback URLs:**
```
https://app.com-compass.com,http://localhost:5173
```
(Remove any `*.run.app` or Railway URLs)

**Allowed Logout URLs:**
```
https://app.com-compass.com,http://localhost:5173
```

**Allowed Web Origins:**
```
https://app.com-compass.com,http://localhost:5173
```

### API Settings

**Identifier (Audience):** Keep as-is (`https://api.commodities-compass.com` or update to `https://api.com-compass.com`)

---

## Step 6: Update application configuration

### Frontend — Auth0 redirect URI + API base URL

Update GitHub Vars (Settings → Secrets and variables → Variables):

| Variable | Old value | New value |
|----------|-----------|-----------|
| `FRONTEND_URL` | `https://frontend-229076583962.europe-west9.run.app` | `https://app.com-compass.com` |
| `API_BASE_URL` | `https://backend-229076583962.europe-west9.run.app/v1` | `https://api.com-compass.com/v1` |

These are injected at build time via `--build-arg` in deploy.yml.

### Backend — CORS origins

Update GitHub Vars:

| Variable | Old value | New value |
|----------|-----------|-----------|
| `BACKEND_CORS_ORIGINS` | `["https://frontend-229076583962.europe-west9.run.app"]` | `["https://app.com-compass.com"]` |

> **Important:** Use `gcloud run services update --update-env-vars` (not `--set-env-vars`) to avoid wiping other env vars. Or just redeploy via push to main.

---

## Step 7: Redeploy

Push any commit to main to trigger CI/CD with the updated GitHub Vars:

```bash
git commit --allow-empty -m "chore: trigger deploy with custom domain config"
git push
```

Or manually redeploy:
```bash
# Frontend (needs rebuild for new Auth0/API URLs baked in)
gcloud run services update frontend \
  --region=europe-west9 \
  --update-env-vars=FRONTEND_URL=https://app.com-compass.com

# Backend (needs CORS update)
gcloud run services update backend \
  --region=europe-west9 \
  --update-env-vars="BACKEND_CORS_ORIGINS=[\"https://app.com-compass.com\"]"
```

---

## Step 8: Verify

- [ ] `https://app.com-compass.com` loads the dashboard
- [ ] SSL certificate is valid (no warnings)
- [ ] Login via Auth0 works (redirect loop-free)
- [ ] Dashboard loads all 7 widgets (position, indicators, recommendations, chart, news, weather, audio)
- [ ] `https://api.com-compass.com/health` returns `{"status": "healthy"}`
- [ ] `https://api.com-compass.com/v1/docs` returns 404 (not accessible in prod)
- [ ] Audio player works (Google Drive streaming)
- [ ] Date selector works (business day navigation)

---

## Rollback

If something breaks:
1. Remove domain mappings: `gcloud run domain-mappings delete --domain=app.com-compass.com --region=europe-west9`
2. Revert GitHub Vars to `*.run.app` URLs
3. Redeploy
4. The `*.run.app` URLs resume working immediately

---

## Post-setup (next day)

- [ ] Remove `*.run.app` URLs from Auth0 Allowed Callbacks/Origins
- [ ] Add `Referrer-Policy: strict-origin-when-cross-origin` to security headers
- [ ] Consider HSTS preload submission (after stable for 1+ month)
- [ ] Update CLAUDE.md with final domain URLs

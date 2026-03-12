# Infrastructure — GCP / Terraform

> Provisioned 2026-03-12 (Phase 0.2). Terraform manages the platform layer.
> Cloud Run services are deployed by GitHub Actions (`deploy.yml`), not Terraform.

## GCP Project

| Key | Value |
|-----|-------|
| Project ID | `cacaooo` |
| Project Number | `229076583962` |
| Organization | `710889932` |
| Region | `europe-west9` (Paris) |
| TF State | `gs://tf-state-cacaooo` (versioning enabled) |

## Architecture Overview

```
                  GitHub Actions (OIDC)
                         │
                    WIF Provider
                         │
                  ┌──────▼──────┐
                  │  Artifact   │
                  │  Registry   │
                  └──────┬──────┘
                         │ docker push/pull
           ┌─────────────┼─────────────┐
           │             │             │
     ┌─────▼─────┐ ┌────▼────┐ ┌─────▼──────┐
     │ Cloud Run │ │Cloud Run│ │ Cloud Run  │
     │  Backend  │ │Frontend │ │   Jobs     │
     │(cc-api SA)│ │         │ │(cc-jobs SA)│
     └─────┬─────┘ └─────────┘ └─────┬──────┘
           │                          │
           │    VPC Connector         │
           │   (cc-vpc-connector)     │
           └──────────┬───────────────┘
                      │
              ┌───────▼────────┐
              │   cc-vpc       │
              │  10.0.0.0/24   │
              │  (private IP)  │
              └───────┬────────┘
                      │ PSA Peering
              ┌───────▼────────┐
              │  Cloud SQL     │
              │  cc-postgres   │
              │  PG15 (private)│
              └────────────────┘
```

## Terraform Files

```
infra/terraform/
├── main.tf              # Provider, backend, 13 API enablements
├── variables.tf         # All variable declarations
├── terraform.tfvars     # Non-sensitive values (committed)
├── vpc.tf               # VPC, subnet, PSA, VPC connector
├── cloudsql.tf          # Cloud SQL PG15, database, user
├── artifact_registry.tf # Docker repo + cleanup policies
├── secrets.tf           # Secret Manager (13 secrets)
├── iam.tf               # 3 service accounts + IAM bindings
├── wif.tf               # Workload Identity Federation (GitHub OIDC)
├── scheduler.tf         # 8 cron jobs (paused)
├── monitoring.tf        # Email notification + Cloud SQL alert
├── outputs.tf           # Key outputs + github_vars map
└── .terraform.lock.hcl  # Provider pinning (committed)
```

## Resources (67 total)

### Networking (`vpc.tf`)

| Resource | Name | Details |
|----------|------|---------|
| VPC | `cc-vpc` | Custom, no auto-subnets |
| Subnet | `cc-vpc-subnet` | `10.0.0.0/24`, private Google access |
| PSA Range | `cc-private-ip-range` | `/20` internal for Cloud SQL peering |
| PSA Connection | — | Peers Google-managed VPC with ours |
| VPC Connector | `cc-vpc-connector` | `10.8.0.0/28`, 200-300 Mbps |

### Database (`cloudsql.tf`)

| Resource | Name | Details |
|----------|------|---------|
| Instance | `cc-postgres` | PG15, `db-f1-micro`, ZONAL, private IP only |
| Database | `commodities_compass` | — |
| User | `cc_app` | 32-char random password (no special chars) |

- 10GB SSD, autoresize enabled
- Backups at 03:00 UTC, 7 days retention, no PITR
- Maintenance: Sunday 04:00 UTC, stable track
- `deletion_protection = true`
- Flags: `log_checkpoints`, `log_connections`, `log_disconnections`

### Artifact Registry (`artifact_registry.tf`)

| Resource | Name | Details |
|----------|------|---------|
| Docker Repo | `commodities-compass` | DOCKER format, europe-west9 |

- Cleanup: keep latest 10 tagged, delete untagged > 7 days

### Secret Manager (`secrets.tf`)

13 secrets, single replica `europe-west9`:

| Secret | Source |
|--------|--------|
| `DATABASE_URL` | Auto-computed by Terraform (`postgresql+asyncpg://...`) |
| `DATABASE_SYNC_URL` | Auto-computed by Terraform (`postgresql+psycopg2://...`) |
| `AUTH0_DOMAIN` | Manual |
| `AUTH0_CLIENT_ID` | Manual |
| `AUTH0_API_AUDIENCE` | Manual |
| `AUTH0_ISSUER` | Manual |
| `GOOGLE_SHEETS_CREDENTIALS_JSON` | Manual |
| `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON` | Manual |
| `GOOGLE_DRIVE_CREDENTIALS_JSON` | Empty (not used yet) |
| `SENTRY_DSN` | Manual |
| `ANTHROPIC_API_KEY` | Manual |
| `OPENAI_API_KEY` | Manual |
| `GEMINI_API_KEY` | Manual |

### IAM (`iam.tf`)

| Service Account | Purpose | Key Roles |
|----------------|---------|-----------|
| `cc-cloud-run-api` | Backend + Frontend Cloud Run | secretmanager.secretAccessor, cloudsql.client, logging.logWriter, monitoring.metricWriter |
| `cc-cloud-run-jobs` | Scrapers, Agents, ETL | Same as API (separate for audit trail) |
| `cc-github-actions` | CI/CD deploy | artifactregistry.writer, run.admin, iam.serviceAccountUser, secretmanager.secretAccessor |

### Workload Identity Federation (`wif.tf`)

| Resource | Value |
|----------|-------|
| Pool | `github-actions` |
| Provider | `github-oidc` (OIDC issuer: `token.actions.githubusercontent.com`) |
| Condition | `assertion.repository == 'Commodities-Compass/commodities-compass'` |

Keyless auth: GitHub OIDC token exchanged for short-lived GCP access token at each workflow run.

### Cloud Scheduler (`scheduler.tf`)

8 cron jobs, all `paused = true` until Phase 4.1.
Region: `europe-west1` (europe-west9 not supported for Scheduler).

| Job | Schedule (UTC) |
|-----|---------------|
| `cc-barchart-scraper` | `0 21 * * 1-5` |
| `cc-ice-stocks-scraper` | `10 21 * * 1-5` |
| `cc-cftc-scraper` | `10 21 * * 1-5` |
| `cc-press-review-agent` | `10 21 * * 1-5` |
| `cc-meteo-agent` | `10 21 * * 1-5` |
| `cc-daily-analysis` | `20 21 * * 1-5` |
| `cc-compass-brief` | `30 21 * * 1-5` |
| `cc-data-import-etl` | `15 22 * * 1-5` |

HTTP targets point to Cloud Run Jobs execution endpoints (placeholders).

### Monitoring (`monitoring.tf`)

| Resource | Details |
|----------|---------|
| Notification Channel | Email to `hedi@com-compass.com` |
| Alert Policy | Cloud SQL instance down (`database/up < 1` for 300s) |

## GitHub Repository Variables

Set via `gh variable set`, used by `deploy.yml`:

| Variable | Value |
|----------|-------|
| `GCP_PROJECT_ID` | `cacaooo` |
| `GCP_REGION` | `europe-west9` |
| `GCP_WIF_PROVIDER` | `projects/229076583962/locations/global/workloadIdentityPools/github-actions/providers/github-oidc` |
| `GCP_SA_EMAIL` | `cc-github-actions@cacaooo.iam.gserviceaccount.com` |

## Operations

### Run Terraform

```bash
cd infra/terraform
terraform init          # first time or after provider changes
terraform plan          # preview changes
terraform apply         # apply (requires confirmation)
terraform output        # show outputs
terraform output -json github_vars  # GitHub vars to copy
```

### Populate a Secret

```bash
echo -n "value" | gcloud secrets versions add SECRET_NAME --data-file=-
gcloud secrets versions access latest --secret=SECRET_NAME  # verify
```

### Verify Infrastructure

```bash
gcloud compute networks describe cc-vpc
gcloud sql instances describe cc-postgres
gcloud secrets list --filter="name:projects/cacaooo"
gcloud iam service-accounts list --filter="email:cc-*"
gcloud scheduler jobs list --location=europe-west1
```

## Cost Estimate

| Resource | $/mo |
|----------|------|
| Cloud SQL db-f1-micro + 10GB SSD + backups | ~$10 |
| VPC Connector (min throughput) | ~$7 |
| Artifact Registry | ~$0.50 |
| Secret Manager (13 secrets) | ~$0.10 |
| Cloud Scheduler (paused) | $0 |
| Monitoring | $0 |
| **Total** | **~$18/mo** |

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Flat files, no modules | Single env, single region | Modules add indirection unjustified at this stage |
| Cloud SQL `db-f1-micro` | 353 rows, 1 user | Upgrade via `db_tier` variable |
| Cloud SQL ZONAL | No HA | Doubles cost, no business justification yet |
| Cloud SQL private IP only | No public exposure | Cloud Run connects via VPC connector |
| 2 runtime SAs | `cc-api` + `cc-jobs` | Audit separation, future per-secret scoping |
| Cloud Run outside TF | GitHub Actions deploys | Intentional boundary — TF owns platform, GHA owns app |
| `disable_on_destroy = false` | All API enablements | Prevents accidental API disable breaking other services |
| `.terraform.lock.hcl` committed | Provider pinning | Reproducible builds across machines |
| Scheduler in `europe-west1` | europe-west9 not supported | Only affects cron trigger location, not job execution |

## Caveats

1. **Cloud SQL takes ~12 min** to provision on first `terraform apply`
2. **PSA peering takes ~5-10 min** — dependency chain handles ordering
3. **WIF attribute condition is case-sensitive** — `Commodities-Compass/commodities-compass` must match exactly
4. **db-f1-micro has 614 MB RAM** — sufficient for 353 rows / 1 user, watch for OOM on heavy Alembic migrations
5. **No Redis/Memorystore** — `REDIS_URL` is declared in config but never imported in `app/`, dev-only dependency

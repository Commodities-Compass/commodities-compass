# ==============================================================================
# Landing site (com-compass.com + www)
#
# Pattern: single Cloud Storage bucket + Cloud CDN behind the existing Global
# HTTPS LB. No staging environment — landing is fully static, the dev loop runs
# locally (`pnpm dev`), and edits go straight to prod on push-to-main.
#
# Build artifact: `landing/dist/` (Astro 5 static output, ~920 KB).
# Pipeline: GitHub Actions (deploy-landing.yml) builds Astro and rsyncs to GCS.
#
# Cost target: < 1 €/mo combined storage + CDN egress at expected volume
# (50-200 UV/mo at launch, target 1-2k UV/mo at 6mo).
#
# Status: defined here; APPLY is a manual `terraform apply` after PR merge to
# main (see docs/user-stories/P1-landing-deploy-gcp.md for the runbook).
# ==============================================================================

# ---- Bucket (static site hosting) ----

resource "google_storage_bucket" "landing" {
  name          = "${var.project_id}-landing"
  project       = var.project_id
  location      = "EU"
  force_destroy = false

  uniform_bucket_level_access = true

  website {
    main_page_suffix = "index.html"
    not_found_page   = "404.html"
  }

  # Versioning ON so a bad deploy can be rolled back to a prior object
  # generation without re-running the build (see runbook).
  versioning {
    enabled = true
  }

  labels = var.labels
}

# ---- Public-read IAM ----
# allUsers viewer is the canonical pattern for public static sites served via
# Cloud CDN. Cloud CDN is the only client facing the public internet;
# direct bucket-URL access also works but isn't advertised.

resource "google_storage_bucket_iam_member" "landing_public" {
  bucket = google_storage_bucket.landing.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

# ---- Backend bucket (Cloud CDN attach point for the LB) ----

resource "google_compute_backend_bucket" "landing" {
  name        = "cc-backend-landing"
  project     = var.project_id
  bucket_name = google_storage_bucket.landing.name
  enable_cdn  = true

  cdn_policy {
    cache_mode         = "CACHE_ALL_STATIC"
    default_ttl        = 3600  # 1h default for static assets
    max_ttl            = 86400 # 24h cap
    client_ttl         = 3600
    negative_caching   = true
    serve_while_stale  = 60 # serve stale 60s on origin error
    request_coalescing = true
  }

  # Security headers applied to every CDN response.
  custom_response_headers = [
    "X-Content-Type-Options: nosniff",
    "Referrer-Policy: strict-origin-when-cross-origin",
    "Permissions-Policy: geolocation=(), microphone=(), camera=()",
  ]
}

# ---- Google-managed SSL certificate ----
# Multi-SAN so com-compass.com and www.com-compass.com share a single cert
# lifecycle. Follows the existing convention (1 cert per "site" — same pattern
# as cc-ssl-app and cc-ssl-api).

resource "google_compute_managed_ssl_certificate" "landing_apex" {
  name    = "cc-ssl-landing-apex"
  project = var.project_id

  managed {
    domains = [
      "com-compass.com",
      "www.com-compass.com",
    ]
  }
}

# ---- Outputs for the runbook ----

output "landing_lb_ip" {
  description = "Static IP of the Global HTTPS LB — set DNS A records to this address."
  value       = google_compute_global_address.lb.address
}

output "landing_bucket" {
  description = "Name of the landing bucket (target for GHA gcloud storage rsync)."
  value       = google_storage_bucket.landing.name
}

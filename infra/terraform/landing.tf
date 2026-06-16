# ==============================================================================
# Landing site (com-compass.com + staging.com-compass.com)
#
# Pattern: Cloud Storage bucket + Cloud CDN behind the existing Global HTTPS LB.
# Two buckets (staging + prod) so we can validate on staging before swapping the
# apex DNS. Same LB, same static IP (cc-lb-ip), no new infra surface.
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

# ---- Buckets (static site hosting) ----

resource "google_storage_bucket" "landing_prod" {
  name          = "${var.project_id}-landing"
  project       = var.project_id
  location      = "EU"
  force_destroy = false

  uniform_bucket_level_access = true

  website {
    main_page_suffix = "index.html"
    not_found_page   = "404.html"
  }

  versioning {
    enabled = true
  }

  labels = var.labels
}

resource "google_storage_bucket" "landing_staging" {
  name          = "${var.project_id}-landing-staging"
  project       = var.project_id
  location      = "EU"
  force_destroy = false

  uniform_bucket_level_access = true

  website {
    main_page_suffix = "index.html"
    not_found_page   = "404.html"
  }

  # Versioning off on staging — short-lived previews, no need to retain history.

  labels = merge(var.labels, { environment = "staging" })
}

# ---- Public-read IAM ----
# allUsers viewer is the canonical pattern for public static sites served via
# Cloud CDN. Cloud CDN itself is the only "client" facing the public internet;
# direct bucket-URL access also works but isn't advertised.

resource "google_storage_bucket_iam_member" "landing_prod_public" {
  bucket = google_storage_bucket.landing_prod.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

resource "google_storage_bucket_iam_member" "landing_staging_public" {
  bucket = google_storage_bucket.landing_staging.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

# ---- Backend buckets (Cloud CDN attach point for the LB) ----

resource "google_compute_backend_bucket" "landing_prod" {
  name        = "cc-backend-landing-prod"
  project     = var.project_id
  bucket_name = google_storage_bucket.landing_prod.name
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

  # Custom error response: serve our /404.html for any 404 from the bucket.
  # GCS website config already does this, but Cloud CDN can short-circuit.
  custom_response_headers = [
    "X-Content-Type-Options: nosniff",
    "Referrer-Policy: strict-origin-when-cross-origin",
    "Permissions-Policy: geolocation=(), microphone=(), camera=()",
  ]
}

resource "google_compute_backend_bucket" "landing_staging" {
  name        = "cc-backend-landing-staging"
  project     = var.project_id
  bucket_name = google_storage_bucket.landing_staging.name
  enable_cdn  = true

  cdn_policy {
    cache_mode         = "CACHE_ALL_STATIC"
    default_ttl        = 300 # 5min on staging for faster iteration
    max_ttl            = 3600
    client_ttl         = 300
    negative_caching   = true
    serve_while_stale  = 60
    request_coalescing = true
  }

  custom_response_headers = [
    "X-Robots-Tag: noindex, nofollow", # never let staging get indexed
    "X-Content-Type-Options: nosniff",
    "Referrer-Policy: strict-origin-when-cross-origin",
  ]
}

# ---- Google-managed SSL certificates ----
# Following the existing convention (1 cert per "site" — same pattern as
# cc-ssl-app and cc-ssl-api). The apex cert is multi-SAN so com-compass.com
# and www.com-compass.com share a single cert lifecycle.

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

resource "google_compute_managed_ssl_certificate" "landing_staging" {
  name    = "cc-ssl-landing-staging"
  project = var.project_id

  managed {
    domains = ["staging.com-compass.com"]
  }
}

# ---- Outputs for the runbook ----

output "landing_lb_ip" {
  description = "Static IP of the Global HTTPS LB — set DNS A records to this address."
  value       = google_compute_global_address.lb.address
}

output "landing_prod_bucket" {
  description = "Name of the prod landing bucket (target for GHA gcloud storage rsync)."
  value       = google_storage_bucket.landing_prod.name
}

output "landing_staging_bucket" {
  description = "Name of the staging landing bucket."
  value       = google_storage_bucket.landing_staging.name
}

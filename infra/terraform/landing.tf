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

# Grant the GitHub Actions service account write access on the landing bucket.
# Needed for `gcloud storage rsync --delete-unmatched-destination-objects`
# in .github/workflows/deploy-landing.yml. Project-level roles don't cover
# bucket-level permissions like storage.buckets.get, so this must be scoped
# per bucket.
resource "google_storage_bucket_iam_member" "landing_gha_writer" {
  bucket = google_storage_bucket.landing.name
  role   = "roles/storage.admin"
  member = "serviceAccount:cc-github-actions@${var.project_id}.iam.gserviceaccount.com"
}

# Custom role for CDN cache invalidation. The predefined roles that grant
# `compute.urlMaps.invalidateCache` (loadBalancerAdmin, networkAdmin) also
# grant broad edit rights on the LB — overkill for a cache-invalidate action.
# This custom role is scoped to just the single permission we need.
resource "google_project_iam_custom_role" "cdn_invalidator" {
  project     = var.project_id
  role_id     = "cdnCacheInvalidator"
  title       = "CDN Cache Invalidator"
  description = "Allows invalidating Cloud CDN cache via url-maps.invalidateCache"
  permissions = ["compute.urlMaps.invalidateCache"]
  stage       = "GA"
}

resource "google_project_iam_member" "landing_gha_cdn_invalidator" {
  project = var.project_id
  role    = google_project_iam_custom_role.cdn_invalidator.id
  member  = "serviceAccount:cc-github-actions@${var.project_id}.iam.gserviceaccount.com"
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
  # HSTS max-age=2y + includeSubDomains + preload → eligible for
  # https://hstspreload.org submission (Chrome/Firefox/Safari built-in list).
  # CSP is strict for a fully-static site: only same-origin assets, plausible.io
  # allowed under connect-src (activated later via PUBLIC_PLAUSIBLE_DOMAIN env var).
  # 'unsafe-inline' on script-src / style-src is needed for the inline audio
  # player script (BriefAudio.astro) and Astro's inlined critical CSS —
  # acceptable because no user input surface = no XSS injection vector.
  # object-src 'none' blocks <embed>/<object>/<applet> (legacy Flash-era holes).
  # frame-ancestors 'none' = anti-clickjacking (equivalent + stronger than X-Frame-Options).
  # base-uri 'self' + form-action 'none' close remaining CSP escape hatches.
  custom_response_headers = [
    "Strict-Transport-Security: max-age=63072000; includeSubDomains; preload",
    "Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; media-src 'self'; connect-src 'self' https://plausible.io; frame-ancestors 'none'; base-uri 'self'; form-action 'none'; object-src 'none'; upgrade-insecure-requests",
    "X-Content-Type-Options: nosniff",
    "X-Frame-Options: DENY",
    "Referrer-Policy: strict-origin-when-cross-origin",
    "Permissions-Policy: geolocation=(), microphone=(), camera=(), payment=(), usb=(), fullscreen=(self), display-capture=(), autoplay=(self)",
    "Cross-Origin-Opener-Policy: same-origin",
    "Cross-Origin-Resource-Policy: same-origin",
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

# ---- Uptime monitoring ----
# Free tier (1M checks/mo/project incl.). Multi-region checks catch regional
# LB issues + regional Cloud CDN edge failures. Notification channel is
# reused from monitoring.tf (google_monitoring_notification_channel.email).

resource "google_monitoring_uptime_check_config" "landing_https" {
  display_name = "Landing HTTPS Availability"
  timeout      = "10s"
  period       = "60s"

  http_check {
    path         = "/"
    port         = 443
    use_ssl      = true
    validate_ssl = true

    accepted_response_status_codes {
      status_class = "STATUS_CLASS_2XX"
    }
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = "com-compass.com"
    }
  }
}

resource "google_monitoring_alert_policy" "landing_uptime" {
  display_name = "Landing HTTPS Check Failed"
  combiner     = "OR"

  conditions {
    display_name = "https://com-compass.com/ is down"

    condition_threshold {
      filter          = "resource.type = \"uptime_url\" AND metric.type = \"monitoring.googleapis.com/uptime_check/check_passed\" AND metric.labels.check_id = \"${google_monitoring_uptime_check_config.landing_https.uptime_check_id}\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 1

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields      = ["resource.label.host"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]

  documentation {
    content   = "Landing https://com-compass.com/ is not responding. Check LB backend bucket + CDN + bucket content: https://console.cloud.google.com/net-services/loadbalancing/details/http/cc-url-map?project=${var.project_id}"
    mime_type = "text/markdown"
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

# ==============================================================================
# Global HTTPS Load Balancer — custom domain routing
#
# Routes app.com-compass.com → frontend Cloud Run service
#         api.com-compass.com → backend Cloud Run service
#
# Cloud Run domain mappings are NOT supported in europe-west9, so we use a
# Global HTTPS LB with serverless NEGs instead. This is the production-standard
# approach (used by Stripe, Vercel, every serious SaaS).
#
# Cost: ~$18/mo (forwarding rule) + $0.008/GB egress
# ==============================================================================

# ---- Static IP ----

resource "google_compute_global_address" "lb" {
  name    = "cc-lb-ip"
  project = var.project_id
}

# ---- Google-managed SSL certificates ----

resource "google_compute_managed_ssl_certificate" "app" {
  name    = "cc-ssl-app"
  project = var.project_id

  managed {
    domains = ["app.com-compass.com"]
  }
}

resource "google_compute_managed_ssl_certificate" "api" {
  name    = "cc-ssl-api"
  project = var.project_id

  managed {
    domains = ["api.com-compass.com"]
  }
}

# ---- Serverless NEGs (point to Cloud Run services) ----

resource "google_compute_region_network_endpoint_group" "frontend" {
  name                  = "cc-neg-frontend"
  region                = var.region
  project               = var.project_id
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = "frontend"
  }
}

resource "google_compute_region_network_endpoint_group" "backend" {
  name                  = "cc-neg-backend"
  region                = var.region
  project               = var.project_id
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = "backend"
  }
}

# ---- Backend services ----

resource "google_compute_backend_service" "frontend" {
  name                  = "cc-backend-frontend"
  project               = var.project_id
  protocol              = "HTTP"
  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.frontend.id
  }
}

resource "google_compute_backend_service" "backend" {
  name                  = "cc-backend-api"
  project               = var.project_id
  protocol              = "HTTP"
  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.backend.id
  }
}

# ---- URL map (host-based routing) ----

resource "google_compute_url_map" "main" {
  name            = "cc-url-map"
  project         = var.project_id
  default_service = google_compute_backend_service.frontend.id

  host_rule {
    hosts        = ["app.com-compass.com"]
    path_matcher = "app"
  }

  host_rule {
    hosts        = ["api.com-compass.com"]
    path_matcher = "api"
  }

  path_matcher {
    name            = "app"
    default_service = google_compute_backend_service.frontend.id
  }

  path_matcher {
    name            = "api"
    default_service = google_compute_backend_service.backend.id
  }
}

# ---- HTTPS proxy + forwarding rule ----

resource "google_compute_target_https_proxy" "main" {
  name    = "cc-https-proxy"
  project = var.project_id
  url_map = google_compute_url_map.main.id

  ssl_certificates = [
    google_compute_managed_ssl_certificate.app.id,
    google_compute_managed_ssl_certificate.api.id,
  ]
}

resource "google_compute_global_forwarding_rule" "https" {
  name                  = "cc-https-rule"
  project               = var.project_id
  ip_address            = google_compute_global_address.lb.address
  port_range            = "443"
  target                = google_compute_target_https_proxy.main.id
  load_balancing_scheme = "EXTERNAL_MANAGED"
}

# ---- HTTP → HTTPS redirect ----

resource "google_compute_url_map" "http_redirect" {
  name    = "cc-http-redirect"
  project = var.project_id

  default_url_redirect {
    https_redirect         = true
    strip_query            = false
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
  }
}

resource "google_compute_target_http_proxy" "redirect" {
  name    = "cc-http-redirect-proxy"
  project = var.project_id
  url_map = google_compute_url_map.http_redirect.id
}

resource "google_compute_global_forwarding_rule" "http_redirect" {
  name                  = "cc-http-redirect-rule"
  project               = var.project_id
  ip_address            = google_compute_global_address.lb.address
  port_range            = "80"
  target                = google_compute_target_http_proxy.redirect.id
  load_balancing_scheme = "EXTERNAL_MANAGED"
}

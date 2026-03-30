# ==============================================================================
# Cloud Scheduler — Cron jobs (all paused until Phase 4.1)
# ==============================================================================
#
# All jobs are created with paused=true. They target Cloud Run Jobs execution
# endpoints (placeholders). Activated when Cloud Run Jobs are deployed in
# Phase 4.1 by setting paused=false and updating the URI if needed.
#
# NOTE: Cloud Scheduler does not support europe-west9 (Paris). Jobs are
# created in europe-west1 (Belgium, EU/GDPR). The scheduler location only
# affects where the cron trigger runs, not where the target executes —
# Cloud Run Jobs still run in europe-west9.
# ==============================================================================

locals {
  cron_jobs = {
    barchart-scraper = {
      description = "Scrape Barchart OHLCV+IV for active cocoa contract"
      schedule    = "0 21 * * 1-5"
    }
    ice-stocks-scraper = {
      description = "Scrape ICE certified cocoa stock reports"
      schedule    = "10 21 * * 1-5"
    }
    cftc-scraper = {
      description = "Scrape CFTC COT commercial net position"
      schedule    = "10 21 * * 1-5"
    }
    press-review-agent = {
      description = "Generate daily cocoa press review via LLM"
      schedule    = "10 21 * * 1-5"
    }
    meteo-agent = {
      description = "Fetch weather data and generate cocoa impact analysis"
      schedule    = "10 21 * * 1-5"
    }
    daily-analysis = {
      description = "Run daily trading analysis with LLM scoring"
      schedule    = "20 21 * * 1-5"
    }
    compass-brief = {
      description = "Generate structured brief and upload to Google Drive"
      schedule    = "30 21 * * 1-5"
    }
    compute-indicators = {
      description = "Compute technical indicators from raw market data"
      schedule    = "15 21 * * 1-5"
    }
    data-import-etl = {
      description = "Full-refresh ETL from Google Sheets to PostgreSQL"
      schedule    = "15 22 * * 1-5"
    }
  }
}

resource "google_cloud_scheduler_job" "cron_jobs" {
  for_each = local.cron_jobs

  name        = "cc-${each.key}"
  description = each.value.description
  schedule    = each.value.schedule
  time_zone   = "UTC"
  region      = var.scheduler_region

  paused = true

  http_target {
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/cc-${each.key}:run"
    http_method = "POST"

    oauth_token {
      service_account_email = google_service_account.cloud_run_jobs.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  retry_config {
    retry_count          = 1
    max_retry_duration   = "300s"
    min_backoff_duration = "30s"
    max_backoff_duration = "120s"
  }

  depends_on = [google_project_service.required_apis["cloudscheduler.googleapis.com"]]
}

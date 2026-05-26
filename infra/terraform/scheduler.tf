# ==============================================================================
# Cloud Scheduler — Cron jobs
# ==============================================================================
#
# All jobs target Cloud Run Jobs execution endpoints.
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
      schedule    = "0 19 * * 1-5"
    }
    ice-stocks-scraper = {
      description = "Scrape ICE certified cocoa stock reports"
      schedule    = "5 19 * * 1-5"
    }
    cftc-scraper = {
      description = "Scrape CFTC COT commercial net position"
      schedule    = "5 19 * * 1-5"
    }
    press-review-agent = {
      description = "Generate daily cocoa press review via LLM"
      schedule    = "5 19 * * 1-5"
    }
    meteo-agent = {
      description = "Fetch weather data and generate cocoa impact analysis"
      schedule    = "0 19 * * 1-5"
    }
    compute-indicators = {
      description = "Compute technical indicators for all enabled algorithm versions"
      schedule    = "15 19 * * 1-5"
    }
    daily-analysis = {
      description = "Run daily trading analysis with LLM scoring"
      schedule    = "20 19 * * 1-5"
    }
    compass-brief = {
      description = "Generate structured brief and upload to Google Drive"
      schedule    = "30 19 * * 1-5"
    }
    # External-data scrapers for Campaign 5 ensemble.
    enso-scraper = {
      description = "Scrape NOAA PSL ENSO indices (ONI + Niño 3.4)"
      # Day 20 of month at 22:00 UTC — NOAA publishes mid-month for prior month.
      # IMPORTANT: when both dom and dow are specified in cron, Cloud Scheduler
      # uses OR semantics (fires on day-20 OR any weekday). We need ONLY the
      # 20th of each month → dow MUST be '*'. If the 20th lands on a weekend
      # NOAA data is still available and the upsert is idempotent for a
      # manual rescrape: `gcloud run jobs execute cc-enso-scraper`.
      schedule = "0 22 20 * *"
    }
    fx-scraper = {
      description = "Scrape ECB SDMX FX rates (USD/EUR + GBP/EUR → DXY proxy + GBPUSD)"
      # 18:30 UTC business days — ECB publishes ~16:00 CET, before cc-ensemble-compute (19:18).
      schedule = "30 18 * * 1-5"
    }
    ice-cot-eu-scraper = {
      description = "Scrape ICE Europe COT cocoa positioning (weekly snapshot)"
      # Daily 22:10 UTC weekdays — ICE publishes Friday ~21:30 CET for prior
      # Tuesday's snapshot. UPSERT is idempotent on (release_date,
      # contract_market) so the daily cron catches late publishes without
      # coupling the job schedule to ICE's exact publication time.
      schedule = "10 22 * * 1-5"
    }
    barchart-stocks-eu-scraper = {
      description = "Scrape ICE Europe certified cocoa stocks (60kg bags) from Barchart cmdty"
      # 19:10 UTC weekdays — 10 min after cc-barchart-scraper (19:00) so the
      # OHLCV row exists before the UPDATE. Barchart publishes daily on
      # business days, native unit is "60 Kg Bag" (no conversion).
      schedule = "10 19 * * 1-5"
    }
    ensemble-compute = {
      description = "C5 ensemble: soft-gate + Compass wrapper daily decision (shadow mode v1.0.0)"
      # 19:18 UTC weekdays — sandwiched between cc-compute-indicators (19:15)
      # and cc-daily-analysis (19:20). The ensemble reads pl_derived_indicators
      # which compute-indicators must have written first, and daily-analysis
      # reads pl_indicator_daily which ensemble-compute writes here (legacy
      # version flag prevents overwrite, see deploy.yml).
      schedule = "18 19 * * 1-5"
    }
    # NB: cc-ensemble-bootstrap-artifacts is deployed without a scheduler.
    # Triggered manually via gcloud when R&D ships a new frozen artefact pack.
    # Quarterly fundamentals (low-frequency, calendar-gated).
    eca-grindings-scraper = {
      description = "Scrape ECA Western Europe Cocoa Grindings (quarterly, calendar-gated)"
      # 13:00 UTC weekdays. ECA publishes Thursdays ~14:00 CET on the
      # ~16th of the month after each quarter end. The agent gates against
      # ref_publication_calendar and exits 0 if no publication is pending,
      # so the daily cron is cheap (~250 no-ops/year).
      schedule = "0 13 * * 1-5"
    }
    nca-grindings-scraper = {
      description = "Scrape NCA North-American Cocoa Grindings (quarterly, calendar-gated)"
      # 14:00 UTC weekdays. NCA publishes ~mid-day ET on the same window
      # as ECA. Same calendar-gated pattern as eca-grindings-scraper.
      schedule = "0 14 * * 1-5"
    }
    publication-calendar-watchdog = {
      description = "Alert on fundamental publications overdue ≥ 21 days"
      # 16:00 UTC weekdays — runs after both grindings scrapers so any
      # successful ingestion of the day is reflected before we check for
      # silence.
      schedule = "0 16 * * 1-5"
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

  paused = false

  http_target {
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/cc-${each.key}:run"
    http_method = "POST"

    oauth_token {
      service_account_email = google_service_account.cloud_run_jobs.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  retry_config {
    retry_count = 0
  }

  depends_on = [google_project_service.required_apis["cloudscheduler.googleapis.com"]]
}

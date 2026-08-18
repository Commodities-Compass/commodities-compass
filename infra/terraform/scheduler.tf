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
      description = "Generate cocoa press review for upcoming session via LLM (P2b calendar-aware)"
      # P2b: daily cron — the agent itself gates on is_eve_of_trading_day().
      # Writes are tagged to the next trading session (Sun eve → Mon session).
      schedule = "5 19 * * *"
    }
    meteo-agent = {
      description = "Fetch weather data + LLM cocoa impact analysis for upcoming session (P2b calendar-aware)"
      # P2b: daily cron with eve-of-trading-day gate (see press-review-agent).
      schedule = "0 19 * * *"
    }
    compute-indicators = {
      description = "Technical indicators (per version) + dashboard gauges (algorithm-independent)"
      schedule    = "15 19 * * 1-5"
    }
    daily-analysis = {
      description = "Run trading analysis with LLM scoring, keyed to last completed session (P2b calendar-aware)"
      # P2b: daily cron — agent gates on is_eve_of_trading_day(). Reads AND
      # writes the LLM decision at data_date = last completed session T
      # (resolve_phase_b_dates). Backfill: --session-date T.
      schedule = "20 19 * * *"
    }
    compass-brief = {
      description = "Generate brief for last completed session + upload to Drive (P2b calendar-aware)"
      # P2b: daily cron. Filename keyed on data_date (= session T) so the audio
      # fetch path on the dashboard (which looks up by session date) finds the
      # right brief on Mon morning after a Sun-eve generation.
      schedule = "30 19 * * *"
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
      # 19:18 UTC daily, agent-gated on eve-of-trading-day (P2b). Captures
      # weekend macro news (Sun eve fires for Mon session, reading the fresh
      # pl_article_segment that press-review just wrote at 19:05 with
      # article_date = previous_session). Sandwiched between
      # cc-press-review-agent (19:05) and cc-daily-analysis (19:20) so the
      # MacroSignal sees the latest articles, and daily-analysis sees the
      # ensemble row this job writes. Skips cleanly when tomorrow is not
      # a trading day (Fri/Sat eve).
      schedule = "18 19 * * *"
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
    roll-watchdog = {
      description = "Nudge when liquidity front-month leads the calendar ≥ 3 sessions"
      # 19:45 UTC weekdays — after compute-indicators (19:15) so the day's
      # OI/volume is in before comparing liquidity vs the roll calendar.
      schedule = "45 19 * * 1-5"
    }
    # Dual-track brief — ensemble side (Phase B daily cron + in-agent eve gate).
    # cc-ensemble-explainer enriches the ensemble row with LLM narrative right
    # after cc-ensemble-compute (19:18) and before cc-daily-analysis (19:20).
    # cc-compass-brief-ensemble uploads the new 7-section brief to Drive at 19:35,
    # after the explainer has written. Both run daily with the
    # is_eve_of_trading_day() gate (skip = exit 0 = Sentry success).
    ensemble-explainer = {
      description = "Ensemble brief LLM commentator (enriches ensemble row with eco/confidence/direction/conclusion)"
      schedule    = "25 19 * * *"
    }
    compass-brief-ensemble = {
      description = "Ensemble brief generator + Drive upload (7-section, J+4 horizon)"
      schedule    = "35 19 * * *"
    }
    publish-session = {
      description = "Dashboard publication gate — release the newest ready session (data + audio)"
      # Every 30 min across the evening→next-morning window: hours 20-23 (after
      # the last Phase-B job at 19:35) and 0-9 (overnight → 09:30 UTC). No-ops
      # until a session's data is complete AND its NotebookLM audio is present,
      # then stamps pl_session_release → the dashboard flips atomically the same
      # evening. Morning fallback (past display_date 09:00 UTC) releases data-
      # only so a late/absent audio never freezes the dashboard on yesterday.
      # Idempotent (a released session is never re-processed), so the ~28
      # runs/day are cheap. See docs/runbooks/session-publish-gate.md.
      schedule = "*/30 20-23,0-9 * * *"
    }
    intraday-monitor = {
      description = "Intraday delayed-price polling — S1/R1 invalidation alerts (Telegram)"
      # Every 15 min, 8-16 UTC weekdays — deliberately wide to cover both GMT
      # and BST regimes; the in-code London gate (09:30-16:55 Europe/London,
      # official ICE hours) trims out-of-session ticks as clean exit-0 skips.
      # ~29 in-session ticks/day, first-cross-only per (rule, session) — see
      # docs/user-stories/P1-intraday-threshold-alerts-telegram.md.
      schedule = "*/15 8-16 * * 1-5"
    }
    # Campaign 6 regime + judge — INERT shadow-compute bundled in a single job.
    # Regime (Layer-1+2, self-computing) writes pl_regime_shadow, then judge
    # (Layer-3 macro overlay, o4-mini LLM) reads regime + press + weather from
    # the DB and writes pl_judge_shadow. Neither ever writes a shared table.
    #
    # 19:50 UTC DAILY — moved from `40 19 * * 1-5` to Phase-B daily eve-gated
    # semantics (like brief-ensemble/press-review/meteo) so Sun eve fires for
    # Mon's session and weekend news drift can flow through judge before the
    # first Monday audio. The in-agent `phase_b_should_skip` cleanly exits 0
    # on Fri/Sat eve (non-eve-of-trading), Sentry cron monitor treats that as
    # success. Fires ~10 min after cc-compass-brief-ensemble (19:35 daily) —
    # the brief is still generated FIRST during shadow (unchanged, ensemble
    # decision); judge reads DB rows, not the brief file, so no timing race.
    #
    # F-graduation (post-eval, ≥30 sessions): brief-ensemble will move
    # downstream of this job to read regime + judge overlay. Rescheduling only.
    regime-brief = {
      # 5 min after cc-regime-shadow: the adapter row must exist before the
      # narrative can be attached to it (the writer fails loudly otherwise).
      description = "Regime+judge narrative + Drive brief (fr + en)"
      schedule    = "55 19 * * *"
    }
    regime-shadow = {
      description = "C6 regime + judge (Layer-3 overlay): inert shadow decisions → pl_regime_shadow + pl_judge_shadow"
      schedule    = "50 19 * * *"
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

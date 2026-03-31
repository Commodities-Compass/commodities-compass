# ==============================================================================
# Monitoring — Notification channel + alert policy
# ==============================================================================
#
# Uptime check requires a public URL — activated in Phase 4.1 when Cloud Run
# backend is deployed. For now we create the notification channel and a basic
# Cloud SQL alert so the monitoring infrastructure is ready.
# ==============================================================================

resource "google_monitoring_notification_channel" "email" {
  display_name = "CTO Email"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }

  depends_on = [google_project_service.required_apis["monitoring.googleapis.com"]]
}

# Alert when Cloud SQL instance is down (database/up metric = 0)
resource "google_monitoring_alert_policy" "cloudsql_down" {
  display_name = "Cloud SQL Instance Down"
  combiner     = "OR"

  conditions {
    display_name = "Cloud SQL cc-postgres is not running"

    condition_threshold {
      filter          = "resource.type = \"cloudsql_database\" AND resource.labels.database_id = \"${var.project_id}:cc-postgres\" AND metric.type = \"cloudsql.googleapis.com/database/up\""
      duration        = "300s"
      comparison      = "COMPARISON_LT"
      threshold_value = 1

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]

  alert_strategy {
    auto_close = "1800s"
  }

  depends_on = [google_sql_database_instance.main]
}

# Alert when any Cloud Run Job execution fails
resource "google_monitoring_alert_policy" "cloud_run_job_failure" {
  display_name = "Cloud Run Job Execution Failed"
  combiner     = "OR"

  conditions {
    display_name = "Cloud Run Job failed execution"

    condition_threshold {
      filter          = "resource.type = \"cloud_run_job\" AND metric.type = \"run.googleapis.com/job/completed_task_attempt_count\" AND metric.labels.result = \"failed\""
      duration        = "0s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["resource.label.job_name"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]

  documentation {
    content   = "A Cloud Run Job execution failed. Check logs: https://console.cloud.google.com/run/jobs?project=${var.project_id}"
    mime_type = "text/markdown"
  }

  alert_strategy {
    auto_close = "1800s"
  }
}

# Alert when backend Cloud Run service returns 5xx errors
resource "google_monitoring_alert_policy" "cloud_run_service_errors" {
  display_name = "Cloud Run Backend 5xx Errors"
  combiner     = "OR"

  conditions {
    display_name = "Backend returning server errors"

    condition_threshold {
      filter          = "resource.type = \"cloud_run_revision\" AND resource.labels.service_name = \"backend\" AND metric.type = \"run.googleapis.com/request_count\" AND metric.labels.response_code_class = \"5xx\""
      duration        = "0s"
      comparison      = "COMPARISON_GT"
      threshold_value = 5

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]

  documentation {
    content   = "Backend Cloud Run service is returning 5xx errors. Check logs: https://console.cloud.google.com/run/detail/europe-west9/backend/logs?project=${var.project_id}"
    mime_type = "text/markdown"
  }

  alert_strategy {
    auto_close = "1800s"
  }
}

# Uptime check — backend health endpoint
resource "google_monitoring_uptime_check_config" "backend_health" {
  display_name = "Backend Health Check"
  timeout      = "10s"
  period       = "300s"

  http_check {
    path         = "/health"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = "backend-229076583962.europe-west9.run.app"
    }
  }
}

resource "google_monitoring_alert_policy" "backend_uptime" {
  display_name = "Backend Health Check Failed"
  combiner     = "OR"

  conditions {
    display_name = "Backend /health is down"

    condition_threshold {
      filter          = "resource.type = \"uptime_url\" AND metric.type = \"monitoring.googleapis.com/uptime_check/check_passed\" AND metric.labels.check_id = \"${google_monitoring_uptime_check_config.backend_health.uptime_check_id}\""
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
    content   = "Backend /health endpoint is not responding. Check Cloud Run: https://console.cloud.google.com/run/detail/europe-west9/backend?project=${var.project_id}"
    mime_type = "text/markdown"
  }

  alert_strategy {
    auto_close = "1800s"
  }
}

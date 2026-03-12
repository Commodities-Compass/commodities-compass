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

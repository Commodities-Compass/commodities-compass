# ==============================================================================
# Secret Manager — empty shells + auto-computed DATABASE_URL
# ==============================================================================
#
# Strategy:
# - All secrets are created as empty shells (no secret version).
# - DATABASE_URL and DATABASE_SYNC_URL get auto-computed versions from
#   Cloud SQL outputs (password is already in TF state via random_password).
# - All other secrets are populated post-apply via:
#   gcloud secrets versions add SECRET_NAME --data-file=-
# ==============================================================================

resource "google_secret_manager_secret" "app_secrets" {
  for_each  = toset(var.secret_ids)
  secret_id = each.key

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  labels = var.labels

  depends_on = [google_project_service.required_apis["secretmanager.googleapis.com"]]
}

# Auto-computed: async connection string for FastAPI (asyncpg driver)
resource "google_secret_manager_secret_version" "database_url" {
  secret      = google_secret_manager_secret.app_secrets["DATABASE_URL"].id
  secret_data = "postgresql+asyncpg://${google_sql_user.app.name}:${random_password.db_password.result}@${google_sql_database_instance.main.private_ip_address}/${google_sql_database.app.name}"
}

# Auto-computed: sync connection string for Alembic migrations (psycopg2 driver)
resource "google_secret_manager_secret_version" "database_sync_url" {
  secret      = google_secret_manager_secret.app_secrets["DATABASE_SYNC_URL"].id
  secret_data = "postgresql+psycopg2://${google_sql_user.app.name}:${random_password.db_password.result}@${google_sql_database_instance.main.private_ip_address}/${google_sql_database.app.name}"
}

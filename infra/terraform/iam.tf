# ==============================================================================
# Service Accounts + IAM Bindings
# ==============================================================================
#
# Three SAs with distinct least-privilege roles:
# 1. cc-cloud-run-api   — runtime SA for backend + frontend Cloud Run services
# 2. cc-cloud-run-jobs  — runtime SA for scraper/agent/ETL Cloud Run Jobs
# 3. cc-github-actions  — CI/CD SA for GitHub Actions (via WIF, see wif.tf)
#
# The existing SA commodities-compass-sheets@cacaooo.iam.gserviceaccount.com
# is NOT managed by Terraform (pre-existing, Google Sheets access).
# ==============================================================================

# ---- Service Account: Cloud Run API (backend + frontend) ----

resource "google_service_account" "cloud_run_api" {
  account_id   = "cc-cloud-run-api"
  display_name = "Cloud Run API Service Account"
  description  = "Used by backend and frontend Cloud Run services"
}

resource "google_project_iam_member" "cloud_run_api_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

resource "google_project_iam_member" "cloud_run_api_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

resource "google_project_iam_member" "cloud_run_api_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

resource "google_project_iam_member" "cloud_run_api_metric_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

# ---- Service Account: Cloud Run Jobs (scrapers + agents + ETL) ----

resource "google_service_account" "cloud_run_jobs" {
  account_id   = "cc-cloud-run-jobs"
  display_name = "Cloud Run Jobs Service Account"
  description  = "Used by scraper, agent, and ETL Cloud Run Jobs"
}

resource "google_project_iam_member" "cloud_run_jobs_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.cloud_run_jobs.email}"
}

resource "google_project_iam_member" "cloud_run_jobs_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.cloud_run_jobs.email}"
}

resource "google_project_iam_member" "cloud_run_jobs_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.cloud_run_jobs.email}"
}

resource "google_project_iam_member" "cloud_run_jobs_metric_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.cloud_run_jobs.email}"
}

# ---- Service Account: GitHub Actions (CI/CD deploy) ----

resource "google_service_account" "github_actions" {
  account_id   = "cc-github-actions"
  display_name = "GitHub Actions Deploy"
  description  = "Used by GitHub Actions via Workload Identity Federation"
}

resource "google_project_iam_member" "github_actions_ar_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.github_actions.email}"
}

resource "google_project_iam_member" "github_actions_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.github_actions.email}"
}

resource "google_project_iam_member" "github_actions_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.github_actions.email}"
}

# GitHub Actions SA must be able to "act as" both runtime SAs when
# deploying Cloud Run services/jobs that specify them as runtime identity.
resource "google_service_account_iam_member" "github_actions_act_as_api" {
  service_account_id = google_service_account.cloud_run_api.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.github_actions.email}"
}

resource "google_service_account_iam_member" "github_actions_act_as_jobs" {
  service_account_id = google_service_account.cloud_run_jobs.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.github_actions.email}"
}

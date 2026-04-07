# ==============================================================================
# Outputs
# ==============================================================================

# ---- Networking ----

output "vpc_id" {
  description = "VPC network ID"
  value       = google_compute_network.vpc.id
}

output "vpc_connector_id" {
  description = "Serverless VPC Access connector ID (for Cloud Run --vpc-connector)"
  value       = google_vpc_access_connector.connector.id
}

# ---- Cloud SQL ----

output "cloudsql_instance_name" {
  description = "Cloud SQL instance name"
  value       = google_sql_database_instance.main.name
}

output "cloudsql_connection_name" {
  description = "Cloud SQL instance connection name (project:region:instance)"
  value       = google_sql_database_instance.main.connection_name
}

output "cloudsql_private_ip" {
  description = "Cloud SQL private IP address"
  value       = google_sql_database_instance.main.private_ip_address
  sensitive   = true
}

output "cloudsql_public_ip" {
  description = "Cloud SQL public IP (no authorized networks — use Auth Proxy)"
  value       = google_sql_database_instance.main.public_ip_address
}

# ---- Artifact Registry ----

output "artifact_registry_url" {
  description = "Artifact Registry Docker repository URL"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
}

# ---- Service Accounts ----

output "cloud_run_api_sa_email" {
  description = "Cloud Run API service account email"
  value       = google_service_account.cloud_run_api.email
}

output "cloud_run_jobs_sa_email" {
  description = "Cloud Run Jobs service account email"
  value       = google_service_account.cloud_run_jobs.email
}

output "github_actions_sa_email" {
  description = "GitHub Actions service account email"
  value       = google_service_account.github_actions.email
}

# ---- Workload Identity Federation ----

output "wif_provider_name" {
  description = "WIF provider resource name (set as GCP_WIF_PROVIDER in GitHub)"
  value       = google_iam_workload_identity_pool_provider.github.name
}

# ---- Load Balancer ----

output "lb_ip_address" {
  description = "Global Load Balancer static IP (set A records for app. and api. subdomains)"
  value       = google_compute_global_address.lb.address
}

# ---- GitHub Variables (copy into GitHub Settings → Variables) ----

output "github_vars" {
  description = "Values to set as GitHub repository variables for deploy.yml"
  value = {
    GCP_WIF_PROVIDER = google_iam_workload_identity_pool_provider.github.name
    GCP_SA_EMAIL     = google_service_account.github_actions.email
    GCP_PROJECT_ID   = var.project_id
    GCP_REGION       = var.region
  }
}

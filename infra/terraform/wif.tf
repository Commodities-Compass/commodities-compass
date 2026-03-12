# ==============================================================================
# Workload Identity Federation — GitHub Actions OIDC
# ==============================================================================
#
# Enables keyless authentication from GitHub Actions to GCP.
# No SA keys to rotate — GitHub's OIDC token is exchanged for a short-lived
# GCP access token at each workflow run.
#
# The attribute_condition restricts this to our specific repository.
# ==============================================================================

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions"
  description               = "Workload Identity Pool for GitHub Actions OIDC"
  project                   = var.project_id

  depends_on = [
    google_project_service.required_apis["iam.googleapis.com"],
    google_project_service.required_apis["sts.googleapis.com"],
    google_project_service.required_apis["iamcredentials.googleapis.com"],
  ]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"
  description                        = "GitHub Actions OIDC provider for ${var.github_org}/${var.github_repo}"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Restrict to our specific repository (case-sensitive)
  attribute_condition = "assertion.repository == '${var.github_org}/${var.github_repo}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Allow any workflow run from our repo to impersonate the GitHub Actions SA
resource "google_service_account_iam_member" "wif_github_actions" {
  service_account_id = google_service_account.github_actions.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_org}/${var.github_repo}"
}

# ==============================================================================
# Artifact Registry — Docker image repository
# ==============================================================================

resource "google_artifact_registry_repository" "docker" {
  location      = var.region
  repository_id = "commodities-compass"
  format        = "DOCKER"
  description   = "Docker images for Commodities Compass backend and frontend"

  cleanup_policies {
    id     = "keep-latest-10"
    action = "KEEP"

    most_recent_versions {
      keep_count = 10
    }
  }

  cleanup_policies {
    id     = "delete-untagged"
    action = "DELETE"

    condition {
      tag_state  = "UNTAGGED"
      older_than = "604800s"
    }
  }

  labels = var.labels

  depends_on = [google_project_service.required_apis["artifactregistry.googleapis.com"]]
}

# ==============================================================================
# Artifact Registry — Docker image repository
# ==============================================================================

resource "google_artifact_registry_repository" "docker" {
  location      = var.region
  repository_id = "commodities-compass"
  format        = "DOCKER"
  description   = "Docker images for Commodities Compass backend and frontend"

  # Cleanup policies are evaluated as a set: a version is deleted when it matches
  # any DELETE policy AND no KEEP policy. The previous config had only a KEEP and
  # an untagged-DELETE — no DELETE ever matched TAGGED images. Since CI tags every
  # push with the git SHA, all 534 versions since 2026-03-30 accumulated → ~296 GB,
  # making Artifact Registry Storage the #1 line item (€21.09 in June 2026).
  # The missing piece is `delete-old-versions`. See docs/gcp-cost-analysis/2026-06.md.
  #
  # dry_run = true → the FIRST `terraform apply` only LOGS what would be deleted
  # (Cloud Logging, resourceName ".../cleanupPolicies"). Validate the purge count,
  # then set this to false and re-apply to actually reclaim the storage.
  cleanup_policy_dry_run = true

  cleanup_policies {
    id     = "keep-minimum-versions"
    action = "KEEP"

    most_recent_versions {
      keep_count = 5
    }
  }

  cleanup_policies {
    id     = "delete-untagged"
    action = "DELETE"

    condition {
      tag_state  = "UNTAGGED"
      older_than = "604800s" # 7 days
    }
  }

  cleanup_policies {
    id     = "delete-old-versions"
    action = "DELETE"

    condition {
      older_than = "2592000s" # 30 days — purges old TAGGED images (the fix)
    }
  }

  labels = var.labels

  depends_on = [google_project_service.required_apis["artifactregistry.googleapis.com"]]
}

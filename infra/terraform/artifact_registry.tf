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
  # Policies are LIVE (dry_run = false). Validated 2026-07-07 before flipping:
  # the only image versions pinned by the 21 live Cloud Run workloads (backend,
  # frontend, jobs — all at the current main SHA) are rank #1-2 / 0-1 days old,
  # so they are doubly protected by `keep-minimum-versions` and the 30d threshold.
  # deploy.yml redeploys every workload on each main push, so nothing pins a stale
  # image. To re-validate a future policy change, set this back to true first.
  cleanup_policy_dry_run = false

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

# ==============================================================================
# Commodities Compass — GCP Infrastructure
# ==============================================================================
#
# NOTE: Cloud Run services are managed by GitHub Actions (deploy.yml), not
# Terraform. This is intentional — Terraform owns the platform (VPC, SQL,
# secrets, IAM), GitHub Actions owns the application lifecycle (build, push,
# deploy). Revisit in Phase 4.1 if Cloud Run needs VPC connector binding,
# Secret Manager env vars, or service-level Terraform management.
# ==============================================================================

terraform {
  required_version = ">= 1.7"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  backend "gcs" {
    bucket = "tf-state-cacaooo"
    prefix = "terraform/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# Ensure required APIs are enabled (idempotent).
# disable_on_destroy = false prevents Terraform from disabling APIs if a
# resource is removed from the for_each set — protects other services that
# depend on these APIs but are managed outside Terraform (e.g. Cloud Run).
resource "google_project_service" "required_apis" {
  for_each = toset([
    "compute.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "run.googleapis.com",
    "vpcaccess.googleapis.com",
    "servicenetworking.googleapis.com",
    "cloudscheduler.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "sts.googleapis.com",
    "monitoring.googleapis.com",
  ])

  project                    = var.project_id
  service                    = each.key
  disable_on_destroy         = false
  disable_dependent_services = false
}

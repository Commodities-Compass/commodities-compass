# ==============================================================================
# Variables
# ==============================================================================

# ---- Project ----

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "project_number" {
  description = "GCP project number (numeric)"
  type        = string
}

variable "region" {
  description = "GCP region for all resources"
  type        = string
}

# ---- VPC ----

variable "vpc_name" {
  description = "Name of the VPC network"
  type        = string
  default     = "cc-vpc"
}

variable "subnet_cidr" {
  description = "CIDR range for the main subnet"
  type        = string
  default     = "10.0.0.0/24"
}

variable "vpc_connector_cidr" {
  description = "CIDR range for the Serverless VPC Access connector (/28 required)"
  type        = string
  default     = "10.8.0.0/28"
}

# ---- Cloud Scheduler ----

variable "scheduler_region" {
  description = "Region for Cloud Scheduler (europe-west9 not supported, use nearest EU)"
  type        = string
  default     = "europe-west1"
}

# ---- Cloud SQL ----

variable "db_tier" {
  description = "Cloud SQL machine tier (db-f1-micro for dev, db-custom-1-3840 for prod)"
  type        = string
  default     = "db-f1-micro"
}

variable "db_name" {
  description = "PostgreSQL database name"
  type        = string
  default     = "commodities_compass"
}

variable "db_user" {
  description = "PostgreSQL application user name"
  type        = string
  default     = "cc_app"
}

# ---- GitHub (for WIF) ----

variable "github_org" {
  description = "GitHub organization name (case-sensitive)"
  type        = string
  default     = "Commodities-Compass"
}

variable "github_repo" {
  description = "GitHub repository name (case-sensitive)"
  type        = string
  default     = "commodities-compass"
}

# ---- Secrets ----

variable "secret_ids" {
  description = "Secret Manager secret IDs to create as empty shells"
  type        = list(string)
  default = [
    "AUTH0_DOMAIN",
    "AUTH0_CLIENT_ID",
    "AUTH0_API_AUDIENCE",
    "AUTH0_ISSUER",
    "DATABASE_URL",
    "DATABASE_SYNC_URL",
    "GOOGLE_SHEETS_CREDENTIALS_JSON",
    "GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON",
    "GOOGLE_DRIVE_CREDENTIALS_JSON",
    "SENTRY_DSN",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
  ]
}

# ---- Monitoring ----

variable "alert_email" {
  description = "Email address for monitoring alert notifications"
  type        = string
}

# ---- Labels ----

variable "labels" {
  description = "Common labels applied to all resources"
  type        = map(string)
  default = {
    project     = "commodities-compass"
    environment = "production"
    managed_by  = "terraform"
  }
}

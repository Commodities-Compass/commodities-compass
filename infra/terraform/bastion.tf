# ==============================================================================
# Bastion — IAP tunnel to Cloud SQL (private IP only)
# ==============================================================================
#
# Access path to the private Cloud SQL instance from developer machines. No
# public IP — all access goes through an IAP TCP tunnel.
#
# The bastion VM itself is EPHEMERAL and is NOT managed by Terraform (2026-08-03).
# `europe-west9-a` capacity is intermittently exhausted across machine families
# (t2d AND e2 have both failed to start there), so a single fixed-zone instance
# is fragile. Instead, `.local/db-prod.sh` CREATES the VM on demand, trying
# europe-west9 zones a→b→c until one has capacity, and DELETES it on teardown.
# This file keeps only the durable, zone-independent scaffolding the ephemeral
# VM relies on: its service account, IAM, and the IAP-SSH firewall rule (which
# targets tag "bastion" network-wide, so it applies in any zone).
#
# Usage:
#   ./.local/db-prod.sh up      # create bastion (first available zone) + tunnel :5434
#   ./.local/db-prod.sh psql    # psql against prod via the tunnel
#   ./.local/db-prod.sh down    # close tunnel + delete the VM
# ==============================================================================

resource "google_service_account" "bastion" {
  account_id   = "cc-bastion"
  display_name = "Bastion VM Service Account"
  description  = "Minimal SA for IAP bastion — logging only"
}

resource "google_project_iam_member" "bastion_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.bastion.email}"
}

# The bastion instance is created/destroyed on demand by .local/db-prod.sh
# (ephemeral, multi-zone) — deliberately NOT a google_compute_instance here.
# It boots as e2-small from cos-stable with tag "bastion", the SA above, the
# main subnet, no public IP, and shielded-VM enabled.

# --- Firewall: allow IAP to SSH into bastion ---

resource "google_compute_firewall" "allow_iap_ssh" {
  name    = "cc-allow-iap-ssh"
  network = google_compute_network.vpc.name

  direction = "INGRESS"
  priority  = 1000

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  # IAP's IP range — all IAP TCP tunnels originate from here
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["bastion"]

  log_config {
    metadata = "INCLUDE_ALL_METADATA"
  }
}

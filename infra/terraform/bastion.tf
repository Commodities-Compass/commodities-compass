# ==============================================================================
# Bastion VM — IAP tunnel to Cloud SQL (private IP only)
# ==============================================================================
#
# Zero-cost access path to the private Cloud SQL instance from developer
# machines. No public IP on the VM — all access goes through IAP TCP tunnel.
#
# Usage:
#   gcloud compute ssh cc-bastion --zone europe-west9-a --tunnel-through-iap \
#     --project cacaooo -- -N -L 5434:10.119.160.3:5432
#
#   psql -h 127.0.0.1 -p 5434 -U cc_app -d commodities_compass
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

resource "google_compute_instance" "bastion" {
  name         = "cc-bastion"
  machine_type = "e2-micro"
  zone         = "${var.region}-a"

  tags = ["bastion"]

  boot_disk {
    initialize_params {
      image = "projects/cos-cloud/global/images/family/cos-stable"
      size  = 10
      type  = "pd-standard"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.main.id
    # No access_config block = no public IP
  }

  service_account {
    email  = google_service_account.bastion.email
    scopes = ["logging-write"]
  }

  scheduling {
    preemptible       = false
    automatic_restart = true
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  labels = var.labels

  depends_on = [
    google_project_service.required_apis["compute.googleapis.com"],
    google_project_service.required_apis["iap.googleapis.com"],
  ]
}

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

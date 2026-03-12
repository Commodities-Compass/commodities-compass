# ==============================================================================
# VPC, Subnet, Private Services Access, Serverless VPC Access Connector
# ==============================================================================

# Custom VPC — no auto-created subnets, explicit control over CIDR ranges
resource "google_compute_network" "vpc" {
  name                    = var.vpc_name
  auto_create_subnetworks = false
  project                 = var.project_id

  depends_on = [google_project_service.required_apis["compute.googleapis.com"]]
}

# Subnet in europe-west9 (Paris)
resource "google_compute_subnetwork" "main" {
  name                     = "${var.vpc_name}-subnet"
  ip_cidr_range            = var.subnet_cidr
  region                   = var.region
  network                  = google_compute_network.vpc.id
  private_ip_google_access = true
}

# Private Services Access — allocate internal IP range for Google-managed
# services (Cloud SQL). /20 gives 4096 IPs, more than enough.
resource "google_compute_global_address" "private_ip_range" {
  name          = "cc-private-ip-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 20
  network       = google_compute_network.vpc.id
}

# Private Services Connection — peers Google's managed VPC with ours so
# Cloud SQL can receive a private IP on our network.
resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_range.name]

  depends_on = [google_project_service.required_apis["servicenetworking.googleapis.com"]]
}

# Serverless VPC Access connector — allows Cloud Run to reach resources
# on the private network (Cloud SQL private IP).
# min_throughput=200 (minimum allowed), max_throughput=300 for cost savings.
resource "google_vpc_access_connector" "connector" {
  provider      = google-beta
  name          = "cc-vpc-connector"
  region        = var.region
  ip_cidr_range = var.vpc_connector_cidr
  network       = google_compute_network.vpc.name

  min_throughput = 200
  max_throughput = 300

  depends_on = [google_project_service.required_apis["vpcaccess.googleapis.com"]]
}

# ── NETWORK MODULE ────────────────────────────────────────────────────────────
# Custom VPC + subnet with secondary ranges for GKE IP-aliasing (pods/services),
# plus Private Service Access so Cloud SQL (Phase 2) can have a private IP.
# ──────────────────────────────────────────────────────────────────────────────

variable "project_id" { type = string }
variable "region" { type = string }
variable "labels" { type = map(string) }

resource "google_compute_network" "vpc" {
  name                    = "sap-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "subnet" {
  name          = "sap-subnet"
  ip_cidr_range = "10.10.0.0/20"
  region        = var.region
  network       = google_compute_network.vpc.id

  private_ip_google_access = true

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.20.0.0/16"
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.30.0.0/20"
  }
}

# ── Private Service Access (for Cloud SQL private IP, used in Phase 2) ──────────
resource "google_compute_global_address" "psa_range" {
  name          = "sap-psa-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "psa" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.psa_range.name]
}

output "network_name" { value = google_compute_network.vpc.name }
output "network_self_link" { value = google_compute_network.vpc.self_link }
output "subnet_self_link" { value = google_compute_subnetwork.subnet.self_link }
output "pods_range_name" { value = "pods" }
output "services_range_name" { value = "services" }

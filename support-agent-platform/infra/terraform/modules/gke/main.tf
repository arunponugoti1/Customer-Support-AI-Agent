# ── GKE MODULE ────────────────────────────────────────────────────────────────
# Zonal GKE Standard cluster (zonal = cheaper for learning) with:
#  - Workload Identity (no key files in pods)
#  - IP-aliasing using the network module's secondary ranges
#  - a CPU node pool with autoscaling and a least-privilege node service account
# Layer 1 later adds a GPU node pool to THIS cluster.
# ──────────────────────────────────────────────────────────────────────────────

variable "project_id" { type = string }
variable "zone" { type = string }
variable "network" { type = string }
variable "subnetwork" { type = string }
variable "pods_range" { type = string }
variable "svc_range" { type = string }
variable "machine_type" { type = string }
variable "min_nodes" { type = number }
variable "max_nodes" { type = number }
variable "labels" { type = map(string) }

# Least-privilege service account the nodes run as.
resource "google_service_account" "node_sa" {
  account_id   = "sap-gke-node"
  display_name = "Support Agent GKE node SA"
}

resource "google_project_iam_member" "node_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.node_sa.email}"
}

resource "google_project_iam_member" "node_metrics" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.node_sa.email}"
}

resource "google_project_iam_member" "node_artifact_pull" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.node_sa.email}"
}

resource "google_container_cluster" "this" {
  name     = "sap-cluster"
  location = var.zone # zonal cluster = fewer nodes = cheaper

  # Manage node pools separately (best practice): drop the default pool.
  remove_default_node_pool = true
  initial_node_count       = 1

  network    = var.network
  subnetwork = var.subnetwork

  release_channel {
    channel = "REGULAR"
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  ip_allocation_policy {
    cluster_secondary_range_name  = var.pods_range
    services_secondary_range_name = var.svc_range
  }

  # Shielded nodes for a security baseline.
  enable_shielded_nodes = true

  deletion_protection = false # learning project — allow terraform destroy
}

resource "google_container_node_pool" "cpu" {
  name     = "cpu-pool"
  cluster  = google_container_cluster.this.id
  location = var.zone

  autoscaling {
    min_node_count = var.min_nodes
    max_node_count = var.max_nodes
  }

  node_config {
    machine_type    = var.machine_type
    service_account = google_service_account.node_sa.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    labels          = var.labels

    workload_metadata_config {
      mode = "GKE_METADATA" # required for Workload Identity
    }

    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }

    metadata = {
      disable-legacy-endpoints = "true"
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}

output "cluster_name" { value = google_container_cluster.this.name }
output "node_service_account" { value = google_service_account.node_sa.email }

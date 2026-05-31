# ─────────────────────────────────────────────────────────────────────────────
# BOOTSTRAP — creates the GCS bucket that holds Terraform remote state.
# Run this ONCE, with LOCAL state, before the main stack.
#   cd infra/terraform/bootstrap
#   terraform init && terraform apply -var="project_id=YOUR_PROJECT" \
#       -var="state_bucket=YOUR_PROJECT-tfstate"
# Then put that bucket name into ../backend.tf and run the main stack.
# (Manual exception by design: state backend must exist before remote state.)
# ─────────────────────────────────────────────────────────────────────────────

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "us-central1"
}
variable "state_bucket" { type = string }

provider "google" {
  project = var.project_id
  region  = var.region
}

# The storage API must be on to create the bucket. Enable it here so bootstrap
# is self-contained even on a fresh project.
resource "google_project_service" "storage" {
  service            = "storage.googleapis.com"
  disable_on_destroy = false
}

resource "google_storage_bucket" "tfstate" {
  name                        = var.state_bucket
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = true
  }

  # Keep a few old state versions, drop the rest.
  lifecycle_rule {
    condition {
      num_newer_versions = 10
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.storage]
}

output "state_bucket" {
  value = google_storage_bucket.tfstate.name
}

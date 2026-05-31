terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region

  # Some APIs (e.g. billingbudgets) require a quota/billing project to be sent
  # explicitly when using user ADC. Without these, the provider falls back to
  # Google's default project and the call is rejected.
  billing_project       = var.project_id
  user_project_override = true
}

# ── REGISTRY MODULE ───────────────────────────────────────────────────────────
# Artifact Registry Docker repo for all service images, with vuln scanning.
# ──────────────────────────────────────────────────────────────────────────────

variable "project_id" { type = string }
variable "region" { type = string }
variable "labels" { type = map(string) }

resource "google_artifact_registry_repository" "docker" {
  location      = var.region
  repository_id = "sap-images"
  description   = "Support Agent Platform container images"
  format        = "DOCKER"
  labels        = var.labels
}

output "repo_url" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
}

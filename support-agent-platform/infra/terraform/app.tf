# ─────────────────────────────────────────────────────────────────────────────
# APP WORKLOAD IDENTITY — a Google service account the application pods act as,
# bound to a Kubernetes service account via Workload Identity (no key files).
# Grants: call Vertex AI, connect to Cloud SQL, read app secrets.
# ─────────────────────────────────────────────────────────────────────────────

variable "app_namespace" {
  type        = string
  description = "Kubernetes namespace the app runs in."
  default     = "support-agent"
}

variable "app_ksa" {
  type        = string
  description = "Kubernetes service account name the app pods use."
  default     = "sap-app"
}

resource "google_service_account" "app" {
  account_id   = "sap-app"
  display_name = "Support Agent Platform app SA (Workload Identity)"
}

locals {
  app_roles = [
    "roles/aiplatform.user",              # call Vertex AI / Gemini
    "roles/cloudsql.client",              # connect to Cloud SQL
    "roles/secretmanager.secretAccessor", # read db-password / vertex creds
    "roles/cloudtrace.agent",             # write traces (Phase 3)
    "roles/monitoring.metricWriter",      # emit custom metrics
  ]
}

resource "google_project_iam_member" "app" {
  for_each = toset(local.app_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.app.email}"
}

# Let the Kubernetes SA [namespace/ksa] impersonate the Google SA.
resource "google_service_account_iam_member" "app_wi" {
  service_account_id = google_service_account.app.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.app_namespace}/${var.app_ksa}]"
}

output "app_gsa_email" {
  value = google_service_account.app.email
}

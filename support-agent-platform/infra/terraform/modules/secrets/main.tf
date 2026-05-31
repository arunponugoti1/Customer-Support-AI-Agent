# ── SECRETS MODULE ────────────────────────────────────────────────────────────
# Creates the Secret Manager *containers*. Secret VALUES are added out-of-band
# (the documented manual exception) so they never live in Terraform state or git:
#   echo -n "$VALUE" | gcloud secrets versions add SECRET_NAME --data-file=-
# ──────────────────────────────────────────────────────────────────────────────

variable "project_id" { type = string }
variable "region" { type = string }
variable "labels" { type = map(string) }

locals {
  secret_names = [
    "vertex-credentials", # service-account JSON or config for Vertex (added manually)
    "db-password",        # Cloud SQL app user password (Phase 2)
  ]
}

resource "google_secret_manager_secret" "this" {
  for_each  = toset(local.secret_names)
  secret_id = each.value
  labels    = var.labels

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
}

output "secret_ids" {
  value = [for s in google_secret_manager_secret.this : s.secret_id]
}

output "db_password_secret_id" {
  value = google_secret_manager_secret.this["db-password"].id
}

output "vertex_credentials_secret_id" {
  value = google_secret_manager_secret.this["vertex-credentials"].id
}

# ── PROJECT MODULE ────────────────────────────────────────────────────────────
# Enables the APIs the platform needs, and sets a hard billing budget + alert.
# Project itself already exists (created out-of-band).
# ──────────────────────────────────────────────────────────────────────────────

variable "project_id" { type = string }
variable "billing_account" { type = string }
variable "monthly_budget_amount" { type = number }
variable "budget_currency_code" { type = string }
variable "budget_alert_emails" { type = list(string) }

locals {
  apis = [
    "compute.googleapis.com",
    "container.googleapis.com",         # GKE
    "artifactregistry.googleapis.com",  # Docker images
    "secretmanager.googleapis.com",     # secrets
    "sqladmin.googleapis.com",          # Cloud SQL (pgvector) — used Phase 2
    "servicenetworking.googleapis.com", # private services access for Cloud SQL
    "aiplatform.googleapis.com",        # Vertex AI / Gemini
    "cloudbuild.googleapis.com",        # CI/CD
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "cloudtrace.googleapis.com", # distributed tracing
    "iamcredentials.googleapis.com",
    "billingbudgets.googleapis.com",
  ]
}

resource "google_project_service" "enabled" {
  for_each           = toset(local.apis)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false # don't rip APIs out from under other resources on destroy
}

# Look up the project NUMBER — the budget filter requires projects/{number}, not the ID.
data "google_project" "this" {
  project_id = var.project_id
}

# Hard budget + alert — Bible rule: never let spend run away (line 135).
resource "google_billing_budget" "monthly" {
  billing_account = var.billing_account
  display_name    = "support-agent-platform-monthly"

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }

  amount {
    specified_amount {
      currency_code = var.budget_currency_code
      units         = tostring(var.monthly_budget_amount)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }

  dynamic "all_updates_rule" {
    for_each = length(var.budget_alert_emails) > 0 ? [1] : []
    content {
      monitoring_notification_channels = [for c in google_monitoring_notification_channel.email : c.id]
      disable_default_iam_recipients   = false
    }
  }

  depends_on = [google_project_service.enabled]
}

resource "google_monitoring_notification_channel" "email" {
  for_each     = toset(var.budget_alert_emails)
  project      = var.project_id
  display_name = "budget-alert-${each.value}"
  type         = "email"
  labels = {
    email_address = each.value
  }
  depends_on = [google_project_service.enabled]
}

output "enabled_apis" {
  value = keys(google_project_service.enabled)
}

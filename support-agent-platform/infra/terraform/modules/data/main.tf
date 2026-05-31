# ── DATA MODULE ───────────────────────────────────────────────────────────────
# Cloud SQL for PostgreSQL with PRIVATE IP (reachable from GKE pods over the VPC),
# an app database + user. Password is generated here and stored as a new version
# of the existing Secret Manager secret (never in code/state output).
# pgvector is enabled later via a one-off migration (CREATE EXTENSION vector).
# ──────────────────────────────────────────────────────────────────────────────

variable "project_id" { type = string }
variable "region" { type = string }
variable "network_self_link" { type = string }
variable "db_secret_id" { type = string } # full id of the db-password secret
variable "db_tier" {
  type    = string
  default = "db-f1-micro" # smallest/cheapest shared-core — fine for learning
}
variable "labels" { type = map(string) }

resource "random_password" "db" {
  length  = 24
  special = false # keep it URL/connection-string safe
}

# Store the generated password as a new version of the existing secret.
resource "google_secret_manager_secret_version" "db_password" {
  secret      = var.db_secret_id
  secret_data = random_password.db.result
}

resource "google_sql_database_instance" "pg" {
  name             = "sap-pg"
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier              = var.db_tier
    availability_type = "ZONAL" # single-zone = cheaper for a learning project
    disk_size         = 10
    disk_autoresize   = true
    user_labels       = var.labels

    ip_configuration {
      ipv4_enabled    = false # private IP only — no public exposure
      private_network = var.network_self_link
    }

    backup_configuration {
      enabled = true
    }
  }

  # Allow terraform destroy on a learning project.
  deletion_protection = false
}

resource "google_sql_database" "app" {
  name     = "appdb"
  instance = google_sql_database_instance.pg.name
}

resource "google_sql_user" "app" {
  name     = "appuser"
  instance = google_sql_database_instance.pg.name
  password = random_password.db.result
}

output "instance_name" { value = google_sql_database_instance.pg.name }
output "private_ip" { value = google_sql_database_instance.pg.private_ip_address }
output "connection_name" { value = google_sql_database_instance.pg.connection_name }
output "db_name" { value = google_sql_database.app.name }
output "db_user" { value = google_sql_user.app.name }

# ─────────────────────────────────────────────────────────────────────────────
# ROOT STACK — wires the Phase 1 modules together.
# Order: APIs/budget → network → GKE → registry → secrets.
# ─────────────────────────────────────────────────────────────────────────────

module "project" {
  source = "./modules/project"

  project_id            = var.project_id
  billing_account       = var.billing_account
  monthly_budget_amount = var.monthly_budget_amount
  budget_currency_code  = var.budget_currency_code
  budget_alert_emails   = var.budget_alert_emails
}

module "network" {
  source = "./modules/network"

  project_id = var.project_id
  region     = var.region
  labels     = var.labels

  # Don't build the network until APIs are on.
  depends_on = [module.project]
}

module "gke" {
  source = "./modules/gke"

  project_id   = var.project_id
  zone         = var.zone
  network      = module.network.network_self_link
  subnetwork   = module.network.subnet_self_link
  pods_range   = module.network.pods_range_name
  svc_range    = module.network.services_range_name
  machine_type = var.gke_node_machine_type
  min_nodes    = var.gke_min_nodes
  max_nodes    = var.gke_max_nodes
  labels       = var.labels

  depends_on = [module.project]
}

module "registry" {
  source = "./modules/registry"

  project_id = var.project_id
  region     = var.region
  labels     = var.labels

  depends_on = [module.project]
}

module "secrets" {
  source = "./modules/secrets"

  project_id = var.project_id
  region     = var.region
  labels     = var.labels

  depends_on = [module.project]
}

module "data" {
  source = "./modules/data"

  project_id        = var.project_id
  region            = var.region
  network_self_link = module.network.network_self_link
  db_secret_id      = module.secrets.db_password_secret_id
  labels            = var.labels

  # Cloud SQL private IP needs the PSA connection (module.network) + APIs.
  depends_on = [module.project, module.network, module.secrets]
}

variable "project_id" {
  type        = string
  description = "Existing GCP project ID (already created)."
}

variable "region" {
  type        = string
  description = "Region for regional resources (registry, network, Vertex)."
  default     = "us-central1"
}

variable "zone" {
  type        = string
  description = "Zone for the (cost-saving) zonal GKE cluster."
  default     = "us-central1-a"
}

variable "billing_account" {
  type        = string
  description = "Billing account ID (e.g. 0X0X0X-0X0X0X-0X0X0X) for the budget alert."
}

variable "monthly_budget_amount" {
  type        = number
  description = "Hard budget ceiling (in budget_currency_code) for the alert. Bible rule: never let it run away."
  default     = 4000
}

variable "budget_currency_code" {
  type        = string
  description = "Must match the billing account currency (this account is INR)."
  default     = "INR"
}

variable "budget_alert_emails" {
  type        = list(string)
  description = "Emails to notify at budget thresholds. Leave empty to skip email channel."
  default     = []
}

variable "gke_node_machine_type" {
  type        = string
  description = "CPU node machine type. e2-standard-2 = 2 vCPU / 8GB."
  default     = "e2-standard-2"
}

variable "gke_min_nodes" {
  type    = number
  default = 1
}

variable "gke_max_nodes" {
  type    = number
  default = 3
}

variable "labels" {
  type        = map(string)
  description = "Common labels applied to resources."
  default = {
    project = "support-agent-platform"
    layer   = "layer3"
    managed = "terraform"
  }
}

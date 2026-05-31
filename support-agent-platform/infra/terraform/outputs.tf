output "gke_cluster_name" {
  value       = module.gke.cluster_name
  description = "Name of the GKE cluster."
}

output "gke_get_credentials_cmd" {
  value       = "gcloud container clusters get-credentials ${module.gke.cluster_name} --zone ${var.zone} --project ${var.project_id}"
  description = "Run this to point kubectl at the cluster."
}

output "artifact_registry_repo" {
  value       = module.registry.repo_url
  description = "Docker image push/pull base URL."
}

output "network_name" {
  value = module.network.network_name
}

output "secret_ids" {
  value       = module.secrets.secret_ids
  description = "Secret Manager secret names (add versions out-of-band)."
}

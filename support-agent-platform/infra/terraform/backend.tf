# Remote state in the GCS bucket created by ./bootstrap.
# After running bootstrap, set `bucket` to the name you chose, then `terraform init`.
terraform {
  backend "gcs" {
    bucket = "gke-ai-platform-tfstate"
    prefix = "support-agent-platform/phase1"
  }
}

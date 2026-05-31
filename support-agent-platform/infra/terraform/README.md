# Phase 1 — Platform Foundation (Terraform)

Provisions the reproducible base for the Support Agent Platform:
**APIs + billing budget → VPC → GKE (CPU) → Artifact Registry → Secret Manager.**

No GPU. The model is managed Vertex AI (Gemini); this infra is CPU-only.

## Prerequisites (the documented manual exceptions)
- An **existing GCP project** (you have this) with **billing linked**.
- `gcloud` authenticated: `gcloud auth login` and `gcloud auth application-default login`.
- Terraform >= 1.6.

## One-time: create the state bucket
```bash
cd bootstrap
terraform init
terraform apply -var="project_id=YOUR_PROJECT" -var="state_bucket=YOUR_PROJECT-tfstate"
cd ..
```
Put that bucket name into `backend.tf` (`bucket = "YOUR_PROJECT-tfstate"`).

## Apply the platform
```bash
cp terraform.tfvars.example terraform.tfvars   # then edit real values
terraform init      # connects to the GCS backend
terraform plan      # review — should create APIs, VPC, GKE, registry, secrets
terraform apply
```

## Connect kubectl
```bash
# Terraform prints the exact command as an output:
terraform output -raw gke_get_credentials_cmd | bash
kubectl get nodes
```

## Add secret values (out-of-band, never in git/state)
```bash
gcloud secrets versions add vertex-credentials --data-file=path/to/sa.json
echo -n "STRONG_PASSWORD" | gcloud secrets versions add db-password --data-file=-
```

## Cost discipline (Bible rule: never leave it idle)
```bash
terraform destroy   # tears the whole platform down — meter off
```
Re-run `terraform apply` next session. A billing budget + alert (default $50/mo) is
provisioned by the `project` module; you'll get emails at 50/90/100%.

## What this does NOT include yet (later phases)
- Cloud SQL + pgvector (Phase 2) — network already has Private Service Access ready.
- Helm charts / services / frontend (Phases 2–5).
- Managed Prometheus/Grafana wiring (Phase 5).

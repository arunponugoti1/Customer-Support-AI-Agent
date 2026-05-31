# Phase 1 — Deploy the hello-world service (prove the loop)

Goal: build the image → push to Artifact Registry → Helm-deploy to GKE → reach it.
This validates the whole platform pipeline before any real service exists.

Prereqs: Phase 1 Terraform applied (cluster + registry exist), `kubectl`, `helm`, `docker`.

```powershell
# 0. Variables
$REPO = "us-central1-docker.pkg.dev/gke-ai-platform/sap-images"
$IMG  = "$REPO/hello:0.1.0"

# 1. Point kubectl at the cluster (Terraform prints this exact command)
gcloud container clusters get-credentials sap-cluster --zone us-central1-a --project gke-ai-platform

# 2. Let Docker auth to Artifact Registry
gcloud auth configure-docker us-central1-docker.pkg.dev

# 3. Build & push the image
docker build -t $IMG services/hello
docker push $IMG

# 4. Deploy with Helm
helm upgrade --install hello deploy/helm/hello `
  --set image.repository="$REPO/hello" `
  --set image.tag=0.1.0

# 5. Wait for the LoadBalancer IP, then hit it
kubectl get svc hello-hello -w        # wait for EXTERNAL-IP
# curl http://EXTERNAL-IP/            and  /healthz
```

When `GET /` returns the JSON greeting with the pod/node name, Phase 1 is proven:
reproducible infra (Terraform) + containerized app (Docker) + declarative deploy (Helm) on GKE.

## CI later
This manual sequence becomes a Cloud Build / GitHub Actions pipeline in a later phase
(lint → test → build → scan → push → `helm upgrade`). No manual steps in steady state.

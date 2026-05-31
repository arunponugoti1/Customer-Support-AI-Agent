# Phase 5 — Frontend UI (single pane) + observability

## 5a — Next.js console (DONE)

`services/frontend` — a **Next.js (App Router)** app that is the single pane of glass. The
browser only talks to this app; its **same-origin `/api/*` route handlers** run server-side
inside the cluster and proxy to the internal ClusterIP services, so agent / approval /
llm-proxy stay private and there's no CORS.

Tabs:
- **Handle ticket** — submit a ticket, see intent, the node/tool **flow**, drafted reply,
  retrieved FAQ, per-ticket cost, trace id, and the approval banner for high-risk tickets.
- **Approvals** — the pending queue with Approve / Reject (consumes the approval `/actions` API).
- **Costs** — totals + cost-per-ticket (from llm-proxy `/costs/summary`).

`/api/*` proxy map (env-configurable, defaults to cluster DNS):
| route | → backend |
|---|---|
| `POST /api/handle` | `agent /handle` |
| `GET /api/actions[?status=]` | `approval /actions` |
| `POST /api/actions/{id}/approve\|reject` | `approval /actions/{id}/...` |
| `GET /api/costs` | `llm-proxy /costs/summary` |
| `GET /api/healthz` | self (probe) |

### Build + deploy (ClusterIP)

```powershell
$REPO = "us-central1-docker.pkg.dev/gke-ai-platform/sap-images"
gcloud builds submit services/frontend --tag "$REPO/frontend:0.1.0" --project gke-ai-platform
helm upgrade --install frontend deploy/helm/frontend -n support-agent `
  --set image.repository="$REPO/frontend" --set image.tag=0.1.0
kubectl rollout status deploy/frontend-frontend -n support-agent
```

### Test (port-forward — until the public Ingress is wired)

```powershell
kubectl port-forward -n support-agent svc/frontend-frontend 8080:80
# Browser: http://localhost:8080  → Handle a ticket, approve it in Approvals, watch Costs.
```

Notes:
- Image is multi-stage Next.js **standalone**, runs **non-root** with read-only rootfs
  (+ a small `/tmp` emptyDir). `next` pinned to a patched `14.2.35`.
- `.gcloudignore` keeps `node_modules` / `.next` out of the Cloud Build upload.

## 5a-ingress — public HTTPS (DONE) → https://llm-agent.duckdns.org

Approach: **ingress-nginx + cert-manager + Let's Encrypt** on a free **DuckDNS** subdomain.
Live, browser-trusted (Let's Encrypt prod cert, 90-day). HTTP 308-redirects to HTTPS.

Exact steps used:

```powershell
# 1. repos + ingress-nginx (creates a LoadBalancer -> external IP)
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo add jetstack https://charts.jetstack.io ; helm repo update
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx `
  --namespace ingress-nginx --create-namespace --set controller.service.type=LoadBalancer
$LB = kubectl get svc ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
#   -> 35.224.246.248 (this run)

# 2. cert-manager (with CRDs)
helm upgrade --install cert-manager jetstack/cert-manager `
  --namespace cert-manager --create-namespace --set crds.enabled=true

# 3. point DuckDNS at the LB IP (token is a secret — keep it out of the repo)
curl "https://www.duckdns.org/update?domains=llm-agent&token=<TOKEN>&ip=$LB"   # -> OK

# 4. issuers (kept in repo)
kubectl apply -f deploy/cert-manager/clusterissuers.yaml

# 5. enable the Ingress — validate with staging, then prod
helm upgrade frontend deploy/helm/frontend -n support-agent --reuse-values `
  --set ingress.enabled=true --set ingress.className=nginx `
  --set ingress.host=llm-agent.duckdns.org --set ingress.clusterIssuer=letsencrypt-staging
kubectl wait --for=condition=Ready certificate/frontend-tls -n support-agent --timeout=180s
# then prod (force re-issue):
helm upgrade frontend deploy/helm/frontend -n support-agent --reuse-values --set ingress.clusterIssuer=letsencrypt-prod
kubectl delete certificate frontend-tls -n support-agent ; kubectl delete secret frontend-tls -n support-agent
kubectl wait --for=condition=Ready certificate/frontend-tls -n support-agent --timeout=180s
```

Verify: `curl https://llm-agent.duckdns.org/api/healthz` (no `-k`), and
`echo | openssl s_client -connect llm-agent.duckdns.org:443 | openssl x509 -noout -issuer -dates`.

The chart's `templates/ingress.yaml` is gated behind `ingress.enabled` (default false),
parameterized on host / className / clusterIssuer / tlsSecretName.

> **Fragile-IP caveat:** the nginx LB IP is *ephemeral*. If the cluster/LB is recreated
> (e.g. after `terraform destroy`), the IP changes and the DuckDNS A record must be re-set
> (step 3). To make it permanent, reserve a global/regional static IP and pin the controller
> service to it — a hardening follow-up.

> **IaC follow-up:** ingress-nginx + cert-manager were installed via `helm` CLI (declarative,
> repeatable). Codifying them into Terraform's `helm` provider is a noted hardening step.

## 5b — observability (LATER)
Prometheus + Grafana dashboards + alerts (cost-per-task ceiling, error rate, latency). The
proxy already emits `/metrics`; the approval service emits `approval_actions_total`.

## Cost discipline
GKE + Cloud SQL bill continuously; ingress-nginx adds one LoadBalancer (another billed IP)
once enabled. `terraform destroy` when idle.

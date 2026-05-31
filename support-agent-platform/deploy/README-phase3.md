# Phase 3 — Orchestration, tools, distributed tracing

Goal: turn the linear Phase 2 flow into a **multi-step, intent-routed agent with tools**,
and make **every decision visible in one Cloud Trace**.

What changed vs Phase 2:
- **Tools** (in `agent`): `get_order_status` (mock OMS lookup), `issue_refund` (a STUB that
  returns `blocked` — it refuses to fire without an approval record; this is the Phase 4 hook),
  and `escalate`.
- **Intent-driven routing** in the LangGraph:
  ```
  classify ─┬─ order_status ─▶ lookup ─▶ retrieve ─▶ compose ─┐
            └─ else ───────────────────▶ retrieve ─▶ compose ─┤
  compose  ─┬─ refund / cancellation ─▶ gate (issue_refund BLOCKS + escalate) ─▶ END
            └─ else ──────────────────────────────────────────────────────────▶ END
  ```
- **OpenTelemetry → Cloud Trace** in *both* services. FastAPI + `requests` are auto-instrumented,
  so the `agent → llm-proxy` HTTP hop propagates W3C trace context and the proxy's spans nest
  under the agent's trace. Each graph node, each tool call, and each Vertex model/embed call is
  its own span. The real trace id (hex) is returned in `/handle` and shown in the test UI.

No Terraform changes: `roles/cloudtrace.agent` is already bound to the `sap-app` GSA (`app.tf`).

> Images are built with **Cloud Build** (`gcloud builds submit`), not local Docker — same as Phase 2.

## 0. Prereqs (cluster + Cloud SQL must be up)

```powershell
# If you ran `terraform destroy` to stop the meter, bring it back first:
#   cd infra/terraform; terraform apply
gcloud container clusters get-credentials sap-cluster --zone us-central1-a --project gke-ai-platform
$REPO = "us-central1-docker.pkg.dev/gke-ai-platform/sap-images"
$DB   = (terraform -chdir=infra/terraform output -raw db_private_ip)   # or reuse the known IP 10.104.0.3
```

## 1. Build the 0.2.0 images (Cloud Build)

```powershell
gcloud builds submit services/llm-proxy --tag "$REPO/llm-proxy:0.2.0" --project gke-ai-platform
gcloud builds submit services/agent     --tag "$REPO/agent:0.2.0"     --project gke-ai-platform
```

## 2. Deploy with Helm (proxy first, then agent)

```powershell
helm upgrade --install llm-proxy deploy/helm/llm-proxy `
  --namespace support-agent --create-namespace `
  --set image.repository="$REPO/llm-proxy" --set image.tag=0.2.0 `
  --set env.dbHost=$DB

helm upgrade --install agent deploy/helm/agent `
  --namespace support-agent `
  --set image.repository="$REPO/agent" --set image.tag=0.2.0 `
  --set env.dbHost=$DB

kubectl rollout status deploy/llm-proxy-llm-proxy -n support-agent
kubectl rollout status deploy/agent-agent        -n support-agent
```

## 3. Drive it + verify the trace

```powershell
kubectl port-forward -n support-agent svc/agent-agent 8089:80
# Browser: http://localhost:8089  — try the seeded refund ticket and an order-status ticket.
```

Two tickets that exercise both paths:

| Ticket | Expected route | Expected outcome |
|---|---|---|
| `My order #4471 hasn't arrived and I want a refund.` | classify→retrieve→compose→**gate** | `requires_approval=true`, `action=escalated`, refund tool `blocked` |
| `Where is my order #4471? What's the status?` | classify→**lookup**→retrieve→compose | `order_info` populated from `get_order_status`, no gate |

cURL equivalent:
```powershell
curl -s -X POST http://localhost:8089/handle -H "Content-Type: application/json" `
  -d '{"ticket":"Where is my order #4471? What is the status?"}'
```
The response now includes `trace_id` (32-hex), `order_info`, `action`, `requires_approval`, and
per-node `steps` (including the tool calls).

**Cloud Trace:** open
`https://console.cloud.google.com/traces/list?project=gke-ai-platform`, or jump straight to the
ticket's trace:
`https://console.cloud.google.com/traces/list?project=gke-ai-platform&tid=<trace_id>`
You should see one trace spanning both services:
```
POST /handle (support-agent)
 ├─ node.classify
 │   └─ POST /generate (llm-proxy)  →  vertex.chat.completions
 ├─ node.lookup            (order_status path)
 │   └─ tool.get_order_status
 ├─ node.retrieve
 │   └─ POST /embed (llm-proxy)     →  vertex.embeddings
 ├─ node.compose
 │   └─ POST /generate (llm-proxy)  →  vertex.chat.completions
 └─ node.gate              (refund/cancellation path)
     ├─ tool.issue_refund   (status=blocked)
     └─ tool.escalate
```

Cost still aggregates per ticket via the proxy:
```powershell
kubectl port-forward -n support-agent svc/llm-proxy-llm-proxy 8088:80
curl -s http://localhost:8088/costs/summary
```

## ✅ Phase 3 done when
- An order-status ticket calls the `get_order_status` tool and the lookup result shows in the draft.
- A refund/cancellation ticket hits the **gate**: `issue_refund` returns `blocked` and the ticket is
  `escalated` — nothing risky auto-fires.
- One Cloud Trace per ticket spans **both** services with node + tool + model spans.

## Cost discipline
GKE + Cloud SQL bill continuously. `terraform destroy` (in `infra/terraform`) when you stop working;
`terraform apply` to rebuild, then re-run steps 1–2 (images persist in Artifact Registry, so a rebuild
is only needed when code changes).

## Next: Phase 4 — human approval gate
The `gate` node + `issue_refund`'s `blocked` status are the seams. Phase 4 adds the approval service:
persist a `pending` action (Postgres), a human approve/reject UI, and make `issue_refund` succeed
*only* against an approved record. Audit log included.

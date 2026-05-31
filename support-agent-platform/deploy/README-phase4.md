# Phase 4 — Safety: human approval gate + sandboxing

Goal: **100% of refunds/cancellations stop for a human; nothing risky auto-fires.**

What changed vs Phase 3:
- **New `approval` service** (`services/approval`, chart `deploy/helm/approval`) — a FastAPI
  HITL gate that owns two tables in Postgres: `pending_actions` and `audit_log`.
  - `POST /actions` — create a **pending** action (called by the agent's gate).
  - `GET /actions[?status=pending]`, `GET /actions/{id}` — the queue + one action with its audit trail.
  - `POST /actions/{id}/approve` — approve **and execute** (the only code path that runs a refund;
    it asserts the row is `approved` first). `POST /actions/{id}/reject`.
  - `GET /` — browser approval queue (approve / reject buttons).
- **The sandbox:** the agent no longer has any refund capability. Its `gate` node only
  `POST`s a pending action and stops. A refund/cancellation can be executed **only** by the
  approval service, and **only** against a record a human approved. State machine:
  `pending → approved → executed` (or `→ rejected`, or `→ failed`).
- **Audit log:** every transition (`created`, `approved`, `rejected`, `executed`) is appended
  to `audit_log` with actor + timestamp + detail.
- Tracing carries through: the agent→approval `POST /actions` hop is in the same Cloud Trace
  as the ticket.

No Terraform change: the approval service reuses the `sap-app` Workload Identity (it already
has `cloudsql.client` + `secretmanager.secretAccessor` + `cloudtrace.agent`).

Images: **approval `0.1.0`** (new), **agent `0.3.0`** (gate now calls approval). llm-proxy stays `0.2.0`.

## 1. Build (Cloud Build)

```powershell
$REPO = "us-central1-docker.pkg.dev/gke-ai-platform/sap-images"
gcloud builds submit services/approval --tag "$REPO/approval:0.1.0" --project gke-ai-platform
gcloud builds submit services/agent     --tag "$REPO/agent:0.3.0"     --project gke-ai-platform
```

## 2. Deploy

```powershell
$DB = "10.104.0.3"   # Cloud SQL private IP (terraform output db_private_ip)

helm upgrade --install approval deploy/helm/approval -n support-agent `
  --set image.repository="$REPO/approval" --set image.tag=0.1.0 --set env.dbHost=$DB

helm upgrade --install agent deploy/helm/agent -n support-agent `
  --set image.repository="$REPO/agent" --set image.tag=0.3.0 --set env.dbHost=$DB

kubectl rollout status deploy/approval-approval -n support-agent
kubectl rollout status deploy/agent-agent        -n support-agent
```

## 3. Test the full gate end-to-end

```powershell
# Two forwards: agent (submit a refund) and approval (the queue)
kubectl port-forward -n support-agent svc/agent-agent     8089:80
kubectl port-forward -n support-agent svc/approval-approval 8090:80
```

1. **Submit a refund** (agent) → it becomes a pending action, nothing fires:
   ```powershell
   curl -s -X POST http://localhost:8089/handle -H "Content-Type: application/json" `
     -d '{"ticket":"My order #4471 hasnt arrived and I want a refund."}'
   # response: action="pending_approval", action_id="<uuid>", requires_approval=true
   ```
2. **See it in the queue**: open http://localhost:8090 — the action is `pending`. Or:
   ```powershell
   curl -s "http://localhost:8090/actions?status=pending"
   ```
3. **Approve it** (the human step) — executes the refund and writes the audit log:
   ```powershell
   $ID = "<action_id from step 1>"
   curl -s -X POST "http://localhost:8090/actions/$ID/approve" -H "Content-Type: application/json" `
     -d '{"approver":"operator","note":"verified order, refund ok"}'
   # response: status="executed", result={status:"issued", confirmation:"RF-..."}
   ```
4. **Inspect the record + audit trail**:
   ```powershell
   curl -s "http://localhost:8090/actions/$ID"
   # action.status=executed; audit=[created(agent), approved(operator), executed(operator)]
   ```
   Reject path: `POST /actions/$ID/reject` → status `rejected`, never executed.

## ✅ Phase 4 done when
- A refund ticket produces a **pending** action and the agent executes **nothing**.
- The action stays pending until a human approves; only then does the approval service issue
  it (`executed`), or `rejected` if declined.
- `audit_log` records `created → approved → executed` (or `rejected`) with actor + timestamp.
- The agent has no refund code path at all — the only executor is the gated approval service.

## Cost discipline
GKE + Cloud SQL bill continuously. `terraform destroy` (in `infra/terraform`) when you stop;
`terraform apply` + re-`helm upgrade` to rebuild (images persist in Artifact Registry).

## Next: Phase 5 — Frontend UI + observability
Next.js single pane of glass: live flow board, trace view, cost panel, **approval queue**
(consuming this service's `/actions` API), metrics; Prometheus + Grafana dashboards + alerts.

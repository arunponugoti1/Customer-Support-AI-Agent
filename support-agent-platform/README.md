# Customer-Support AI Agent — an enterprise-grade agent platform on GKE

A production-style **customer-support agent** built the way a platform team would ship it:
infrastructure as code, containerized microservices on Kubernetes, **every model call metered
for cost**, **distributed tracing** across the whole request, a **human approval gate** so no
risky action auto-fires, a **public HTTPS console**, a real **Gmail channel**, and
**Prometheus + Grafana** observability.

> The agent is the vehicle; the *platform engineering* is the point — security, scalability,
> reliability, reproducibility, cost control, and observability.

**Stack:** GKE Standard · Terraform · Helm · Docker · Vertex AI (Gemini 2.5 Flash) · LangGraph ·
pgvector on Cloud SQL Postgres · FastAPI · Next.js · OpenTelemetry → Cloud Trace · Prometheus +
Grafana · ingress-nginx + cert-manager (Let's Encrypt) · Workload Identity · Secret Manager.

---

## What it does

A support ticket (typed in the console **or** arriving by email) flows through a LangGraph agent:

```
classify ─┬─ order_status ─▶ lookup (order tool) ─▶ retrieve ─▶ compose ─┐
          └─ else ───────────────────────────────▶ retrieve ─▶ compose ─┤
compose  ─┬─ refund / cancellation ─▶ GATE ─▶ pending approval ──────────┤
          └─ else ─────────────────────────────────────────────────────▶ reply
```

- **classify** the intent, **retrieve** relevant FAQ from a pgvector store, **compose** a reply.
- **High-risk actions (refund / cancellation) never execute automatically** — they stop at a
  human approval gate. A refund is issued *only* against a record a human approved.
- **Every** model + embedding call is routed through an **LLM Proxy** that meters tokens and
  cost per ticket and exposes Prometheus metrics — the seed of a future model gateway.
- **One distributed trace per ticket** spans every service (agent → proxy → approval),
  including each graph node and tool call.

---

## Architecture

```
                Browser ──HTTPS──▶ Ingress (nginx + Let's Encrypt)
                                        │
                                        ▼
                                   frontend (Next.js)  ── /api/* proxy ──┐
   Gmail inbox ──poll──▶ gmail-connector ──┐                            │
                                            ▼                            ▼
                                          agent (LangGraph) ──▶ llm-proxy ──▶ Vertex AI Gemini
                                            │                     │ (meter: tokens + cost)
                                            ▼                     ▼
                                       approval (HITL gate)   Cloud SQL (pgvector FAQ, llm_calls,
                                            │                  pending_actions, audit_log)
                                            ▼
                                    refund executes only after human approve

   Cross-cutting:  OpenTelemetry → Cloud Trace   |   Prometheus + Grafana   |   Workload Identity + Secret Manager
```

### Services (`services/`, each a Docker image, deployed by Helm)
| service | role |
|---|---|
| **agent** | LangGraph orchestration: classify → (tool) → retrieve → compose → gate |
| **llm-proxy** | single choke point for model/embedding calls; meters tokens + cost; Prometheus metrics |
| **approval** | human-in-the-loop gate; `pending_actions` + append-only `audit_log`; the only executor of risky actions |
| **frontend** | Next.js console (submit ticket, live flow, approvals queue, cost panel); proxies to internal services |
| **gmail-connector** | email channel: ingest mail → agent → approval → send approved reply in-thread |

---

## Engineering principles (enforced throughout)

- **Everything as code** — infra in Terraform, deploys in Helm, apps in Docker. The only manual
  step is the one-time Gmail OAuth consent (a user-resource that *requires* user consent).
- **Secure by default** — secrets in **Secret Manager** (never in code/images), **Workload
  Identity** (no key files in pods), least-privilege IAM, **non-root** containers with
  read-only root filesystems and dropped capabilities.
- **Observable by default** — distributed tracing, Prometheus metrics, and dashboards wired in
  from the start, not bolted on.
- **Reliable by default** — health/readiness probes, HPAs, graceful handling, single-writer
  where correctness needs it.
- **Cost-disciplined** — `terraform apply` to run, `terraform destroy` to stop the meter; a
  billing budget + alert lives in Terraform; per-ticket cost is tracked and dashboarded.

---

## Repository layout

```
support-agent-platform/
├── infra/terraform/        # project, network, GKE, Cloud SQL, registry, secrets, IAM, budget
├── deploy/
│   ├── helm/               # per-service charts: agent, llm-proxy, approval, frontend, gmail-connector
│   ├── cert-manager/       # Let's Encrypt ClusterIssuers
│   ├── observability/      # Prometheus + Grafana values, dashboard, alert rules
│   └── README-phase*.md    # step-by-step runbooks per phase
└── services/               # agent, llm-proxy, approval, frontend, gmail-connector (+ Dockerfiles)
```

---

## Quick start (high level)

> Full, copy-pasteable steps are in the `deploy/README-*.md` runbooks. Requires a GCP project,
> `gcloud`, `kubectl`, `helm`, and (for builds) Cloud Build.

```bash
# 1. Infrastructure (cluster, Cloud SQL, registry, IAM, budget)
cd infra/terraform && terraform init && terraform apply

# 2. Build images (Cloud Build) and deploy services (Helm)
gcloud builds submit services/<svc> --tag <REGION>-docker.pkg.dev/<PROJECT>/sap-images/<svc>:<tag>
helm upgrade --install <release> deploy/helm/<svc> -n support-agent --set image.repository=... --set image.tag=...

# 3. Public HTTPS  — ingress-nginx + cert-manager + Let's Encrypt   (deploy/README-phase5.md)
# 4. Observability — Prometheus + Grafana + alerts                  (deploy/README-phase5b.md)
# 5. Email channel — Gmail connector (one-time OAuth)               (deploy/README-gmail.md)

# Stop the meter when idle:
cd infra/terraform && terraform destroy
```

Runbooks by capability:
- `deploy/README.md` — phase 1: prove the build→push→deploy loop
- `deploy/README-phase3.md` — orchestration, tools, distributed tracing
- `deploy/README-phase4.md` — human approval gate + sandboxing
- `deploy/README-phase5.md` — frontend + public HTTPS (DuckDNS + cert-manager)
- `deploy/README-phase5b.md` — Prometheus + Grafana + alerts
- `deploy/README-gmail.md` — Gmail email channel

---

## Security model

- **No key files.** Pods run as a Google service account via **Workload Identity**; the app SA
  has only `aiplatform.user`, `cloudsql.client`, `secretmanager.secretAccessor`,
  `cloudtrace.agent`, `monitoring.metricWriter`.
- **Secrets** (DB password, Gmail OAuth refresh token) live in **Secret Manager**, read at
  runtime — never baked into images or committed. `.gitignore` blocks tfstate, tfvars, OAuth
  JSON, `.env`, and provider binaries.
- **Containers** are non-root (uid 10001), read-only root filesystem, `allowPrivilegeEscalation:
  false`, all capabilities dropped.
- **The gate is a real sandbox:** the agent has *no* capability to issue a refund or send an
  email — only the approval service / connector can, and only against an `approved` record.

---

## Observability

- **Tracing:** OpenTelemetry → Cloud Trace; one trace per ticket across all services, with a
  span per graph node, tool call, and model call (token/cost/latency attributes).
- **Metrics:** `llm_tokens_total`, `llm_cost_usd_total`, `llm_latency_ms` (histogram),
  `approval_actions_total`, `gmail_ingested_total/sent_total/errors_total`.
- **Grafana dashboard:** total cost, spend $/hr, tokens/s, model p95 latency, approval actions,
  email volume. **Alerts:** p95 latency, spend burn rate, approval failures, connector errors.

---

## Status

Built in phases, each proven end-to-end on a live cluster:

- [x] **1** — IaC + build/deploy loop (Terraform → Cloud Build → Helm → GKE)
- [x] **2** — Agent + LLM Proxy/meter + pgvector FAQ + cost-per-ticket
- [x] **3** — Tools (order lookup) + intent routing + distributed tracing
- [x] **4** — Human approval gate + audit log (nothing risky auto-fires)
- [x] **5a** — Next.js console + public HTTPS (ingress-nginx + cert-manager)
- [x] **Channel** — Gmail ingress (email → draft → approve → reply)
- [x] **5b** — Prometheus + Grafana dashboards + alerts
- [ ] **6** — eval harness, screenshots, hardening (static IP, mesh, CI)

---

## License

For learning / portfolio use.

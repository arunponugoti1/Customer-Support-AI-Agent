# Customer-Support AI Agent — enterprise AI platform on GKE

An end-to-end, production-style **customer-support agent** and the **AI gateway** that governs
its model access — built the way a platform team ships: infrastructure as code, containerized
microservices on Kubernetes, every model call metered, distributed tracing, a human approval
gate, public HTTPS, a real email channel, governed model access, and full observability.

This repo has two components (same GKE cluster + Cloud SQL):

## 📁 [`support-agent-platform/`](support-agent-platform/) — the agent platform (Layer 3)
The support agent itself and its platform. Reads a ticket → retrieves FAQ (pgvector) → drafts a
reply → high-risk actions (refunds) stop at a **human approval gate**. Includes:
- **Terraform** (GKE, Cloud SQL, networking, IAM, Secret Manager, budget) · **Helm** charts ·
  **Docker** images built on Cloud Build
- **agent** (LangGraph: classify → tool/retrieve → compose → gate), **llm-proxy** (token/cost
  meter + PII/injection guardrails), **approval** (HITL gate + audit log), **frontend** (Next.js
  console, public HTTPS via ingress-nginx + cert-manager), **gmail-connector** (email channel)
- **OpenTelemetry → Cloud Trace**, **Prometheus + Grafana** dashboards + alerts

See [`support-agent-platform/README.md`](support-agent-platform/README.md) and the
`deploy/README-*.md` runbooks.

## 📁 [`ai-gateway/`](ai-gateway/) — the AI gateway (Layer 2)
A **LiteLLM** gateway that governs all model access for the platform:
- **Model tiers** (Gemini `fast`/`balanced`/`smart`) with automatic **fallback**
- **Virtual keys** with **budgets + rate limits** (credential containment, blast-radius control)
- **Redis response caching**
- **PII masking + prompt-injection** guardrails
- Per-model / per-key **spend + usage** in Grafana

See [`ai-gateway/README.md`](ai-gateway/README.md).

---

## Architecture (high level)
```
Browser / Email ─▶ Ingress (HTTPS) / Gmail ─▶ frontend / connector ─▶ agent ─▶ llm-proxy ─▶ AI gateway ─▶ Vertex AI Gemini
                                                                          │            (meter + guardrails)  (tiers, keys, cache, fallback)
                                                                          ▼
                                                                   approval gate (HITL) ─▶ Cloud SQL (pgvector, ledger, approvals, audit)
   Observability: OpenTelemetry → Cloud Trace · Prometheus + Grafana · Workload Identity + Secret Manager
```

## Principles
Everything as code · secure by default (Workload Identity, Secret Manager, non-root, least-priv)
· observable by default (tracing, metrics, dashboards) · cost-disciplined (`terraform destroy`
when idle; per-ticket cost tracked).

> Built as a hands-on path to AI Platform / Agent-Infra engineering. For learning / portfolio use.

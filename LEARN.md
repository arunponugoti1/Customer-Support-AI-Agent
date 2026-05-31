# LEARN.md — learn this repo to jump from support → DevOps / Platform / LLMOps

This project is **one coherent production system**, on purpose. The gap that blocks the jump
out of a support/junior role isn't "knows tools" — it's **understanding how the tools fit
together end-to-end around a real purpose**. Toy projects reinforce tool-silos; this one
forces integration: Terraform → GKE → Helm → five services → an AI gateway → tracing →
metrics → CI/CD, all serving one flow (a support ticket).

> The test of "I learned it" is **not** "it deployed." It's: *can I whiteboard the whole
> architecture from memory and explain why every arrow exists?* If you can't draw it without
> looking, you're not done — no matter that it ran.

Work it in **6 passes**. Passes 1–5 build recognition; **pass 6 builds generation** — the
ability to do this for *any* system, which is what actually gets you hired.

---

## The system in one breath
```
Browser/Email ─▶ Ingress (HTTPS + basic-auth) / Gmail connector
            ─▶ frontend (Next.js) ─▶ agent (LangGraph: classify→tool/retrieve→compose→gate)
            ─▶ llm-proxy (meter $ + PII/injection guardrails)
            ─▶ AI gateway (LiteLLM: model tiers, virtual keys+budgets, cache, fallback)
            ─▶ Vertex AI Gemini
   high-risk (refund/cancel) ─▶ approval gate (human) ─▶ refunds ledger
   cross-cutting: OpenTelemetry→Cloud Trace · Prometheus+Grafana · Workload Identity + Secret Manager · CI (GitHub Actions) + eval gate
```

---

## Pass 1 — Read & run (get it live, see it work)
**Goal:** the whole loop runs and you've seen each moving part once.
- Read in this order: root `README.md` → `support-agent-platform/README.md` →
  `infra/terraform/README.md` → the `deploy/README-phase*.md` runbooks in number order.
- Provision: `infra/terraform` (`terraform apply`) → build images (Cloud Build) → `helm upgrade`
  each chart in `deploy/helm/`.
- Drive it from the console (the URL the frontend Ingress gets) using `test.md` scenarios.
- **Done when:** you can name what each of the 5 services + the gateway does in one sentence.

## Pass 2 — Trace one request end-to-end
**Goal:** follow a single ticket through *every* hop.
- Submit a refund ticket. Then open its trace in **Cloud Trace** (the `trace_id` is in the
  response) and walk the spans: `node.classify → POST /generate (llm-proxy) → vertex.chat… →
  node.retrieve → /embed → node.compose → node.gate → tool.request_approval → POST /actions`.
- Map each span to the source: `services/agent/app.py` (nodes), `services/llm-proxy/app.py`
  (meter+guardrails), `ai-gateway/` (LiteLLM), `services/approval/app.py` (gate).
- **Done when:** you can point to the exact function behind every span.

## Pass 3 — Modify (make it yours by changing it)
**Goal:** change behavior confidently. Each is small and local:
- Add a new **intent** (`services/agent/routing.py` + the classify prompt) — add a test in
  `tests/` and a row in `eval/dataset.jsonl`.
- Add a **FAQ** entry and an **order** (`services/agent/app.py` seeds) — watch retrieval change.
- Add/retune a **model tier** or fallback (`ai-gateway/deploy/helm/litellm/files/config.yaml`).
- Run `pytest` and `eval/run_eval.py` after each change.
- **Done when:** you changed a behavior, the unit test + eval still pass, and you saw the diff live.

## Pass 4 — Understand the WHY (the senior-value pass)
**Goal:** code shows the answer chosen, never the alternatives rejected. Seniority lives in the
tradeoffs. For each row below, say it out loud; where you can't, go research it.

| Decision | Exists because | Alternative | Chosen because |
|---|---|---|---|
| **Human approval gate** (not auto-refund) | money/irreversible actions need a human | auto-execute | safety: a misclassified refund must never auto-fire |
| **One LLM-proxy choke point** | meter cost + enforce guardrails in ONE place | each service calls Vertex directly | single point to meter, mask PII, swap backend, can't be bypassed |
| **Workload Identity** (no key files) | pods need GCP access | mount a SA JSON key | no long-lived secret to leak/rotate; per-pod identity |
| **AI gateway (LiteLLM)** in front of models | routing, keys, budgets, cache, fallback | app calls model SDK directly | governed access + blast-radius control + cost attribution |
| **Virtual key with budget+RPM** for the agent | cap a compromised app | share the master key | containment: a leaked app key can't run unlimited spend |
| **Eval gate at 100% on gate-correctness** | some agent errors are *safety* failures | grade accuracy only | a refund misclassified as "other" is dangerous, not just wrong |
| **Edge basic-auth** on the console | the approval UI must not be open | no auth | only authenticated users can approve actions |
| **Private nodes + authorized networks** (code) | reduce attack surface | public cluster | enterprise default; shown as code even if applied on next provision |

- **Done when:** you can defend every row, and you found at least one you had to look up.

## Pass 5 — Break it (predict → break → observe)
**Goal:** hypothesis-driven troubleshooting — the real support→platform superpower.
For each: **first write your prediction**, then break it, then verify against Grafana/Cloud Trace.
- Kill the Cloud SQL connection (scale it / wrong password) → predict the failure + which span/metric shows it.
- Set a virtual-key `rpm_limit` very low and burst → predict the 429 and where it surfaces.
- Send a prompt-injection ticket → predict `injection_detected` + the guardrail metric moving.
- Delete the frontend Ingress (we actually did this by accident once!) → predict the 404 and the fix.
- **Done when:** your prediction matched the observed failure *and* your observability surfaced it.

## Pass 6 — Build something NOT in the repo (cold, no guide)
**Goal:** the proof you own integration is integrating something new. Pick ONE and build it
end-to-end yourself:
- A **Slack channel** beside the Gmail connector (ingest → agent → approve → reply).
- The **eval-gated canary**: ship a new agent version to 10% traffic, run the eval against the
  canary, auto-rollback if gate-correctness drops (Argo Rollouts).
- A **self-hosted model** behind the gateway (flip a tier to a vLLM/Ollama backend).
- **Done when:** it works, you wrote no guide, and you can explain every new arrow.

---

## Career-path map (what each pass proves to which role)
- **DevOps / SRE:** Pass 1–2 (provision, deploy, trace), Pass 5 (break/observe, incident skills).
- **Senior DevOps:** Pass 3–4 (change safely + defend tradeoffs), reliability (retries/backoff,
  probes, HPA), the CI pipeline.
- **Platform Engineer:** the whole IaC + Helm + Workload Identity + gateway + GitOps story; "everything as code."
- **AI Platform / LLMOps:** the gateway (tiers/keys/budgets/cache/guardrails), per-request cost
  metering, and **the eval harness as a deploy gate** — the LLMOps loop most candidates can't articulate.

## Final exam (do this before any interview)
1. Whiteboard the architecture from memory; explain every arrow and why it exists.
2. Talk through one ticket's full trace.
3. Name 3 failure modes and how the system detects + degrades.
4. Explain the cost story: where every dollar is metered and capped.
5. Explain the safety story: why nothing risky auto-fires.

If you can do those five cold, you can defend this project in any platform/LLMOps interview —
and, more importantly, do it again for a real company's system.

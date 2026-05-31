# AI Gateway (Layer 2) — LiteLLM

The governed model-access layer for the platform. Built **on the same GKE cluster + Cloud SQL**
as the support agent (Layer 3), but isolated as its own component here. Apps talk to the
gateway; the gateway owns routing, keys, budgets, caching, and guardrails for every model call.

**Why:** turn the single choke point (the Layer 3 `llm-proxy`) into a real **AI gateway** —
the place where model access is routed, rate-limited, cached, secured, and accounted for.

**Tool:** [LiteLLM](https://docs.litellm.ai) — the de-facto open-source LLM gateway. We learn
the concepts by configuring real ones, not toy versions.

## Model tiers (all Gemini via Vertex, on existing credits)
| alias | model | use |
|---|---|---|
| `fast` | gemini-2.5-flash-lite | easy tickets |
| `balanced` | gemini-2.5-flash | default |
| `smart` | gemini-2.5-pro | hard tickets |

Auto-fallback: `smart → balanced → fast` on error.

## Slice plan
1. **Deploy LiteLLM** — Helm, Cloud SQL-backed, Vertex via Workload Identity. ✅ DONE
2. **Wire in** — point `llm-proxy` `OPENAI_BASE_URL` at the gateway.
3. **Virtual keys + budgets + rate limits** (per team/app).
4. **Routing + fallback** (easy→fast, hard→smart).
5. **Redis semantic caching.**
6. **Guardrails** (PII / injection / moderation) + free providers (OpenRouter / Groq).
7. **Tracking** — spend/usage into Grafana.

## Slice 1 — deploy (DONE, proven 2026-05-31)

Runs in the `support-agent` namespace (reuses the `sap-app` Workload Identity, which has
`aiplatform.user` — Vertex needs no key file). Backed by a dedicated `litellm` database in the
`sap-pg` Cloud SQL instance. Master key + DATABASE_URL live in Secret Manager / a k8s secret,
never in git.

### One-time setup (out-of-band; not in git)
```powershell
# dedicated DB for the gateway's own tables (prisma)
gcloud sql databases create litellm --instance=sap-pg --project gke-ai-platform
# generated admin master key
$KEY = "sk-$([guid]::NewGuid().ToString('N'))$([guid]::NewGuid().ToString('N').Substring(0,16))"
$KEY | gcloud secrets create litellm-master-key --data-file=- --project gke-ai-platform
# k8s secret with master key + DB url (password pulled from Secret Manager)
$DBPASS = gcloud secrets versions access latest --secret=db-password --project gke-ai-platform
$MKEY   = gcloud secrets versions access latest --secret=litellm-master-key --project gke-ai-platform
kubectl create secret generic litellm-secrets -n support-agent `
  --from-literal=LITELLM_MASTER_KEY="$MKEY" `
  --from-literal=DATABASE_URL="postgresql://appuser:$DBPASS@10.104.0.3:5432/litellm"
```

### Deploy
```powershell
helm upgrade --install litellm deploy/helm/litellm -n support-agent
kubectl rollout status deploy/litellm-litellm -n support-agent
```

### Test
```powershell
$MKEY = gcloud secrets versions access latest --secret=litellm-master-key --project gke-ai-platform
kubectl port-forward -n support-agent svc/litellm-litellm 4000:80
curl -H "Authorization: Bearer $MKEY" http://localhost:4000/v1/models
curl -X POST http://localhost:4000/v1/chat/completions -H "Authorization: Bearer $MKEY" `
  -H "Content-Type: application/json" -d '{"model":"fast","messages":[{"role":"user","content":"hi"}]}'
# Admin UI: http://localhost:4000/ui  (login: admin / the master key)
```

## Notes / hardening
- LiteLLM needs ~1–2Gi memory (prisma + proxy); a 1Gi limit OOMKills it. Set to 2Gi.
- Reuses the `support-agent` namespace for the WI binding; a dedicated namespace + least-priv SA
  is a hardening step.
- Cloud SQL + an extra ~1Gi pod = more cost. `terraform destroy` when idle (drop the `litellm`
  DB and secrets are cheap to recreate).

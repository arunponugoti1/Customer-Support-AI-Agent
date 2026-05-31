# Phase 5b — Observability (Prometheus + Grafana + alerts)

Self-hosted, lean Prometheus + Grafana in the `observability` namespace. Prometheus scrapes
the services that already expose `/metrics` via their `prometheus.io/scrape` annotations
(llm-proxy, approval, gmail-connector) — no ServiceMonitors needed. Grafana provisions the
Prometheus datasource and loads a dashboard from a labelled ConfigMap (sidecar).

## Install

```powershell
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts ; helm repo update

# Prometheus (+ alert rules)
helm upgrade --install prometheus prometheus-community/prometheus `
  --namespace observability --create-namespace `
  -f deploy/observability/prometheus-values.yaml

# Dashboard ConfigMap (sidecar picks up label grafana_dashboard=1)
kubectl create configmap sap-dashboard -n observability `
  --from-file=support-agent.json=deploy/observability/dashboard.json `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl label configmap sap-dashboard -n observability grafana_dashboard=1 --overwrite

# Grafana (datasource provisioned to prometheus-server)
helm upgrade --install grafana grafana/grafana `
  --namespace observability -f deploy/observability/grafana-values.yaml
```

## Open Grafana

```powershell
# admin password:
kubectl get secret grafana -n observability -o jsonpath="{.data.admin-password}" | `
  %{ [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }
kubectl port-forward -n observability svc/grafana 3000:80
# http://localhost:3000  (user: admin)  ->  dashboard "Support Agent — platform"
```

Prometheus UI / alerts (optional): `kubectl port-forward -n observability svc/prometheus-server 9090:80`.

## Dashboard panels
- **Total model cost (USD)** — `sum(llm_cost_usd_total)`
- **Emails ingested / replies sent** — `sum(gmail_ingested_total)`, `sum(gmail_sent_total)`
- **Model spend ($/hour)** — `sum(rate(llm_cost_usd_total[10m]))*3600`
- **Tokens/sec by kind** — `sum by(kind)(rate(llm_tokens_total[5m]))`
- **Model latency p95 (ms)** — `histogram_quantile(0.95, sum by(le)(rate(llm_latency_ms_bucket[5m])))`
- **Approval actions (1h) by event** — `sum by(event)(increase(approval_actions_total[1h]))`

## Alert rules (Prometheus → Alertmanager)
`deploy/observability/prometheus-values.yaml` → `serverFiles.alerting_rules.yml`:
- **ModelLatencyHighP95** — p95 model latency > 8s for 5m
- **ModelSpendBurnHigh** — spend > $1/hour for 10m
- **ApprovalExecutionFailure** — any approved action failed to execute
- **GmailConnectorErrors** — connector errors > 3 in 10m

(Alertmanager is installed but has no receiver wired — add Slack/email/PagerDuty in its config
to actually notify. Rules fire and are visible in the Prometheus UI / Alertmanager as-is.)

## Note — latency histogram buckets (llm-proxy 0.2.1)
The `llm_latency_ms` histogram needs explicit ms-scale buckets; Prometheus' default buckets top
out at 10 (seconds-oriented), so ms observations overflow into +Inf and quantiles break. Fixed
in llm-proxy **0.2.1** (`buckets=(50,100,250,500,1000,2000,4000,8000,16000,30000)`).

## Cost
Prometheus + Grafana + node-exporter + kube-state-metrics + Alertmanager add memory; on a small
node pool this may pull in another node. `terraform destroy` (+ `helm uninstall prometheus grafana`)
when idle.

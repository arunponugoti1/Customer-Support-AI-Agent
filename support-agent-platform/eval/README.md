# Agent eval harness

A quality gate for the support agent. Runs a labelled set of tickets through the **live**
agent and scores three things that matter for an agent platform:

| metric | what it checks |
|---|---|
| **intent accuracy** | did the agent classify the ticket correctly? |
| **gate correctness** | did high-risk tickets (refund/cancellation) stop for human approval, and low-risk ones *not*? A misclassified refund that auto-answers is a **safety** failure — graded strictly (must be 100%). |
| **cost / ticket** | average + total spend (from the metered response) |

It exits non-zero if thresholds aren't met, so **CI can gate** merges/deploys.

## Run
```bash
python eval/run_eval.py --url https://<host>/api/handle
# or against the agent directly:
python eval/run_eval.py --url http://localhost:8089/handle
# tune: --min-intent 0.8  --min-gate 1.0  --delay 1.5
```
Stdlib only (urllib) — no pip install, runs anywhere incl. CI.

- `dataset.jsonl` — labelled tickets: `{ticket, expected_intent, expected_gate}`.
- Paced (`--delay`) and retries transient 5xx, so it measures agent quality, not provider
  rate-limit blips.

## Baseline (2026-05-31)
`intent 93.8% (15/16)` · `gate 100% (16/16)` · `~$0.0025/ticket` → **PASS**.
(The single intent miss — "track my package" → `shipping` vs `order_status` — is a borderline label.)

> This harness already earned its keep: on first run it surfaced a dropped Ingress (public
> outage) and intermittent embed 429s under burst — the latter fixed with retry+backoff in
> llm-proxy 0.3.2.

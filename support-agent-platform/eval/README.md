# Agent eval harness

A quality gate for the support agent. Runs a labelled set of tickets through the **live**
agent and scores three things that matter for an agent platform:

| metric | what it checks |
|---|---|
| **intent accuracy** | did the agent classify the ticket correctly? |
| **gate correctness** | did high-risk tickets (refund/cancellation) stop for human approval, and low-risk ones *not*? A misclassified refund that auto-answers is a **safety** failure — graded strictly (must be 100%). |
| **cost / ticket** | average + total spend (from the metered response) |

It exits non-zero if thresholds aren't met, so **CI can gate** merges/deploys.
https://llm-agent.duckdns.org/



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

## Red-team harness (`redteam.py`) — adversarial security gate
Unlike the quality eval (and unlike unit tests, which check the regex against the phrases it was
written for), `redteam.py` is **adversarial**: it fires injection / prompt-leak / PII-echo
attacks (including base64, leetspeak, and spaced-out obfuscation) at the live agent and reports
an **injection success rate** — the headline Layer-2 security metric. Lower is better.

```bash
python eval/redteam.py --url https://<host>/api/handle --user operator --password *** --max-rate 0.10
```
**Result (llm-proxy 0.3.2 → 0.3.3 hardening):** success rate **38.5% → 0%** on the current attack
set, after: block-on-detect, normalized matching (defeats spacing/leetspeak), broader patterns,
SSN masking, and **output validation** (catches system-prompt leakage in the reply).

> 0% is on *this* fixed set — an adaptive attacker will find new bypasses, so the set should grow
> over time, and NER-based PII (Presidio/spaCy) is the next hardening layer. The point is the
> measured rate + the downward trend as you harden — also runnable in CI via
> `.github/workflows/redteam.yml`.

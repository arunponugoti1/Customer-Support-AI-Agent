# Gmail channel — production-style email ingress (HITL-gated)

Turns the platform into a real support inbox: **incoming email → agent drafts a reply →
the reply waits in the Approvals queue → on approve, the connector sends it back in-thread.**
No email is ever sent without a human approving it.

```
Gmail inbox ──poll──▶ gmail-connector ──▶ agent /handle (draft)
                            │
                            └──▶ approval /actions (send_email, PENDING)
                                          │  (human clicks Approve in the console)
                                          ▼
                       gmail-connector ◀─ approved ─ sends threaded reply ─▶ Gmail
```

New/changed:
- **`approval` 0.2.0** — adds the `send_email` action type. Unlike refund/cancellation (which
  the approval service executes itself), `send_email` is **approved here but executed by the
  connector** (it owns the Gmail credential). New `POST /actions/{id}/complete` lets the
  connector mark it sent. Nothing sends without a prior `approved` state.
- **`gmail-connector` 0.1.0** — the poll loop (ingest + dispatch). Reuses the `sap-app`
  Workload Identity to read the OAuth secret (no new IAM).

## One-time manual step (yours) — authorize Gmail

Gmail is a *user* resource, so it needs user OAuth consent (service-account delegation is
Workspace-only, not consumer @gmail.com). This is the single documented manual exception.

1. **Enable + consent screen** (Console → APIs & Services):
   - Gmail API is already enabled (`gcloud services enable gmail.googleapis.com` — done).
   - **OAuth consent screen** → External → fill app name + your email → **Add test user =
     the Gmail address** you'll use → Save. (Leave it in "Testing".)
2. **OAuth client** → Credentials → Create credentials → **OAuth client ID** → type
   **Desktop app** → download JSON as `client_secret.json`.
3. **Get a refresh token** on your machine:
   ```powershell
   pip install google-auth-oauthlib
   python support-agent-platform/services/gmail-connector/oauth_setup.py client_secret.json
   ```
   A browser opens → sign in with that Gmail → allow. The script prints
   `{client_id, client_secret, refresh_token}`.
4. **Store it as a secret** (paste the JSON, then Ctrl-Z + Enter on Windows / Ctrl-D on *nix):
   ```powershell
   gcloud secrets create gmail-oauth --data-file=- --project gke-ai-platform
   # later, to rotate: gcloud secrets versions add gmail-oauth --data-file=- --project gke-ai-platform
   ```
   (The `sap-app` service account already has `secretmanager.secretAccessor`, so the connector
   can read it.)

> Heads-up: while the consent screen is "Testing", the refresh token expires ~7 days — re-run
> step 3 to refresh, or publish the app for a long-lived token.

## Deploy

```powershell
$REPO = "us-central1-docker.pkg.dev/gke-ai-platform/sap-images"
# approval 0.2.0 (send_email support)
helm upgrade --install approval deploy/helm/approval -n support-agent `
  --set image.repository="$REPO/approval" --set image.tag=0.2.0 --set env.dbHost=10.104.0.3
# gmail-connector 0.1.0
helm upgrade --install gmail-connector deploy/helm/gmail-connector -n support-agent `
  --set image.repository="$REPO/gmail-connector" --set image.tag=0.1.0
kubectl rollout status deploy/gmail-connector-gmail-connector -n support-agent
kubectl logs -n support-agent deploy/gmail-connector-gmail-connector -f   # watch the poll loop
```

## Test

1. From any account, **send an email** to the authorized Gmail, e.g.
   *Subject:* `Refund for #4471` — *Body:* `My order #4471 arrived broken, I'd like a refund.`
2. Within ~30s the connector ingests it (see logs); a **send_email** action appears in the
   console **Approvals** tab at https://llm-agent.duckdns.org (alongside the refund action,
   since this ticket is also high-risk).
3. Click **Approve** on the send_email action → the connector sends the drafted reply **in the
   same thread**. Check the inbox — you'll get the reply. The action shows `executed` with the
   sent message id; the original mail gets the `AgentReplied` label.
4. **Reject** instead → no email is sent.

Verify the gate held: a `send_email` action can only reach `executed` *after* `approved`
(the `/complete` endpoint returns 409 otherwise).

## Notes / hardening
- Single replica by design (sequential ingest→dispatch avoids double-send). Don't scale as-is.
- Polling (every 30s) is simple + robust; Gmail push via Pub/Sub `users.watch` is the
  lower-latency upgrade (needs a Pub/Sub topic + 7-day watch renewal).
- The connector labels handled mail `AgentHandled` (and replied mail `AgentReplied`) so it
  processes each message once. Tune `GMAIL_QUERY` to scope which mail it picks up.

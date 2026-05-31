"""Gmail connector — the email *channel* for the support agent (a production-style ingress).

Loop (every POLL_INTERVAL):
  1. INGEST: find new inbox mail (Gmail query) → call the agent /handle → create a
     `send_email` PENDING action in the approval service holding the drafted reply.
     Label the mail HANDLED so it's processed once.
  2. DISPATCH: find `send_email` actions a human APPROVED → send the threaded reply via
     Gmail → mark the action complete (executed). Label the mail REPLIED.

The gate guarantee holds end-to-end: no email is ever sent until a human approves it in the
Approvals queue. This worker is the only thing with Gmail send capability; it sends only for
actions already in state 'approved'.

Auth: a Gmail OAuth refresh token (+ client id/secret) stored in Secret Manager, read via
Workload Identity (no key files). Gmail is a *user* resource, so it needs user OAuth — not
project IAM / service-account delegation (that's Workspace-only, not consumer @gmail.com).
"""
import base64
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from email.mime.text import MIMEText

import requests
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from google.cloud import secretmanager
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from opentelemetry import trace as ot
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gmail-connector")

# ── Config ───────────────────────────────────────────────────────────────────
PROJECT = os.environ["GCP_PROJECT"]
AGENT_URL = os.environ["AGENT_URL"]
APPROVAL_URL = os.environ["APPROVAL_URL"]
GMAIL_SECRET = os.getenv("GMAIL_SECRET", "gmail-oauth")
GMAIL_QUERY = os.getenv("GMAIL_QUERY", "in:inbox -label:AgentHandled newer_than:1d")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))
HANDLED_LABEL = os.getenv("HANDLED_LABEL", "AgentHandled")
REPLIED_LABEL = os.getenv("REPLIED_LABEL", "AgentReplied")
MAX_PER_POLL = int(os.getenv("MAX_PER_POLL", "5"))
SCOPES = ["https://www.googleapis.com/auth/gmail.modify",
          "https://www.googleapis.com/auth/gmail.send"]

# ── Tracing ────────────────────────────────────────────────────────────────────
ENABLE_TRACING = os.getenv("ENABLE_TRACING", "true").lower() == "true"
tracer = ot.get_tracer("gmail-connector")


def setup_tracing(fastapi_app):
    if not ENABLE_TRACING:
        log.info("tracing disabled"); return
    provider = TracerProvider(resource=Resource.create({"service.name": "gmail-connector"}))
    provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter(project_id=PROJECT)))
    ot.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(fastapi_app)
    RequestsInstrumentor().instrument()
    log.info("tracing enabled -> Cloud Trace")


# ── Metrics ──────────────────────────────────────────────────────────────────
M_INGESTED = Counter("gmail_ingested_total", "Emails ingested -> approval actions")
M_SENT = Counter("gmail_sent_total", "Approved replies sent")
M_ERRORS = Counter("gmail_errors_total", "Connector errors", ["phase"])

# ── Gmail auth (lazy; tolerates the secret not existing yet) ───────────────────
_service = None
_label_cache = {}


def _load_gmail():
    sm = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT}/secrets/{GMAIL_SECRET}/versions/latest"
    blob = sm.access_secret_version(name=name).payload.data.decode("utf-8")
    cfg = json.loads(blob)
    creds = Credentials(
        token=None,
        refresh_token=cfg["refresh_token"],
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def gmail():
    global _service
    if _service is None:
        _service = _load_gmail()
        log.info("gmail client ready (secret=%s)", GMAIL_SECRET)
    return _service


def label_id(svc, name):
    if name in _label_cache:
        return _label_cache[name]
    existing = svc.users().labels().list(userId="me").execute().get("labels", [])
    for lb in existing:
        if lb["name"] == name:
            _label_cache[name] = lb["id"]; return lb["id"]
    created = svc.users().labels().create(
        userId="me", body={"name": name, "labelListVisibility": "labelShow",
                            "messageListVisibility": "show"}).execute()
    _label_cache[name] = created["id"]
    return created["id"]


def header(msg, key):
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == key.lower():
            return h["value"]
    return ""


def extract_text(payload):
    """Best-effort plain-text body from a Gmail message payload."""
    if payload.get("mimeType", "").startswith("text/plain") and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "replace")
    for part in payload.get("parts", []) or []:
        t = extract_text(part)
        if t:
            return t
    return ""


# ── INGEST: new mail -> agent -> pending approval action ───────────────────────
def ingest():
    svc = gmail()
    handled = label_id(svc, HANDLED_LABEL)
    resp = svc.users().messages().list(userId="me", q=GMAIL_QUERY, maxResults=MAX_PER_POLL).execute()
    for ref in resp.get("messages", []) or []:
        mid = ref["id"]
        msg = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        sender = header(msg, "From")
        subject = header(msg, "Subject") or "(no subject)"
        rfc_id = header(msg, "Message-ID")
        thread_id = msg.get("threadId")
        body = extract_text(msg.get("payload", {})) or msg.get("snippet", "")
        ticket_id = f"gmail-{mid[:10]}"

        with tracer.start_as_current_span("ingest.email") as sp:
            sp.set_attribute("gmail.message_id", mid)
            # 1) run the agent
            a = requests.post(f"{AGENT_URL}/handle",
                              json={"ticket": body, "ticket_id": ticket_id}, timeout=90)
            a.raise_for_status()
            ad = a.json()
            # 2) create the send_email approval action (the reply is held for a human)
            re_subj = subject if subject.lower().startswith("re:") else f"Re: {subject}"
            note = "; agent flagged high-risk (refund/cancellation)" if ad.get("requires_approval") else ""
            payload = {"to": sender, "subject": re_subj, "thread_id": thread_id,
                       "rfc_message_id": rfc_id, "gmail_message_id": mid,
                       "draft": ad.get("draft", ""), "intent": ad.get("intent"),
                       "ticket_id": ticket_id, "agent_action_id": ad.get("action_id")}
            r = requests.post(f"{APPROVAL_URL}/actions",
                              json={"action_type": "send_email", "ticket_id": ticket_id,
                                    "trace_id": ad.get("trace_id"), "payload": payload,
                                    "reason": f"Reply to {sender} re: '{subject}'{note}"}, timeout=30)
            r.raise_for_status()
            sp.set_attribute("approval.action_id", r.json().get("action_id", ""))

        # 3) label so we don't reprocess
        svc.users().messages().modify(
            userId="me", id=mid, body={"addLabelIds": [handled], "removeLabelIds": ["UNREAD"]}).execute()
        M_INGESTED.inc()
        log.info("ingested %s from %s -> action %s", mid, sender, r.json().get("action_id"))


# ── DISPATCH: approved replies -> send via Gmail -> mark complete ──────────────
def send_reply(svc, p):
    msg = MIMEText(p.get("draft", ""))
    msg["To"] = p["to"]
    msg["Subject"] = p["subject"]
    if p.get("rfc_message_id"):
        msg["In-Reply-To"] = p["rfc_message_id"]
        msg["References"] = p["rfc_message_id"]
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = svc.users().messages().send(
        userId="me", body={"raw": raw, "threadId": p.get("thread_id")}).execute()
    return sent.get("id")


def dispatch():
    svc = gmail()
    replied = label_id(svc, REPLIED_LABEL)
    r = requests.get(f"{APPROVAL_URL}/actions",
                     params={"status": "approved", "action_type": "send_email", "limit": MAX_PER_POLL},
                     timeout=30)
    r.raise_for_status()
    for action in r.json().get("actions", []):
        aid = action["action_id"]
        p = action["payload"]
        with tracer.start_as_current_span("dispatch.send") as sp:
            sp.set_attribute("approval.action_id", aid)
            try:
                sent_id = send_reply(svc, p)
                requests.post(f"{APPROVAL_URL}/actions/{aid}/complete",
                              json={"actor": "gmail-connector", "ok": True,
                                    "result": {"status": "sent", "gmail_message_id": sent_id,
                                               "to": p.get("to")}}, timeout=30).raise_for_status()
                if p.get("gmail_message_id"):
                    svc.users().messages().modify(
                        userId="me", id=p["gmail_message_id"],
                        body={"addLabelIds": [replied]}).execute()
                M_SENT.inc()
                log.info("sent reply for action %s (gmail msg %s)", aid, sent_id)
            except Exception as e:  # noqa: BLE001
                M_ERRORS.labels("dispatch").inc()
                log.exception("send failed for %s", aid)
                requests.post(f"{APPROVAL_URL}/actions/{aid}/complete",
                              json={"actor": "gmail-connector", "ok": False,
                                    "result": {"error": str(e)}}, timeout=30)


def loop():
    log.info("poll loop start: every %ss, query=%r", POLL_INTERVAL, GMAIL_QUERY)
    while True:
        for phase, fn in (("ingest", ingest), ("dispatch", dispatch)):
            try:
                fn()
            except Exception as e:  # noqa: BLE001 — never let the loop die
                M_ERRORS.labels(phase).inc()
                log.warning("%s error (will retry): %s", phase, e)
        time.sleep(POLL_INTERVAL)


@asynccontextmanager
async def lifespan(_: FastAPI):
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    yield


app = FastAPI(title="gmail-connector", lifespan=lifespan)
setup_tracing(app)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

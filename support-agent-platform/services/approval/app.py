"""Approval service — the human-in-the-loop gate (Layer 3 'human gate + sandboxing').

The agent can only *request* a high-risk action; only THIS service can *execute* one, and
only against a row a human has approved. That separation is the sandbox: a refund is
impossible without an approved record. Every state change is appended to an audit log.

State machine:  pending ──approve──▶ approved ──(execute)──▶ executed
                   └─────reject───▶ rejected            └──(error)──▶ failed

Auth: Workload Identity (reuses the sap-app GSA/KSA). No key files.
"""
import logging
import os
import uuid
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from google.cloud import secretmanager
from opentelemetry import trace as ot
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from psycopg.rows import dict_row
from psycopg.types.json import Json
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("approval")

# ── Config ───────────────────────────────────────────────────────────────────
PROJECT = os.environ["GCP_PROJECT"]
DB_HOST = os.environ["DB_HOST"]
DB_NAME = os.getenv("DB_NAME", "appdb")
DB_USER = os.getenv("DB_USER", "appuser")
DB_PASSWORD_SECRET = os.getenv("DB_PASSWORD_SECRET", "db-password")

# Actions that may flow through the gate.
#  - INLINE_EXECUTE: this service runs them itself on approve (it owns the capability).
#  - others (e.g. send_email): approved here, but executed by an external worker that owns
#    the capability/credentials (the gmail-connector), which then calls /complete.
INLINE_EXECUTE = {"refund", "cancellation"}
ALLOWED_ACTIONS = INLINE_EXECUTE | {"send_email"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_actions (
  id            BIGSERIAL PRIMARY KEY,
  action_id     UUID        NOT NULL UNIQUE,
  ticket_id     TEXT,
  trace_id      TEXT,
  action_type   TEXT        NOT NULL,
  payload       JSONB       NOT NULL DEFAULT '{}'::jsonb,
  reason        TEXT,
  status        TEXT        NOT NULL DEFAULT 'pending',
  result        JSONB,
  requested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at    TIMESTAMPTZ,
  decided_by    TEXT,
  decision_note TEXT
);
CREATE INDEX IF NOT EXISTS pending_actions_status_idx ON pending_actions (status);

CREATE TABLE IF NOT EXISTS audit_log (
  id         BIGSERIAL PRIMARY KEY,
  action_id  UUID,
  event      TEXT        NOT NULL,
  actor      TEXT,
  detail     JSONB,
  at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_log_action_idx ON audit_log (action_id);
"""

# ── Secrets / DB ───────────────────────────────────────────────────────────────
DB_PASSWORD: str | None = None


def fetch_db_password() -> str:
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT}/secrets/{DB_PASSWORD_SECRET}/versions/latest"
    return client.access_secret_version(name=name).payload.data.decode("utf-8")


def db():
    return psycopg.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
        connect_timeout=10, row_factory=dict_row,
    )


def audit(cur, action_id: str, event: str, actor: str, detail: dict | None = None) -> None:
    cur.execute(
        "INSERT INTO audit_log (action_id, event, actor, detail) VALUES (%s,%s,%s,%s)",
        (action_id, event, actor, Json(detail or {})),
    )


# ── Metrics + tracing ──────────────────────────────────────────────────────────
M_ACTIONS = Counter("approval_actions_total", "Approval actions by event", ["event"])
ENABLE_TRACING = os.getenv("ENABLE_TRACING", "true").lower() == "true"
tracer = ot.get_tracer("approval")


def setup_tracing(fastapi_app: FastAPI) -> None:
    if not ENABLE_TRACING:
        log.info("tracing disabled (ENABLE_TRACING=false)")
        return
    provider = TracerProvider(resource=Resource.create({"service.name": "approval"}))
    provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter(project_id=PROJECT)))
    ot.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(fastapi_app)
    RequestsInstrumentor().instrument()
    log.info("tracing enabled -> Cloud Trace (project=%s)", PROJECT)


# ── The sandbox: the ONLY place a risky action is actually executed ─────────────
def execute_action(action_type: str, payload: dict) -> dict:
    """Perform the approved action. This function is reached ONLY for a row whose status
    is 'approved' (enforced by the caller). Layer 3 has no real payment API, so the refund
    is a deterministic stand-in — but the *gating* is real and is the point."""
    if action_type == "refund":
        return {"status": "issued", "kind": "refund",
                "order_id": payload.get("order_id"),
                "amount_usd": payload.get("amount_usd"),
                "confirmation": f"RF-{uuid.uuid4().hex[:10].upper()}"}
    if action_type == "cancellation":
        return {"status": "cancelled", "kind": "cancellation",
                "order_id": payload.get("order_id"),
                "confirmation": f"CX-{uuid.uuid4().hex[:10].upper()}"}
    raise ValueError(f"unsupported action_type: {action_type}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    global DB_PASSWORD
    DB_PASSWORD = fetch_db_password()
    with db() as conn:
        conn.execute(SCHEMA)
        conn.commit()
    log.info("approval service ready")
    yield


app = FastAPI(title="approval", lifespan=lifespan)
setup_tracing(app)


# ── Models ──────────────────────────────────────────────────────────────────────
class CreateAction(BaseModel):
    action_type: str
    ticket_id: str | None = None
    trace_id: str | None = None
    payload: dict = {}
    reason: str | None = None


class Decision(BaseModel):
    approver: str = "operator"
    note: str | None = None


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/actions", status_code=201)
def create_action(req: CreateAction):
    if req.action_type not in ALLOWED_ACTIONS:
        raise HTTPException(400, f"action_type must be one of {sorted(ALLOWED_ACTIONS)}")
    action_id = str(uuid.uuid4())
    span = ot.get_current_span()
    span.set_attribute("approval.action_id", action_id)
    span.set_attribute("approval.action_type", req.action_type)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO pending_actions
                   (action_id, ticket_id, trace_id, action_type, payload, reason)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (action_id, req.ticket_id, req.trace_id, req.action_type,
                 Json(req.payload), req.reason),
            )
            audit(cur, action_id, "created", "agent",
                  {"ticket_id": req.ticket_id, "action_type": req.action_type})
        conn.commit()
    M_ACTIONS.labels("created").inc()
    log.info("pending action %s created (%s, ticket=%s)", action_id, req.action_type, req.ticket_id)
    return {"action_id": action_id, "status": "pending", "action_type": req.action_type}


@app.get("/actions")
def list_actions(status: str | None = None, action_type: str | None = None, limit: int = 50):
    clauses, args = [], []
    if status:
        clauses.append("status=%s"); args.append(status)
    if action_type:
        clauses.append("action_type=%s"); args.append(action_type)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    args.append(limit)
    with db() as conn:
        rows = conn.execute(
            f"SELECT * FROM pending_actions{where} ORDER BY requested_at DESC LIMIT %s",
            tuple(args)).fetchall()
    return {"actions": rows}


@app.get("/actions/{action_id}")
def get_action(action_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM pending_actions WHERE action_id=%s",
                           (action_id,)).fetchone()
        audit_rows = conn.execute(
            "SELECT event, actor, detail, at FROM audit_log WHERE action_id=%s ORDER BY at",
            (action_id,)).fetchall()
    if not row:
        raise HTTPException(404, "action not found")
    return {"action": row, "audit": audit_rows}


def _load_for_decision(cur, action_id: str) -> dict:
    cur.execute("SELECT * FROM pending_actions WHERE action_id=%s FOR UPDATE", (action_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "action not found")
    if row["status"] != "pending":
        raise HTTPException(409, f"action already {row['status']}")
    return row


@app.post("/actions/{action_id}/approve")
def approve(action_id: str, decision: Decision):
    """Approve, then execute. Execution asserts the row is 'approved' — the sandbox seam."""
    span = ot.get_current_span()
    span.set_attribute("approval.action_id", action_id)
    with db() as conn:
        with conn.cursor() as cur:
            row = _load_for_decision(cur, action_id)
            cur.execute(
                "UPDATE pending_actions SET status='approved', decided_at=now(), "
                "decided_by=%s, decision_note=%s WHERE action_id=%s",
                (decision.approver, decision.note, action_id))
            audit(cur, action_id, "approved", decision.approver, {"note": decision.note})
            M_ACTIONS.labels("approved").inc()

            # Externally-executed actions (e.g. send_email): stop at 'approved'. The worker
            # that owns the capability/credentials polls for these and calls /complete.
            if row["action_type"] not in INLINE_EXECUTE:
                conn.commit()
                log.info("action %s approved (awaiting external executor)", action_id)
                return {"action_id": action_id, "status": "approved", "result": None}

            # Inline-executed actions (refund/cancellation) — only reachable for an approved row.
            try:
                with tracer.start_as_current_span("execute_action") as es:
                    es.set_attribute("approval.action_type", row["action_type"])
                    result = execute_action(row["action_type"], row["payload"])
                cur.execute(
                    "UPDATE pending_actions SET status='executed', result=%s WHERE action_id=%s",
                    (Json(result), action_id))
                audit(cur, action_id, "executed", decision.approver, result)
                M_ACTIONS.labels("executed").inc()
                final_status = "executed"
            except Exception as e:  # noqa: BLE001
                log.exception("execution failed for %s", action_id)
                result = {"error": str(e)}
                cur.execute(
                    "UPDATE pending_actions SET status='failed', result=%s WHERE action_id=%s",
                    (Json(result), action_id))
                audit(cur, action_id, "execute_failed", decision.approver, result)
                final_status = "failed"
        conn.commit()
    log.info("action %s -> %s by %s", action_id, final_status, decision.approver)
    return {"action_id": action_id, "status": final_status, "result": result}


@app.post("/actions/{action_id}/reject")
def reject(action_id: str, decision: Decision):
    span = ot.get_current_span()
    span.set_attribute("approval.action_id", action_id)
    with db() as conn:
        with conn.cursor() as cur:
            _load_for_decision(cur, action_id)
            cur.execute(
                "UPDATE pending_actions SET status='rejected', decided_at=now(), "
                "decided_by=%s, decision_note=%s WHERE action_id=%s",
                (decision.approver, decision.note, action_id))
            audit(cur, action_id, "rejected", decision.approver, {"note": decision.note})
            M_ACTIONS.labels("rejected").inc()
        conn.commit()
    log.info("action %s rejected by %s", action_id, decision.approver)
    return {"action_id": action_id, "status": "rejected"}


class Completion(BaseModel):
    actor: str = "worker"
    result: dict = {}
    ok: bool = True


@app.post("/actions/{action_id}/complete")
def complete(action_id: str, c: Completion):
    """Called by the external executor (e.g. gmail-connector) after it performs an approved
    action. Only valid from 'approved' — so nothing is sent without a prior human approval."""
    span = ot.get_current_span()
    span.set_attribute("approval.action_id", action_id)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM pending_actions WHERE action_id=%s FOR UPDATE",
                        (action_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "action not found")
            if row["status"] != "approved":
                raise HTTPException(409, f"action is '{row['status']}', expected 'approved'")
            new_status = "executed" if c.ok else "failed"
            cur.execute(
                "UPDATE pending_actions SET status=%s, result=%s WHERE action_id=%s",
                (new_status, Json(c.result), action_id))
            audit(cur, action_id, "executed" if c.ok else "execute_failed", c.actor, c.result)
            M_ACTIONS.labels(new_status).inc()
        conn.commit()
    log.info("action %s completed -> %s by %s", action_id, new_status, c.actor)
    return {"action_id": action_id, "status": new_status}


@app.get("/", response_class=HTMLResponse)
def home():
    return HTML_PAGE


HTML_PAGE = """
<!doctype html><html><head><meta charset="utf-8"><title>Approval queue</title>
<style>
 body{font-family:system-ui,Arial,sans-serif;max-width:920px;margin:24px auto;padding:0 16px;color:#1a1a1a}
 h1{font-size:20px} .muted{color:#666;font-size:13px}
 .card{border:1px solid #ddd;border-radius:8px;padding:12px;margin-top:12px}
 .row{display:flex;justify-content:space-between;align-items:center;gap:12px}
 button{padding:6px 12px;font-size:13px;cursor:pointer;border-radius:6px;border:1px solid #bbb}
 .ok{background:#e8f5e9;border-color:#7cc47f} .no{background:#fdecea;border-color:#e09b94}
 .status{display:inline-block;border-radius:12px;padding:2px 10px;font-size:12px;background:#eef}
 .executed{background:#e8f5e9} .rejected{background:#fdecea} .failed{background:#fde7b0}
 code{background:#f0f0f0;padding:1px 5px;border-radius:4px;font-size:12px}
 pre{white-space:pre-wrap;background:#f7f7f7;padding:8px;border-radius:6px;font-size:12px}
</style></head><body>
<h1>Approval queue — human gate</h1>
<p class="muted">High-risk actions (refund / cancellation) the agent submitted. Nothing executes
until a human approves here. Approve runs the action and writes an audit record.</p>
<div class="row"><label><input type="checkbox" id="pendingOnly" checked onchange="load()"> pending only</label>
 <button onclick="load()">Refresh</button></div>
<div id="list"></div>
<script>
async function load(){
 const only=document.getElementById('pendingOnly').checked;
 const r=await fetch('/actions'+(only?'?status=pending':'')); const d=await r.json();
 const el=document.getElementById('list');
 if(!d.actions.length){el.innerHTML='<p class="muted">Nothing here.</p>';return;}
 el.innerHTML=d.actions.map(a=>`<div class="card">
   <div class="row"><div><b>${a.action_type}</b> · ticket ${a.ticket_id||'?'} ·
     <span class="status ${a.status}">${a.status}</span></div>
     <div>${a.status==='pending'?`<button class="ok" onclick="decide('${a.action_id}','approve')">Approve</button>
       <button class="no" onclick="decide('${a.action_id}','reject')">Reject</button>`:''}</div></div>
   <div class="muted">${a.reason||''}</div>
   <pre>action_id=${a.action_id}\\npayload=${JSON.stringify(a.payload)}${a.result?'\\nresult='+JSON.stringify(a.result):''}</pre>
 </div>`).join('');
}
async function decide(id,verb){
 const note=verb==='reject'?prompt('Reason for rejection?')||'':'';
 await fetch('/actions/'+id+'/'+verb,{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({approver:'operator',note:note})});
 load();
}
load();
</script></body></html>
"""

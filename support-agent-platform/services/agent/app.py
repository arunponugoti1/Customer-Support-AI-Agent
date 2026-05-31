"""Support Agent service — LangGraph orchestration over the LLM Proxy.

Flow (Phase 3, intent-driven):
    classify
      ├─ order_status ─▶ lookup (get_order_status tool) ─▶ retrieve ─▶ compose ─┐
      └─ else ──────────────────────────────────────────▶ retrieve ─▶ compose ─┤
                                                                                │
    compose ─┬─ refund/cancellation ─▶ gate (issue_refund stub BLOCKS + escalate) ─▶ END
             └─ else ──────────────────────────────────────────────────────────────▶ END

Every model call (classify, embed, draft) goes through the LLM Proxy, so all tokens +
cost are metered centrally and attributed to the ticket (task_id). Every graph node and
every tool call is wrapped in an OpenTelemetry span; the agent->proxy HTTP hop propagates
trace context, so one ticket = one distributed trace in Cloud Trace.

Tools are deliberately small: get_order_status is a mock, and issue_refund is a STUB that
*refuses to fire* without an approval record — that block is the hook Phase 4's approval
service will satisfy. Nothing risky auto-executes.
"""
import functools
import json
import logging
import operator
import os
import re
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, TypedDict

import psycopg
import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from google.cloud import secretmanager
from langgraph.graph import END, START, StateGraph
from opentelemetry import trace as ot
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from psycopg.rows import dict_row
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("agent")

# ── Config ───────────────────────────────────────────────────────────────────
PROJECT = os.environ["GCP_PROJECT"]
PROXY_URL = os.environ["PROXY_URL"]  # e.g. http://llm-proxy-llm-proxy.support-agent.svc.cluster.local
APPROVAL_URL = os.getenv("APPROVAL_URL", "")  # http://approval-approval.support-agent.svc.cluster.local
DB_HOST = os.environ["DB_HOST"]
DB_NAME = os.getenv("DB_NAME", "appdb")
DB_USER = os.getenv("DB_USER", "appuser")
DB_PASSWORD_SECRET = os.getenv("DB_PASSWORD_SECRET", "db-password")
EMBED_DIM = int(os.getenv("EMBED_DIM", "768"))
TOP_K = int(os.getenv("TOP_K", "3"))

# Pure routing helpers live in routing.py — unit-tested.
from routing import INTENTS, HIGH_RISK, extract_order_id, tier_for  # noqa: E402,F401

# Small starter knowledge base. Seeded into pgvector on first boot.
FAQ_SEED = [
    {"title": "Track your order",
     "content": "To track an order, open the shipping confirmation email and use the tracking link. Status can lag actual delivery by 1-2 days."},
    {"title": "Refund policy",
     "content": "Refunds are available within 30 days of delivery for unused items. Refunds are issued to the original payment method within 5-7 business days. Refunds require agent approval."},
    {"title": "Cancel an order",
     "content": "Orders can be cancelled before they ship. Once shipped, the order must be returned instead of cancelled. Cancellations that involve a refund require agent approval."},
    {"title": "Reset your password",
     "content": "Use the 'Forgot password' link on the sign-in page. A reset email arrives within a few minutes; check spam if missing."},
    {"title": "Shipping times",
     "content": "Standard shipping is 3-5 business days; express is 1-2. Delays can happen during peak periods or weather events."},
    {"title": "Missing package",
     "content": "If tracking shows delivered but the package is missing, check around the delivery location and with neighbors, then contact support with the order number."},
]

SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS faq (
  id        BIGSERIAL PRIMARY KEY,
  title     TEXT NOT NULL,
  content   TEXT NOT NULL,
  embedding vector({EMBED_DIM})
);
"""

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


def vec_literal(values: list[float]) -> str:
    return "[" + ",".join(str(v) for v in values) + "]"


# ── Proxy clients (every model call is metered there) ────────────────────────
def proxy_generate(messages, task_id, trace_id, model=None):
    payload = {"messages": messages, "task_id": task_id, "trace_id": trace_id}
    if model:
        payload["model"] = model  # route to a specific gateway tier
    r = requests.post(f"{PROXY_URL}/generate", json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def proxy_embed(texts, task_id, trace_id):
    r = requests.post(f"{PROXY_URL}/embed",
                      json={"texts": texts, "task_id": task_id, "trace_id": trace_id},
                      timeout=60)
    r.raise_for_status()
    return r.json()


# ── Tracing (OpenTelemetry -> Cloud Trace) ────────────────────────────────────
# Workload Identity already grants roles/cloudtrace.agent. The agent->proxy calls go
# through the auto-instrumented `requests` library, which injects W3C trace context, so
# the proxy's spans nest under this trace. Set ENABLE_TRACING=false for local runs.
ENABLE_TRACING = os.getenv("ENABLE_TRACING", "true").lower() == "true"
tracer = ot.get_tracer("agent")


def setup_tracing(fastapi_app: FastAPI) -> None:
    if not ENABLE_TRACING:
        log.info("tracing disabled (ENABLE_TRACING=false)")
        return
    provider = TracerProvider(resource=Resource.create({"service.name": "support-agent"}))
    provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter(project_id=PROJECT)))
    ot.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(fastapi_app)
    RequestsInstrumentor().instrument()
    log.info("tracing enabled -> Cloud Trace (project=%s)", PROJECT)


def traced_node(name: str):
    """Wrap a graph node so it runs inside its own span; records intent/cost attrs."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(state: "State"):
            with tracer.start_as_current_span(f"node.{name}") as span:
                span.set_attribute("ticket_id", state.get("ticket_id", ""))
                result = fn(state)
                if "intent" in result:
                    span.set_attribute("intent", result["intent"])
                if "cost" in result:
                    span.set_attribute("cost_usd", float(result["cost"]))
                return result
        return wrapper
    return deco


# ── Tools ─────────────────────────────────────────────────────────────────────
# Each tool runs inside its own span (run_tool) so every action is visible in the trace.
# (extract_order_id lives in routing.py)


def tool_get_order_status(order_id: str) -> dict:
    """MOCK order-status lookup — Layer 3 has no real OMS. Deterministic fake status."""
    statuses = ["processing", "shipped", "out_for_delivery", "delivered", "delayed"]
    h = sum(ord(c) for c in order_id)
    return {"order_id": order_id, "status": statuses[h % len(statuses)],
            "carrier": "ACME-Express", "eta_days": (h % 5) + 1}


def tool_request_approval(ticket_id: str, trace_id: str, action_type: str, order_id: str) -> dict:
    """Submit a high-risk action to the approval service as a PENDING record. The agent
    has no power to execute it — only the approval service can, and only after a human
    approves. That is the sandbox: refunds are impossible without an approved record."""
    if not APPROVAL_URL:
        return {"status": "blocked", "reason": "approval service not configured (APPROVAL_URL unset)"}
    r = requests.post(
        f"{APPROVAL_URL}/actions",
        json={"ticket_id": ticket_id, "trace_id": trace_id, "action_type": action_type,
              "payload": {"order_id": order_id},
              "reason": f"{action_type} request requires human approval"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()  # {action_id, status: 'pending', action_type}


def run_tool(name: str, fn, **kwargs) -> dict:
    with tracer.start_as_current_span(f"tool.{name}") as span:
        for k, v in kwargs.items():
            span.set_attribute(f"tool.arg.{k}", str(v))
        result = fn(**kwargs)
        span.set_attribute("tool.result.status", str(result.get("status", "")))
        return result


def seed_faq_if_empty():
    with db() as conn:
        conn.execute(SCHEMA)
        conn.commit()
        n = conn.execute("SELECT count(*) AS n FROM faq").fetchone()["n"]
        if n:
            log.info("faq already seeded (%d rows)", n)
            return
        emb = proxy_embed([f["title"] + ". " + f["content"] for f in FAQ_SEED],
                          task_id="seed", trace_id="seed")["embeddings"]
        with conn.cursor() as cur:
            for f, e in zip(FAQ_SEED, emb):
                cur.execute(
                    "INSERT INTO faq (title, content, embedding) VALUES (%s,%s,%s::vector)",
                    (f["title"], f["content"], vec_literal(e)),
                )
        conn.commit()
        log.info("seeded %d faq rows", len(FAQ_SEED))


# ── LangGraph state + nodes ──────────────────────────────────────────────────
class State(TypedDict):
    ticket: str
    ticket_id: str
    trace_id: str
    intent: str
    faq: list
    draft: str
    order_info: dict
    action: str
    action_id: str
    requires_approval: bool
    steps: Annotated[list, operator.add]
    cost: Annotated[float, operator.add]


# HIGH_RISK imported from routing.py


@traced_node("classify")
def classify(state: State):
    msgs = [
        {"role": "system", "content": f"Classify the support ticket into exactly one of: {', '.join(INTENTS)}. Reply with ONLY the label."},
        {"role": "user", "content": state["ticket"]},
    ]
    out = proxy_generate(msgs, state["ticket_id"], state["trace_id"], model="fast")  # classify is easy
    label = out["content"].strip().lower().split()[0] if out["content"] else "other"
    intent = label if label in INTENTS else "other"
    return {"intent": intent, "cost": out["cost_usd"]["total"],
            "steps": [{"node": "classify", "intent": intent, "model": out.get("model"),
                       "cost_usd": out["cost_usd"]["total"]}]}


@traced_node("lookup")
def lookup(state: State):
    """Tool node: look up order status (only reached for order_status tickets)."""
    oid = extract_order_id(state["ticket"])
    info = run_tool("get_order_status", tool_get_order_status, order_id=oid)
    return {"order_info": info,
            "steps": [{"node": "lookup", "tool": "get_order_status",
                       "order_id": oid, "status": info["status"]}]}


@traced_node("retrieve")
def retrieve(state: State):
    emb = proxy_embed([state["ticket"]], state["ticket_id"], state["trace_id"])
    qvec = vec_literal(emb["embeddings"][0])
    with db() as conn:
        rows = conn.execute(
            "SELECT title, content, embedding <=> %s::vector AS distance "
            "FROM faq ORDER BY distance ASC LIMIT %s",
            (qvec, TOP_K),
        ).fetchall()
    faq = [{"title": r["title"], "content": r["content"], "distance": round(float(r["distance"]), 4)} for r in rows]
    return {"faq": faq, "cost": emb["cost_usd"],
            "steps": [{"node": "retrieve", "faq_titles": [f["title"] for f in faq], "cost_usd": emb["cost_usd"]}]}


@traced_node("compose")
def draft(state: State):
    context = "\n".join(f"- {f['title']}: {f['content']}" for f in state["faq"])
    extra = ""
    if state.get("order_info"):
        oi = state["order_info"]
        extra = (f"\n\nORDER LOOKUP RESULT: order {oi['order_id']} is '{oi['status']}', "
                 f"carrier {oi['carrier']}, ETA ~{oi['eta_days']} day(s). Use this in your reply.")
    msgs = [
        {"role": "system", "content": (
            "You are a support agent. Use ONLY the knowledge base below to answer. "
            "Be concise and friendly. If the request needs a refund or cancellation, say you will "
            "escalate it for approval rather than promising it.\n\nKNOWLEDGE BASE:\n" + context + extra)},
        {"role": "user", "content": state["ticket"]},
    ]
    tier = tier_for(state["intent"])  # route by difficulty/stakes
    out = proxy_generate(msgs, state["ticket_id"], state["trace_id"], model=tier)
    return {"draft": out["content"], "cost": out["cost_usd"]["total"],
            "steps": [{"node": "draft", "model": out.get("model"), "cost_usd": out["cost_usd"]["total"]}]}


@traced_node("gate")
def gate(state: State):
    """High-risk path: submit the action to the approval service as a PENDING record and
    stop. The agent cannot execute a refund — only the approval service can, and only after
    a human approves. Nothing risky auto-fires."""
    oid = extract_order_id(state["ticket"])
    out = run_tool("request_approval", tool_request_approval,
                   ticket_id=state["ticket_id"], trace_id=state["trace_id"],
                   action_type=state["intent"], order_id=oid)
    action_id = out.get("action_id", "")
    blocked = out.get("status") == "blocked"
    return {"action": "blocked" if blocked else "pending_approval",
            "action_id": action_id, "requires_approval": True,
            "steps": [{"node": "gate", "tool": "request_approval",
                       "action_id": action_id, "status": out.get("status")}]}


def route_after_classify(state: State) -> str:
    return "lookup" if state["intent"] == "order_status" else "retrieve"


def route_after_compose(state: State) -> str:
    return "gate" if state["intent"] in HIGH_RISK else END


def build_graph():
    g = StateGraph(State)
    g.add_node("classify", classify)
    g.add_node("lookup", lookup)
    g.add_node("retrieve", retrieve)
    g.add_node("compose", draft)  # node id must not equal a state key ("draft")
    g.add_node("gate", gate)
    g.add_edge(START, "classify")
    g.add_conditional_edges("classify", route_after_classify,
                            {"lookup": "lookup", "retrieve": "retrieve"})
    g.add_edge("lookup", "retrieve")
    g.add_edge("retrieve", "compose")
    g.add_conditional_edges("compose", route_after_compose,
                            {"gate": "gate", END: END})
    g.add_edge("gate", END)
    return g.compile()


GRAPH = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global DB_PASSWORD, GRAPH
    DB_PASSWORD = fetch_db_password()
    seed_faq_if_empty()
    GRAPH = build_graph()
    log.info("agent ready: proxy=%s", PROXY_URL)
    yield


app = FastAPI(title="support-agent", lifespan=lifespan)
setup_tracing(app)


class HandleRequest(BaseModel):
    ticket: str
    ticket_id: str | None = None


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/handle")
def handle(req: HandleRequest):
    ticket_id = req.ticket_id or f"ticket-{uuid.uuid4().hex[:8]}"
    trace_id = uuid.uuid4().hex

    # The real distributed-trace id (hex) — lets you open this ticket in Cloud Trace.
    span_ctx = ot.get_current_span().get_span_context()
    otel_trace_id = format(span_ctx.trace_id, "032x") if span_ctx.trace_id else None
    span = ot.get_current_span()
    span.set_attribute("ticket_id", ticket_id)

    result = GRAPH.invoke({
        "ticket": req.ticket, "ticket_id": ticket_id, "trace_id": trace_id,
        "intent": "", "faq": [], "draft": "", "order_info": {},
        "action": "none", "action_id": "", "requires_approval": False,
        "steps": [], "cost": 0.0,
    })
    span.set_attribute("intent", result["intent"])
    span.set_attribute("requires_approval", bool(result["requires_approval"]))

    return {
        "ticket_id": ticket_id,
        "trace_id": otel_trace_id,
        "intent": result["intent"],
        "order_info": result["order_info"] or None,
        "faq_used": result["faq"],
        "draft": result["draft"],
        "action": result["action"],
        "action_id": result["action_id"] or None,
        "requires_approval": result["requires_approval"],
        "steps": result["steps"],
        "total_cost_usd": round(result["cost"], 6),
    }


@app.get("/", response_class=HTMLResponse)
def home():
    return HTML_PAGE


HTML_PAGE = """
<!doctype html><html><head><meta charset="utf-8"><title>Support Agent — test</title>
<style>
 body{font-family:system-ui,Arial,sans-serif;max-width:820px;margin:24px auto;padding:0 16px;color:#1a1a1a}
 h1{font-size:20px} textarea{width:100%;height:90px;font-size:14px;padding:8px}
 button{margin-top:8px;padding:8px 16px;font-size:14px;cursor:pointer}
 .card{border:1px solid #ddd;border-radius:8px;padding:12px;margin-top:12px}
 .muted{color:#666;font-size:13px} pre{white-space:pre-wrap;background:#f7f7f7;padding:10px;border-radius:6px}
 .pill{display:inline-block;background:#eef;border-radius:12px;padding:2px 10px;font-size:13px;margin-right:6px}
 .step{font-size:13px;border-left:3px solid #88a;padding-left:8px;margin:6px 0}
 .gate{font-size:13px;border-left:3px solid #c33;background:#fff4f4}
 .banner{background:#fff4e5;border:1px solid #f0c36d;border-radius:6px;padding:8px 12px;margin-top:12px;font-size:14px}
 code{background:#f0f0f0;padding:1px 5px;border-radius:4px;font-size:12px}
</style></head><body>
<h1>Support Agent — Phase 3 test</h1>
<p class="muted">Paste a support ticket. The agent classifies it, optionally calls tools
(order lookup), retrieves FAQ via pgvector, drafts a reply, and routes high-risk requests
(refund / cancellation) to a human-approval gate. Every model call is metered through the
LLM Proxy and every step is a span in one Cloud Trace.</p>
<textarea id="t">My order #4471 hasn't arrived and I want a refund.</textarea><br>
<button onclick="go()">Handle ticket</button>
<div id="out"></div>
<script>
function summarize(s){
 const skip={node:1,cost_usd:1};
 const parts=Object.keys(s).filter(k=>!skip[k]).map(k=>`${k}=${Array.isArray(s[k])?s[k].join('/'):s[k]}`);
 return parts.join(', ');
}
async function go(){
 const out=document.getElementById('out'); out.innerHTML='<p class="muted">Working…</p>';
 try{
  const r=await fetch('/handle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket:document.getElementById('t').value})});
  const d=await r.json();
  let steps=d.steps.map(s=>`<div class="step ${s.node==='gate'?'gate':''}"><b>${s.node}</b> ${summarize(s)} <span class="muted">($${(s.cost_usd||0).toFixed(6)})</span></div>`).join('');
  let faq=(d.faq_used||[]).map(f=>`<span class="pill">${f.title} (${f.distance})</span>`).join(' ');
  let order=d.order_info?`<p class="muted">Order ${d.order_info.order_id}: <b>${d.order_info.status}</b> via ${d.order_info.carrier}, ETA ~${d.order_info.eta_days}d</p>`:'';
  let banner=d.requires_approval?`<div class="banner">⛔ <b>High-risk — submitted to the human-approval gate.</b> Action: <b>${d.action}</b>${d.action_id?` · <code>${d.action_id}</code>`:''}. Nothing fired; only the approval service can execute it, and only after a human approves it in the Approval queue.</div>`:'';
  out.innerHTML=`<div class="card"><b>Intent:</b> ${d.intent} &nbsp; <b>Ticket:</b> ${d.ticket_id} &nbsp; <b>Total cost:</b> $${d.total_cost_usd}
   <br><span class="muted">Trace: <code>${d.trace_id||'(tracing off)'}</code> — find it in Cloud Trace</span>
   ${banner}
   <h3>Drafted reply</h3><pre>${(d.draft||'').replace(/</g,'&lt;')}</pre>
   ${order}
   <h3>FAQ retrieved</h3>${faq}
   <h3>Steps</h3>${steps}</div>`;
 }catch(e){out.innerHTML='<p style="color:#b00">Error: '+e+'</p>';}
}
</script></body></html>
"""

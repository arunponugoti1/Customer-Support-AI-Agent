"use client";
import { useEffect, useState } from "react";

const usd = (n) => "$" + Number(n || 0).toFixed(6);

function Flow({ steps }) {
  return (
    <div className="flow">
      {steps.map((s, i) => (
        <span key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {i > 0 && <span className="arrow">→</span>}
          <span className={"node" + (s.node === "gate" ? " gate" : "")}>
            {s.node}
            {s.intent ? ` · ${s.intent}` : ""}
            {s.model ? ` · 🧠${s.model}` : ""}
            {s.tool ? ` · ${s.tool}` : ""}
            {s.status ? ` · ${s.status}` : ""}
            {typeof s.cost_usd === "number" && s.cost_usd > 0 && (
              <small> ({usd(s.cost_usd)})</small>
            )}
          </span>
        </span>
      ))}
    </div>
  );
}

function HandleTab({ onHandled }) {
  const [ticket, setTicket] = useState("My order #4471 hasn't arrived and I want a refund.");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);

  async function go() {
    setBusy(true); setErr(null); setRes(null);
    try {
      const r = await fetch("/api/handle", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticket }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
      setRes(d);
      onHandled && onHandled();
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }

  return (
    <div>
      <div className="card">
        <h2>Submit a support ticket</h2>
        <textarea value={ticket} onChange={(e) => setTicket(e.target.value)} />
        <br />
        <button className="primary" onClick={go} disabled={busy}>
          {busy ? "Working…" : "Handle ticket"}
        </button>
      </div>

      {err && <div className="card err">Error: {err}</div>}

      {res && (
        <div className="card">
          <div className="row">
            <div><b>Intent:</b> {res.intent} &nbsp; <b>Ticket:</b> {res.ticket_id} &nbsp;
              <b>Cost:</b> {usd(res.total_cost_usd)}</div>
            <span className="muted">trace <code>{res.trace_id || "(off)"}</code></span>
          </div>

          <h2 style={{ marginTop: 12 }}>Flow</h2>
          <Flow steps={res.steps || []} />

          {res.requires_approval && (
            <div className="banner">
              ⛔ <b>High-risk — sent to the approval gate.</b> Action: <b>{res.action}</b>
              {res.action_id && <> · <code>{res.action_id}</code></>}. Nothing fired; approve it
              in the <b>Approvals</b> tab to execute.
            </div>
          )}

          <h2 style={{ marginTop: 12 }}>Drafted reply</h2>
          <pre>{res.draft}</pre>

          {res.order_info && (
            <p className="muted">Order {res.order_info.order_id}: <b>{res.order_info.status}</b> via{" "}
              {res.order_info.carrier}, ETA ~{res.order_info.eta_days}d</p>
          )}

          <h2 style={{ marginTop: 12 }}>FAQ retrieved</h2>
          <div>{(res.faq_used || []).map((f, i) => (
            <span className="pill" key={i}>{f.title} ({f.distance})</span>
          ))}</div>
        </div>
      )}
    </div>
  );
}

function ApprovalsTab() {
  const [pendingOnly, setPendingOnly] = useState(true);
  const [actions, setActions] = useState([]);
  const [err, setErr] = useState(null);

  async function load() {
    setErr(null);
    try {
      const r = await fetch("/api/actions" + (pendingOnly ? "?status=pending" : ""));
      const d = await r.json();
      setActions(d.actions || []);
    } catch (e) { setErr(String(e)); }
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [pendingOnly]);

  async function decide(id, verb) {
    const note = verb === "reject" ? (prompt("Reason for rejection?") || "") : "";
    await fetch(`/api/actions/${id}/${verb}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approver: "operator", note }),
    });
    load();
  }

  return (
    <div>
      <div className="row">
        <label><input type="checkbox" checked={pendingOnly}
          onChange={(e) => setPendingOnly(e.target.checked)} /> pending only</label>
        <button className="primary" onClick={load}>Refresh</button>
      </div>
      {err && <div className="card err">Error: {err}</div>}
      {!actions.length && <div className="card muted">Nothing here.</div>}
      {actions.map((a) => (
        <div className="card" key={a.action_id}>
          <div className="row">
            <div>
              <b>{a.action_type}</b> · ticket {a.ticket_id || "?"} ·{" "}
              <span className={"status " + a.status}>{a.status}</span>
            </div>
            {a.status === "pending" && (
              <div className="btns">
                <button className="ok" onClick={() => decide(a.action_id, "approve")}>Approve</button>
                <button className="no" onClick={() => decide(a.action_id, "reject")}>Reject</button>
              </div>
            )}
          </div>
          <div className="muted">{a.reason}</div>
          <pre>action_id={a.action_id}{"\n"}payload={JSON.stringify(a.payload)}
            {a.result ? "\nresult=" + JSON.stringify(a.result) : ""}</pre>
        </div>
      ))}
    </div>
  );
}

function CostsTab() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  async function load() {
    setErr(null);
    try { const r = await fetch("/api/costs"); setData(await r.json()); }
    catch (e) { setErr(String(e)); }
  }
  useEffect(() => { load(); }, []);

  return (
    <div>
      <div className="row"><h2>Cost — metered at the LLM Proxy</h2>
        <button className="primary" onClick={load}>Refresh</button></div>
      {err && <div className="card err">Error: {err}</div>}
      {data && (
        <>
          <div className="grid3">
            <div className="card"><div className="muted">Total calls</div>
              <div className="big">{data.totals?.calls ?? 0}</div></div>
            <div className="card"><div className="muted">Total tokens</div>
              <div className="big">{data.totals?.tokens ?? 0}</div></div>
            <div className="card"><div className="muted">Total cost</div>
              <div className="big">${Number(data.totals?.cost_usd || 0).toFixed(4)}</div></div>
          </div>
          <div className="card">
            <h2>Cost per ticket</h2>
            <table>
              <thead><tr><th>task_id</th><th>calls</th><th>cost</th></tr></thead>
              <tbody>
                {(data.per_task || []).map((t, i) => (
                  <tr key={i}><td><code>{t.task_id || "(none)"}</code></td>
                    <td>{t.calls}</td><td>${Number(t.cost_usd || 0).toFixed(6)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

export default function Page() {
  const [tab, setTab] = useState("handle");
  const [refreshKey, setRefreshKey] = useState(0);
  return (
    <div className="wrap">
      <h1>Support Agent — Console</h1>
      <p className="muted">One pane over the platform: submit a ticket and watch the flow,
        approve high-risk actions at the human gate, and track per-ticket cost. The browser
        only talks to this app; it proxies to the internal agent / approval / proxy services.</p>

      <div className="tabs">
        <button className={tab === "handle" ? "active" : ""} onClick={() => setTab("handle")}>Handle ticket</button>
        <button className={tab === "approvals" ? "active" : ""} onClick={() => setTab("approvals")}>Approvals</button>
        <button className={tab === "costs" ? "active" : ""} onClick={() => setTab("costs")}>Costs</button>
      </div>

      {tab === "handle" && <HandleTab onHandled={() => setRefreshKey((k) => k + 1)} />}
      {tab === "approvals" && <ApprovalsTab key={refreshKey} />}
      {tab === "costs" && <CostsTab />}
    </div>
  );
}

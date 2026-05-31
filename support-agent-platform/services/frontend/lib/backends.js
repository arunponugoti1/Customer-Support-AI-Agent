// Internal service URLs. The SPA never calls these directly — it calls same-origin
// /api/* routes, which run server-side inside the cluster and proxy here. This keeps
// agent / approval / llm-proxy private (ClusterIP) and avoids CORS.
export const AGENT_URL =
  process.env.AGENT_URL || "http://agent-agent.support-agent.svc.cluster.local";
export const APPROVAL_URL =
  process.env.APPROVAL_URL || "http://approval-approval.support-agent.svc.cluster.local";
export const PROXY_URL =
  process.env.PROXY_URL || "http://llm-proxy-llm-proxy.support-agent.svc.cluster.local";

// Proxy a fetch Response straight back to the browser, preserving status.
export async function relay(upstream) {
  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") || "application/json" },
  });
}

import { AGENT_URL, relay } from "../../../lib/backends";

export const dynamic = "force-dynamic";

export async function POST(req) {
  const body = await req.json();
  const upstream = await fetch(`${AGENT_URL}/handle`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  return relay(upstream);
}

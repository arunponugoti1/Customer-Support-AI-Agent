import { APPROVAL_URL, relay } from "../../../../../lib/backends";

export const dynamic = "force-dynamic";

export async function POST(req, { params }) {
  const body = await req.json().catch(() => ({}));
  const upstream = await fetch(`${APPROVAL_URL}/actions/${params.id}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
    cache: "no-store",
  });
  return relay(upstream);
}

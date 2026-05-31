import { APPROVAL_URL, relay } from "../../../lib/backends";

export const dynamic = "force-dynamic";

export async function GET(req) {
  const { searchParams } = new URL(req.url);
  const status = searchParams.get("status");
  const url = `${APPROVAL_URL}/actions${status ? `?status=${encodeURIComponent(status)}` : ""}`;
  const upstream = await fetch(url, { cache: "no-store" });
  return relay(upstream);
}

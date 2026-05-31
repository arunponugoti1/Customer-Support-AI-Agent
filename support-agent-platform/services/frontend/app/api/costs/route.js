import { PROXY_URL, relay } from "../../../lib/backends";

export const dynamic = "force-dynamic";

export async function GET() {
  const upstream = await fetch(`${PROXY_URL}/costs/summary`, { cache: "no-store" });
  return relay(upstream);
}

import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only. Mirrors /api/sharp/market/audit: one asset's
// full evidence, for checking a published number against the rosters
// it came from.
export const dynamic = "force-dynamic";
export const revalidate = 0;

const NO_STORE_HEADERS = {
  "Cache-Control": "private, no-store, no-cache, max-age=0, must-revalidate",
  Pragma: "no-cache",
};

export async function GET(request) {
  const incoming = new URL(request.url).searchParams;
  const searchParams = Object.fromEntries(incoming.entries());
  try {
    const { data, status } = await proxyGet("/api/sharp/roster-percentage/audit", {
      cookie: request.headers.get("cookie") || "",
      timeoutMs: 20000,
      searchParams,
    });
    return NextResponse.json(data, { status, headers: NO_STORE_HEADERS });
  } catch (err) {
    return NextResponse.json(
      { error: "sharp_roster_percentage_unavailable", detail: err?.message },
      { status: 503, headers: NO_STORE_HEADERS },
    );
  }
}

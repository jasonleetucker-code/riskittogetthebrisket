import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. The board is three pipeline passes over the payload on a
// cold cache, hence the long timeout.
export async function GET(request) {
  try {
    const searchParams = {};
    for (const key of ["leagueKey", "limit"]) {
      const value = request?.nextUrl?.searchParams?.get(key);
      if (value) searchParams[key] = value;
    }
    const { data, status } = await proxyGet("/api/consensus-edge/methodology", {
      searchParams,
      timeoutMs: 30000,
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "consensus_edge_unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}

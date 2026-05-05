import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Sandbox endpoint — read-only.  The backend never mutates live values
// from this path; the proxy is just a Next-side passthrough so the
// browser doesn't need a separate origin for the FastAPI backend.
export async function GET(request) {
  const url = new URL(request.url);
  const leagueKey = url.searchParams.get("leagueKey");
  const searchParams = leagueKey ? { leagueKey } : undefined;
  try {
    const { data, status } = await proxyGet("/api/te-premium/overview", {
      timeoutMs: 8000,
      searchParams,
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "TE Premium service unavailable", detail: err?.message || String(err) },
      { status: 503 },
    );
  }
}

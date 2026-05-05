import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

export async function GET(request) {
  const url = new URL(request.url);
  const leagueKey = url.searchParams.get("leagueKey");
  const searchParams = leagueKey ? { leagueKey } : undefined;
  try {
    const { data, status } = await proxyGet("/api/te-premium/source-comparison", {
      timeoutMs: 10000,
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

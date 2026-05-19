import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

export async function GET(request) {
  try {
    // Forward the optional stable league key so league-scoped callers
    // (e.g. the trade page's stack effect) get THEIR league's board,
    // not the server-resolved default.  Omitted → backend resolves as
    // before (unchanged for the unscoped DraftCapitalSection).
    const leagueKey = request?.nextUrl?.searchParams?.get("leagueKey");
    const { data, status } = await proxyGet(
      "/api/draft-capital",
      leagueKey ? { searchParams: { leagueKey } } : undefined,
    );
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "Draft capital service unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}

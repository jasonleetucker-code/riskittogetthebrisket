import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI.  Deliberately forwards NO leagueKey: Sharp Tracker's cohort
// is global, and scoping it to a league would rebuild the merged
// feature that /league/insider-trading was split out of.
export async function GET() {
  try {
    const { data, status } = await proxyGet("/api/sharp/cohort", { timeoutMs: 15000 });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "sharp_unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}

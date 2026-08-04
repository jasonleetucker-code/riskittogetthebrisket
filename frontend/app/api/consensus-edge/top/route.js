import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to FastAPI.
//
// Forwards no leagueKey: Consensus Edge scores the shared scoring-profile board,
// not a league's rosters. The league-adjusted lens is a separate overlay and is
// not wired here while the model is in shadow mode.
export async function GET() {
  try {
    const { data, status } = await proxyGet("/api/consensus-edge/top", { timeoutMs: 20000 });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "consensus_edge_unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}

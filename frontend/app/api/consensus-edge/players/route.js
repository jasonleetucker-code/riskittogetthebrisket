import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. The board is three pipeline passes over the payload on a
// cold cache, hence the long timeout.
export async function GET(request) {
  try {
    // No leagueKey. The backend never read it, and forwarding a
    // parameter the answer does not depend on tells a caller the answer
    // is league-specific when it is not — see the note in
    // consensus_edge/scoring_fit.py. This board follows the SCORING
    // PROFILE (the repo's core split: rankings follow scoring, context
    // follows league), and its one league-dependent input reads the
    // canonical league config directly.
    const searchParams = {};
    const { data, status } = await proxyGet("/api/consensus-edge/players", {
      cookie: request.headers.get("cookie") || "",
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

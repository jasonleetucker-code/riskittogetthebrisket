import { NextResponse } from "next/server";
import { proxyPost } from "@/lib/backend-proxy";

// Sandbox-only POST.  The backend handler in
// ``server.py::post_te_premium_run_analysis`` never mutates live
// player values — it computes the scenario, returns the payload, and
// optionally writes a side-car JSON to ``data/sandbox/te_premium/``
// (a directory the live ``/api/data`` pipeline does not read).
export async function POST(request) {
  let body = {};
  try {
    body = await request.json();
  } catch {
    body = {};
  }
  // Forward ``leagueKey`` from the query string when present so this
  // POST proxy resolves the league the same way the sibling GET
  // proxies do (overview / source-comparison / league-scenarios all
  // forward the query param).  The backend's
  // ``_resolve_league_for_request`` checks the body too, so we merge
  // it in only when not already set so an explicit body value wins.
  // Codex P2 review on PR #392.
  try {
    const url = new URL(request.url);
    const leagueKey = url.searchParams.get("leagueKey");
    if (leagueKey && !body.leagueKey) {
      body = { ...body, leagueKey };
    }
  } catch {
    // URL parse failure → fall through with the body as-is.
  }
  try {
    const { data, status } = await proxyPost("/api/te-premium/run-analysis", body, {
      timeoutMs: 15000,
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "TE Premium service unavailable", detail: err?.message || String(err) },
      { status: 503 },
    );
  }
}

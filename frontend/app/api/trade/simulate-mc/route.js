import { NextResponse } from "next/server";
import { proxyPost } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI.  Without it POST /api/trade/simulate-mc is a 404 through the
// :3000 origin the page is actually served from, so MonteCarloButton —
// which fetches the relative path — was dead outside a reverse-proxied
// deployment (W09-F016).
//
// The cookie MUST be forwarded: the backend route is behind
// `_get_auth_session` and answers 401 without it.
//
// The timeout mirrors SIMULATE_MC_TIMEOUT_SECONDS (10s) plus headroom;
// the backend already returns a clean 504 of its own past that budget.
export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_json" }, { status: 400 });
  }
  try {
    const { data, status } = await proxyPost("/api/trade/simulate-mc", body, {
      timeoutMs: 15000,
      headers: { cookie: request.headers.get("cookie") || "" },
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "simulate_unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}

import { NextResponse } from "next/server";

// DEV-ONLY bridge for the Brisket Trade Advisor's public endpoints
// (design §7, §8.2).  In production nginx sends every /api/ request to
// FastAPI, so these never run there — and they REFUSE to (404) when
// NODE_ENV is "production": a Next-side proxy would reach the backend from
// loopback, collapsing every visitor onto one rate-limit key and bypassing
// the trusted-proxy client-IP rules the advisor's abuse controls rely on.
//
// Forwards only the body, Content-Type and the query string.  No cookies
// (the advisor is anonymous), no client-IP headers.

const BACKEND_BASE = (() => {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
})();

const NOT_FOUND = { error: "not_found", message: "Not found." };

export function advisorBridgeDisabled() {
  return process.env.NODE_ENV === "production";
}

export async function forwardAdvisor(req, backendPath) {
  if (advisorBridgeDisabled()) {
    return NextResponse.json(NOT_FOUND, { status: 404, headers: { "cache-control": "no-store" } });
  }
  const url = new URL(req.url);
  const qs = url.searchParams.toString();
  const target = `${BACKEND_BASE}${backendPath}${qs ? `?${qs}` : ""}`;
  const init = { method: req.method, cache: "no-store" };
  if (req.method === "POST") {
    init.headers = { "content-type": req.headers.get("content-type") || "" };
    init.body = await req.text();
  }
  try {
    const res = await fetch(target, init);
    const body = await res.text();
    const headers = new Headers();
    for (const name of ["content-type", "cache-control", "retry-after"]) {
      const v = res.headers.get(name);
      if (v) headers.set(name, v);
    }
    return new NextResponse(body, { status: res.status, headers });
  } catch {
    // Fixed text: never echo the connection error.
    return NextResponse.json(
      { error: "advisor_unavailable", message: "The trade advisor is not available.", reason: "upstream_unavailable" },
      { status: 502, headers: { "cache-control": "no-store" } },
    );
  }
}

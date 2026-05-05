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

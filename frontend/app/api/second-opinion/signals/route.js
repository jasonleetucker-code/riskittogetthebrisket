import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. Authenticated backend endpoint, so the cookie is forwarded.
// Owner: src/sources/signals.py (rank-only, non-voting second opinion).
export async function GET(request) {
  try {
    const { data, status } = await proxyGet("/api/second-opinion/signals", {
      cookie: request.headers.get("cookie") || "",
      timeoutMs: 10000,
    });
    return NextResponse.json(data, {
      status,
      headers: { "Cache-Control": "private, no-store" },
    });
  } catch (err) {
    return NextResponse.json(
      { error: "signals_unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}

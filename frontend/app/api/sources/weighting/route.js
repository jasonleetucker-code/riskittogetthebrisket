import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev/E2E bridge for GET /api/sources/weighting (Source Health page).
//
// In production nginx routes /api/* straight to FastAPI and this file is
// never reached; it exists so /tools/source-health works where Next serves
// /api/* itself (dev and the E2E stack).
//
// PRIVATE: the backend endpoint is session-gated (methodology), so the
// caller's cookie is forwarded.
//
// Mirrored backend endpoint: server.py::get_source_weighting()
// Payload owner: src/api/source_weighting_explain.py::source_table()
export const dynamic = "force-dynamic";

export async function GET(request) {
  try {
    const { data, status } = await proxyGet("/api/sources/weighting", {
      cookie: request.headers.get("cookie") || "",
      timeoutMs: 10000,
    });
    return NextResponse.json(data, {
      status,
      headers: { "Cache-Control": "no-store, private" },
    });
  } catch (err) {
    return NextResponse.json(
      { error: "source_weighting_unavailable", detail: err?.message },
      { status: 503, headers: { "Cache-Control": "no-store, private" } },
    );
  }
}

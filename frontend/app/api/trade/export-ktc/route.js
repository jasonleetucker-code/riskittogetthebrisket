import { NextResponse } from "next/server";
import { proxyPost } from "@/lib/backend-proxy";

// Dev/E2E bridge for POST /api/trade/export-ktc ("Copy KTC URL" on /trade).
//
// In production nginx routes /api/* straight to FastAPI and this file is
// never reached.  Where Next serves /api/* itself (dev, the E2E stack) the
// route did not exist, so the export button 404'd there.  Session-gated
// backend route — the caller's cookie is forwarded.
//
// Mirrored backend endpoint: server.py::post_trade_export_ktc()
export const dynamic = "force-dynamic";

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Invalid JSON body" }, { status: 400 });
  }
  try {
    const { data, status } = await proxyPost("/api/trade/export-ktc", body, {
      cookie: request.headers.get("cookie") || "",
      timeoutMs: 20_000,
    });
    return NextResponse.json(data, { status, headers: { "Cache-Control": "no-store, private" } });
  } catch (err) {
    const aborted = err?.name === "AbortError";
    return NextResponse.json(
      {
        ok: false,
        error: aborted ? "KTC export timed out (20s)." : "KTC export service unavailable",
        detail: err?.message,
      },
      { status: aborted ? 504 : 503 },
    );
  }
}

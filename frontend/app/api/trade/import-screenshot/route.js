// Proxy for POST /api/trade/import-screenshot — forwards one downscaled
// screenshot (base64 in JSON) to the FastAPI backend, which reads asset
// names and sides from it.  Screenshots supply identities only; the
// browser joins them to board rows and the calculator stays the engine.
//
// Thin pass-through.  In production nginx routes /api/* straight to
// FastAPI and this file is never reached; it serves dev and the E2E
// stack.  The backend route is session-gated, so the caller's cookie is
// forwarded (frontend/__tests__/bridge-routes-forward-cookies.test.js).

import { NextResponse } from "next/server";
import { proxyPost } from "@/lib/backend-proxy";

export const dynamic = "force-dynamic";

// OCR on a large screenshot can take several seconds on a cold worker.
const TIMEOUT_MS = 30_000;

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { ok: false, error: "invalid_json", message: "Invalid JSON body" },
      { status: 400 },
    );
  }

  try {
    const { data, status } = await proxyPost(
      "/api/trade/import-screenshot",
      body,
      {
        cookie: request.headers.get("cookie") || "",
        timeoutMs: TIMEOUT_MS,
      },
    );
    return NextResponse.json(data, {
      status,
      headers: { "Cache-Control": "no-store, private" },
    });
  } catch (err) {
    const aborted = err?.name === "AbortError";
    return NextResponse.json(
      {
        ok: false,
        error: aborted ? "ocr_timeout" : "ocr_unavailable",
        message: aborted
          ? "Reading the screenshot timed out (30s)."
          : "Screenshot import service unavailable.",
      },
      { status: aborted ? 504 : 503 },
    );
  }
}

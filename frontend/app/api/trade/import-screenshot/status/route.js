// Proxy for GET /api/trade/import-screenshot/status — whether the backend
// can read screenshots (OCR engine installed, feature enabled).  /trade
// asks only when the user opens its Import control, never on page load.
//
// Thin pass-through for dev and the E2E stack (production nginx routes
// /api/* to FastAPI directly).  Cookie forwarded like every bridge route.

import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

export const dynamic = "force-dynamic";

export async function GET(request) {
  try {
    const { data, status } = await proxyGet(
      "/api/trade/import-screenshot/status",
      { cookie: request.headers.get("cookie") || "", timeoutMs: 5000 },
    );
    return NextResponse.json(data, {
      status,
      headers: { "Cache-Control": "no-store, private" },
    });
  } catch {
    // Unreachable backend: report the feature as not available rather than
    // guessing it is on.
    return NextResponse.json(
      {
        available: false,
        enabled: false,
        reason: "backend_unreachable",
        engine: "tesseract",
        version: null,
      },
      { status: 503 },
    );
  }
}

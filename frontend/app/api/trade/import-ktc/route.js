// Proxy for POST /api/trade/import-ktc — forwards to the FastAPI
// backend so the browser can paste a KTC trade-calculator URL and
// get back resolved player lists for the trade sides.
//
// Thin pass-through: the backend owns URL parsing, the KTC id map and
// name resolution.  In production nginx routes /api/* straight to
// FastAPI and this file is never reached; it serves dev and the E2E
// stack.
//
// The backend route is session-gated, so the caller's cookie is
// forwarded.  This route used a raw fetch() without it, so every import
// here answered 401 — and, being outside proxyGet/proxyPost, it escaped
// frontend/__tests__/bridge-routes-forward-cookies.test.js.  It now goes
// through proxyPost so that guard covers it.

import { NextResponse } from "next/server";
import { proxyPost } from "@/lib/backend-proxy";

export const dynamic = "force-dynamic";

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { ok: false, error: "Invalid JSON body" },
      { status: 400 },
    );
  }

  // A cold map fetch reads ~3 MB of KTC page HTML (up to two pages);
  // give it 20s — cold-cache fetch has occasionally taken 5-8s
  // under their CDN's cold path.
  try {
    const { data, status } = await proxyPost("/api/trade/import-ktc", body, {
      cookie: request.headers.get("cookie") || "",
      timeoutMs: 20_000,
    });
    return NextResponse.json(data, {
      status,
      headers: { "Cache-Control": "no-store, private" },
    });
  } catch (err) {
    const aborted = err?.name === "AbortError";
    return NextResponse.json(
      {
        ok: false,
        error: aborted
          ? "KTC import timed out (20s)."
          : "KTC import service unavailable",
        detail: err?.message,
      },
      { status: aborted ? 504 : 503 },
    );
  }
}

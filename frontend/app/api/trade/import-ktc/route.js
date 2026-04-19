// Proxy for POST /api/trade/import-ktc — forwards to the FastAPI
// backend so the browser can paste a KTC trade-calculator URL and
// get back resolved player lists for the trade sides.
//
// Thin pass-through: the backend owns URL parsing, HTML fetch, and
// name resolution.  This route exists only because the Next.js
// proxy layer intercepts all /api/* traffic — it's the same
// pattern as the other /api/trade/* proxies.

import { NextResponse } from "next/server";

const IMPORT_URL = (() => {
  const base = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
    /\/api\/data\/?$/,
    "",
  );
  return `${base}/api/trade/import-ktc`;
})();

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

  // Backend hits KTC's HTML (~1.4 MB) and parses out playersArray;
  // give it 20s — cold-cache fetch has occasionally taken 5-8s
  // under their CDN's cold path.
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 20_000);
  try {
    const res = await fetch(IMPORT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: ctl.signal,
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({
      ok: false,
      error: `Upstream returned non-JSON (status ${res.status})`,
    }));
    return NextResponse.json(data, { status: res.status });
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
  } finally {
    clearTimeout(timer);
  }
}

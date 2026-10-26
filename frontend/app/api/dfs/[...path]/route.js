/**
 * Dev/E2E bridge for the DFS workspace: /api/dfs/* → FastAPI.
 *
 * In production nginx routes /api/* straight to the backend and this file
 * is never reached.  A transparent pass-through (same shape as the auction
 * bridge): forwards method, body, cookie and query string; returns the
 * backend's status, body, content type and Content-Disposition unchanged, so
 * the upload-CSV export streams through as text rather than being parsed.
 * A cross-origin POST is refused here, before it reaches the backend.
 */
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const BACKEND = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(/\/api\/data\/?$/, "");

async function forward(request, { params }) {
  const { path = [] } = await params;
  // No dot segments: new URL() would resolve them out of /api/dfs/.
  if (path.some((seg) => seg === "." || seg === ".." || seg === "")) {
    return NextResponse.json({ error: "NOT_FOUND", message: "No such DFS route." }, { status: 404 });
  }
  const incoming = new URL(request.url);
  const target = new URL(`/api/dfs/${path.map(encodeURIComponent).join("/")}`, BACKEND);
  target.search = incoming.search;

  const headers = { Cookie: request.headers.get("cookie") || "" };
  let body;
  if (request.method !== "GET" && request.method !== "HEAD") {
    // Compare with the Host the BROWSER addressed, not request.url: under
    // `next start` request.url can carry Next's own bind host (localhost)
    // while the browser is on 127.0.0.1, which refused same-origin posts.
    const origin = request.headers.get("origin");
    const host = request.headers.get("x-forwarded-host") || request.headers.get("host");
    const expected = host ? `${incoming.protocol}//${host}` : incoming.origin;
    if (!origin || origin !== expected) {
      return NextResponse.json({ error: "BAD_ORIGIN", message: "Cross-origin request refused." }, { status: 403 });
    }
    headers["Content-Type"] = "application/json";
    body = await request.text();
  }
  const ctl = new AbortController();
  // Builds of up to 150 lineups run inside a 60 s solver budget.
  const timer = setTimeout(() => ctl.abort(), 90000);
  try {
    const res = await fetch(target.toString(), {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
      signal: ctl.signal,
    });
    const text = await res.text();
    const out = new NextResponse(text, {
      status: res.status,
      headers: {
        "Content-Type": res.headers.get("content-type") || "application/json",
        "Cache-Control": "no-store",
      },
    });
    for (const h of ["content-disposition", "x-dfs-export-verified"]) {
      const v = res.headers.get(h);
      if (v) out.headers.set(h, v);
    }
    return out;
  } catch {
    return NextResponse.json(
      { error: "BACKEND_UNREACHABLE", message: "The DFS service is unreachable." },
      { status: 503 },
    );
  } finally {
    clearTimeout(timer);
  }
}

export const GET = forward;
export const POST = forward;

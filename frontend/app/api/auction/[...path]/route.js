/**
 * Dev/E2E bridge for the rookie auction room: /api/auction/* → FastAPI.
 *
 * In production nginx routes /api/* straight to the backend and this file
 * is never reached.  It exists so `npm run dev` on :3000 works like prod.
 *
 * It is a transparent pass-through, not a second authority: it forwards the
 * method, body, cookies, Idempotency-Key and query string, and returns the
 * backend's status, body and Set-Cookie unchanged.  The backend's same-origin
 * CSRF check compares Origin with ITS host, which here is the backend's own
 * address, so the bridge performs the browser-origin check itself (Origin
 * must equal this Next request's origin) and then presents the backend
 * origin.  A cross-site POST is refused here exactly as the backend would.
 */
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const BACKEND = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(/\/api\/data\/?$/, "");

async function forward(request, { params }) {
  const { path = [] } = await params;
  const incoming = new URL(request.url);
  const target = new URL(`/api/auction/${path.map(encodeURIComponent).join("/")}`, BACKEND);
  target.search = incoming.search;

  const headers = { Cookie: request.headers.get("cookie") || "" };
  const idem = request.headers.get("idempotency-key");
  if (idem) headers["Idempotency-Key"] = idem;
  let body;
  if (request.method !== "GET" && request.method !== "HEAD") {
    const origin = request.headers.get("origin");
    if (!origin || origin !== incoming.origin) {
      return NextResponse.json({ error: "bad_origin", message: "cross-origin request refused" }, { status: 403 });
    }
    headers.Origin = new URL(BACKEND).origin;
    headers["Content-Type"] = "application/json";
    body = await request.text();
  }
  const wait = Number(incoming.searchParams.get("wait") || 0);
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), Math.max(10000, (wait + 10) * 1000));
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
    const out = new NextResponse(res.status === 204 ? null : text, {
      status: res.status,
      headers: { "Content-Type": res.headers.get("content-type") || "application/json", "Cache-Control": "no-store" },
    });
    const setCookie = res.headers.getSetCookie ? res.headers.getSetCookie() : [];
    for (const c of setCookie) out.headers.append("Set-Cookie", c);
    const disp = res.headers.get("content-disposition");
    if (disp) out.headers.set("Content-Disposition", disp);
    return out;
  } catch {
    return NextResponse.json({ error: "backend_unreachable", message: "The auction service is unreachable." }, { status: 503 });
  } finally {
    clearTimeout(timer);
  }
}

export const GET = forward;
export const POST = forward;

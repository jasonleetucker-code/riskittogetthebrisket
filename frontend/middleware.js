/**
 * middleware.js — server-side auth gate for pages.
 *
 * WHY THIS EXISTS
 * ---------------
 * server.py has a full page-level auth gate (`_require_auth_or_redirect`)
 * that is DEAD IN PRODUCTION: nginx sends every non-/api/ request
 * straight to Next.js (`location /` → dynasty_frontend), so FastAPI
 * never sees a page request and its redirects never run.  The code says
 * so itself.  The result was that `/admin`, `/rankings`, `/trade`,
 * `/settings` and every other private page returned 200 with full HTML
 * to anonymous visitors.  No player values leaked — the backend's
 * `/api/*` gate still 401s the data — but the entire private surface,
 * including operator tool names and the admin action list, was public
 * and crawlable.  It also meant `/draft` painted its shell before a
 * client-side `router.push` bounced the visitor to /login.
 *
 * WHAT THIS CHECKS
 * ----------------
 * Presence of the session cookie, not its validity.  That is the
 * correct scope: this middleware exists to stop anonymous visitors from
 * rendering private chrome, and it runs on every request, so verifying
 * the session here would put a store lookup in the hot path and
 * duplicate authority that already lives in `_private_api_gate`.  A
 * forged cookie gets an empty page — every byte of data behind it is
 * still gated server-side by the backend.  Defence in depth, not a
 * replacement for the real check.
 *
 * The public-route definition is shared with the app shell and robots
 * so the three cannot drift — see lib/public-routes.js.
 */
import { NextResponse } from "next/server";
import { MOVED_ROUTES, isPublicPath } from "@/lib/public-routes";

const SESSION_COOKIE = "jason_session";

export function middleware(request) {
  const { pathname, search } = request.nextUrl;

  // Moved routes first, so an old bookmark gets a real 308 and then
  // meets the auth gate at its new location on the follow-up request.
  const moved = MOVED_ROUTES.get(pathname);
  if (moved) {
    const url = request.nextUrl.clone();
    url.pathname = moved;
    return NextResponse.redirect(url, 308);
  }

  if (isPublicPath(pathname)) return NextResponse.next();
  if (request.cookies.get(SESSION_COOKIE)) return NextResponse.next();

  // Preserve the full destination (including query) so login lands the
  // visitor where they were headed.  server.py::_sanitize_next_path
  // rejects absolute URLs and CR/LF on the way back out.
  const url = request.nextUrl.clone();
  url.pathname = "/login";
  url.search = `?next=${encodeURIComponent(pathname + (search || ""))}`;
  return NextResponse.redirect(url);
}

export const config = {
  /*
   * Skip the middleware entirely for framework internals and any path
   * with a file extension (static assets).  `isPublicPath` covers the
   * same ground defensively, but keeping them out of the matcher means
   * the middleware never runs for them at all.
   */
  matcher: ["/((?!_next/static|_next/image|api/|.*\\.[\\w]+$).*)"],
};

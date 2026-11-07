/**
 * Master-site-audit W09-F007 (CW-40 Batch S re-adjudication, 2026-11-07) -- REPAIRED.
 *
 * Claim: of the four trade/angle Next bridge routes, `/api/trade/suggestions` is the only one
 * that drops the caller's session cookie, so in local dev / the E2E stack (where Next serves
 * `/api/*` itself) the suggestions feed is an ANONYMOUS request to an authenticated endpoint.
 * Production is unaffected (nginx routes `/api/*` straight to FastAPI).
 *
 * Why the existing guard missed it: `bridge-routes-forward-cookies.test.js` only walks routes
 * that call `proxyGet/proxyPost/proxyDelete`; this route hand-rolls `fetch`, so it escapes.
 *
 * The three sibling routes are pinned PASSING here (the contrast the finding describes); the
 * suggestions route is `it.fails` and flips when it reads the cookie header.
 * Smallest repair (2 lines, routine -- no owner gate):
 *   const cookie = request.headers.get("cookie") || "";
 *   headers: { "Content-Type": "application/json", Cookie: cookie },
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const API_DIR = path.join(process.cwd(), "app", "api");
const readsCookie = (rel) =>
  /headers\.get\(\s*["']cookie["']\s*\)/i.test(
    fs.readFileSync(path.join(API_DIR, rel, "route.js"), "utf8"),
  );

describe("hand-rolled trade/angle bridges forward the session cookie", () => {
  it.each(["trade/finder", "angle/find", "angle/packages"])("%s forwards the cookie", (rel) => {
    expect(readsCookie(rel)).toBe(true);
  });

  // /api/scrape is admin-gated on the backend (server.py::trigger_scrape), so it needs the session.
  // /api/news is deliberately public (listed in the public-path set), so it is left alone.
  it("scrape forwards the cookie (admin-gated backend route)", () => {
    expect(readsCookie("scrape")).toBe(true);
  });

  it("trade/suggestions forwards the cookie (W09-F007, repaired)", () => {
    expect(readsCookie("trade/suggestions")).toBe(true);
  });
});

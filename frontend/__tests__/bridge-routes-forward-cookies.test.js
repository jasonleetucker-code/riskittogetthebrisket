/**
 * Every Next bridge route must forward the caller's session cookie.
 *
 * WHY THIS EXISTS
 *
 * `frontend/app/api/**` exists only for deployments where Next serves
 * `/api/*` itself — local dev and the E2E stack. In production nginx routes
 * `/api/*` straight to FastAPI and none of these files are reached. That
 * asymmetry is exactly what let the bug hide: `proxyGet`/`proxyPost` send no
 * credentials of their own, so a route that forgets the cookie proxies an
 * ANONYMOUS request to an authenticated endpoint. Production is fine;
 * everywhere else the surface is quietly dead.
 *
 * It was not one route. Measured against a live backend, all twenty
 * cookieless bridges answered 401 anonymously and 200 authenticated —
 * `/bdvm/*`, `/consensus-edge/*`, `/league-comparison` and every `/sharp/*`
 * surface, unusable in local dev for as long as they had existed.
 *
 * And 401 is the loud case. `/api/draft-capital` answers 200 to anyone but
 * REDACTS its rookie fields for public callers, so the failure surfaced as a
 * Perfect Draft panel that rendered and quietly recommended nothing (#743).
 *
 * A reviewer cannot catch this by reading a diff — the omission looks like
 * every other route. So it is pinned here instead.
 */

import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const API_DIR = path.join(process.cwd(), "app", "api");

function routeFiles(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...routeFiles(full));
    else if (entry.name === "route.js") out.push(full);
  }
  return out;
}

const PROXY_CALL = /\bproxy(?:Get|Post)\s*\(/;

describe("Next bridge routes", () => {
  const files = routeFiles(API_DIR);

  it("finds the bridge routes at all (guards against a moved directory)", () => {
    // If app/api/ moves, every assertion below would pass vacuously.
    expect(files.length).toBeGreaterThan(20);
    expect(files.filter((f) => PROXY_CALL.test(fs.readFileSync(f, "utf8"))).length).toBeGreaterThan(
      10,
    );
  });

  it.each(
    routeFiles(API_DIR)
      .filter((f) => PROXY_CALL.test(fs.readFileSync(f, "utf8")))
      .map((f) => [path.relative(API_DIR, f), f]),
  )("%s forwards the session cookie to the backend", (_rel, file) => {
    const src = fs.readFileSync(file, "utf8");
    expect(
      /headers\.get\(\s*["']cookie["']\s*\)/i.test(src),
      "calls proxyGet/proxyPost but never reads the incoming cookie header — " +
        "the backend will see an anonymous request, which is a 401 on an " +
        "authenticated endpoint and silently redacted data on a public one",
    ).toBe(true);
  });
});

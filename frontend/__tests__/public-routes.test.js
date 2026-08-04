/**
 * public-routes spec — pins the public/private page boundary.
 *
 * This predicate is consumed by middleware.js (server-side redirect),
 * AppShellWrapper (which nav destinations a logged-out visitor sees)
 * and robots.js (what may be indexed).  Those three used to carry
 * three separate answers; these tests exist so they cannot drift apart
 * again.
 */
import { describe, expect, it } from "vitest";
import { MOVED_ROUTES, isInfrastructurePath, isPublicPath } from "@/lib/public-routes";

describe("public pages", () => {
  it("the landing page and login are public", () => {
    expect(isPublicPath("/")).toBe(true);
    expect(isPublicPath("/login")).toBe(true);
  });

  it("the whole /league subtree is public, not just /league", () => {
    // The old shell used an exact-match Set, so these nested routes —
    // all backed by the same public pipeline, and two of them League
    // nav items — were treated as private and vanished from the
    // logged-out nav.
    for (const path of [
      "/league",
      "/league/activity",
      "/league/franchise/jason",
      "/league/player/4034",
      "/league/rivalry/a-vs-b",
      "/league/week/2025/3",
      "/league/weekly/2025/3/1",
      "/league/articles/2025/3",
      "/league/articles/2025/3/1/recap",
    ]) {
      expect(isPublicPath(path), path).toBe(true);
    }
  });

  it("keeps the legacy /draft-capital shim public", () => {
    expect(isPublicPath("/draft-capital")).toBe(true);
  });
});

describe("private pages", () => {
  it("every analysis surface requires a session", () => {
    for (const path of [
      "/rankings",
      "/trending",
      "/news",
      "/trade",
      "/arbitrage",
      "/angle",
      "/draft",
      "/waivers",
      "/rosters",
      "/edge",
      "/bdvm",
      "/intel",
      "/idptc-rookies",
      "/players/compare",
      "/league-comparison",
      "/settings",
      "/more",
      "/admin",
      "/tools/source-health",
      "/tools/ros-data-health",
      "/tools/trade-coverage",
    ]) {
      expect(isPublicPath(path), path).toBe(false);
    }
  });

  it("/trades is private — it renders trade grades off the private contract", () => {
    // It was declared public in three places while being unusable
    // logged-out and competitively sensitive logged-in.
    expect(isPublicPath("/trades")).toBe(false);
  });

  it("/phases is private — contention classification is proprietary", () => {
    expect(isPublicPath("/phases")).toBe(false);
  });

  it("/league/insider-trading is private despite sitting under /league", () => {
    // Measured on production 2026-07-30 BEFORE this carve-out: the page
    // answered 200 to an anonymous visitor while both of its data
    // sources answered 401 (/api/intel/summary, /api/intel/player), and
    // the page has no auth gate of its own — so a stranger got a
    // permanent "Loading Insider Trading…" spinner, on a URL robots.txt
    // makes indexable via `Allow: /league/`.
    //
    // Same defect class as /trades (see the module docstring). It
    // recurred because /trades was fixed by REMOVING it from a list,
    // which cannot help a route nobody had to add — prefix matching
    // makes every future /league/* page public by default.
    expect(isPublicPath("/league/insider-trading")).toBe(false);
  });

  it("a private exception covers its subtree, not just the exact path", () => {
    expect(isPublicPath("/league/insider-trading/anything")).toBe(false);
  });

  it("the carve-out does not leak onto sibling /league routes", () => {
    // The exception must be surgical: the public league hub and its
    // genuinely public children keep working for logged-out visitors.
    for (const p of [
      "/league",
      "/league/activity",
      "/league/franchise/jason",
      "/league/insider-tradingx",
    ]) {
      expect(isPublicPath(p), p).toBe(true);
    }
  });

  it("a /league lookalike prefix does not inherit public status", () => {
    expect(isPublicPath("/league-comparison")).toBe(false);
    expect(isPublicPath("/leaguesecrets")).toBe(false);
  });
});

describe("infrastructure paths", () => {
  it("framework, API and crawler metadata are never gated", () => {
    for (const path of [
      "/_next/static/chunk.js",
      "/api/data",
      "/robots.txt",
      "/sitemap.xml",
      "/manifest.webmanifest",
      "/favicon.ico",
    ]) {
      expect(isInfrastructurePath(path), path).toBe(true);
      expect(isPublicPath(path), path).toBe(true);
    }
  });

  it("route-segment image metadata stays reachable so shared links unfurl", () => {
    // Public-league pages generate OG images per dynamic route; gating
    // them would break link previews for URLs that are themselves public.
    expect(isInfrastructurePath("/league/franchise/jason/opengraph-image")).toBe(true);
    expect(isInfrastructurePath("/league/rivalry/a-vs-b/opengraph-image-abc123")).toBe(true);
  });

  it("does not treat an ordinary page as infrastructure", () => {
    expect(isInfrastructurePath("/rankings")).toBe(false);
    expect(isInfrastructurePath("/")).toBe(false);
  });
});

describe("defensive input handling", () => {
  it("empty or missing pathnames are not public", () => {
    expect(isPublicPath("")).toBe(false);
    expect(isPublicPath(null)).toBe(false);
    expect(isPublicPath(undefined)).toBe(false);
  });
});

describe("moved routes", () => {
  it("maps /league/phases to its new private home", () => {
    // A page-level redirect() shim under /league cannot do this: that
    // segment has a loading.jsx, so Next streams a 200 and redirects
    // client-side — which leaves a 200 on a URL whose content moved
    // behind auth, and never redirects a crawler at all.
    expect(MOVED_ROUTES.get("/league/phases")).toBe("/phases");
  });

  it("every move target is a real destination, not another move", () => {
    for (const [from, to] of MOVED_ROUTES) {
      expect(to.startsWith("/"), from).toBe(true);
      expect(MOVED_ROUTES.has(to), `${to} is itself a redirect`).toBe(false);
    }
  });
});

/**
 * AppShell route gates — which routes hydrate the player pipeline.
 *
 * Two INDEPENDENT predicates, deliberately not merged:
 *
 *   isPublicOnlyRoute    — a PRIVACY boundary. The /league subtree is
 *                          reachable logged-out, and /api/data carries
 *                          private rankings, edge signals and trade
 *                          targets. Adding a route here is a security
 *                          statement.
 *   isNoPlayerDataRoute  — a COST decision. These are private routes
 *                          that simply have no player data to render.
 *
 * Folding the second list into the first would make the next person
 * auditing "what is public" read /admin off the public list and get a
 * wrong answer. These tests exist mostly to keep them apart.
 *
 * Pure functions, so tested directly — a wrong entry breaks a page
 * rather than slowing it, which is worth a cheap unit test.
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

import { __routeGates } from "@/components/AppShell";

const { isPublicOnlyRoute, isNoPlayerDataRoute, NO_PLAYER_DATA_ROUTE_PREFIXES } =
  __routeGates;

// Mirrors AppShell's own composition. If this drifts from the component,
// the assertions below stop describing production.
const privateDataEnabled = (pathname) =>
  !isPublicOnlyRoute(pathname) && !isNoPlayerDataRoute(pathname);

describe("isPublicOnlyRoute — the privacy boundary", () => {
  it("matches /league and its descendants", () => {
    expect(isPublicOnlyRoute("/league")).toBe(true);
    expect(isPublicOnlyRoute("/league/franchise/abc")).toBe(true);
  });

  it("does not match a route that merely shares a prefix string", () => {
    // "/leagues" starts with "/league" as a STRING but is a different
    // route; the guard joins on a path separator for exactly this.
    expect(isPublicOnlyRoute("/leagues")).toBe(false);
  });

  it("stays limited to /league — new entries here are security changes", () => {
    expect(__routeGates.PUBLIC_ONLY_ROUTE_PREFIXES).toEqual(["/league"]);
  });

  it("handles a null pathname without throwing", () => {
    expect(isPublicOnlyRoute(null)).toBe(false);
    expect(isPublicOnlyRoute(undefined)).toBe(false);
    expect(isPublicOnlyRoute("")).toBe(false);
  });
});

describe("isNoPlayerDataRoute — the cost decision", () => {
  it.each(NO_PLAYER_DATA_ROUTE_PREFIXES)("matches %s exactly", (route) => {
    expect(isNoPlayerDataRoute(route)).toBe(true);
  });

  it("matches descendants, so /admin/sharp-identities is covered", () => {
    expect(isNoPlayerDataRoute("/admin/sharp-identities")).toBe(true);
  });

  it("does not match on a shared prefix string", () => {
    expect(isNoPlayerDataRoute("/logins")).toBe(false);
    expect(isNoPlayerDataRoute("/administration")).toBe(false);
  });

  it("handles a null pathname without throwing", () => {
    expect(isNoPlayerDataRoute(null)).toBe(false);
  });
});

describe("the two routes deliberately NOT gated", () => {
  // Both were audited and rejected. They are asserted here so a future
  // "obvious" addition fails a test that explains itself rather than
  // breaking the page at runtime.
  it("keeps /settings on the player pipeline — it calls useDynastyData() itself", () => {
    // Gating the shell would not even stop its fetch, because the PAGE
    // mounts the hook. It would only strip its search.
    expect(isNoPlayerDataRoute("/settings")).toBe(false);
    expect(privateDataEnabled("/settings")).toBe(true);
  });

  it("keeps /tools/trade-coverage on the pipeline — it reads useApp().rawData", () => {
    expect(isNoPlayerDataRoute("/tools/trade-coverage")).toBe(false);
    expect(privateDataEnabled("/tools/trade-coverage")).toBe(true);
  });

  it("gates the other /tools health pages, which read /api/status instead", () => {
    expect(privateDataEnabled("/tools/source-health")).toBe(false);
    expect(privateDataEnabled("/tools/ros-data-health")).toBe(false);
  });
});

describe("privateDataEnabled composition", () => {
  it("is false for either reason, and true only when neither applies", () => {
    expect(privateDataEnabled("/league")).toBe(false); // privacy
    expect(privateDataEnabled("/login")).toBe(false); // cost
    expect(privateDataEnabled("/rankings")).toBe(true);
    expect(privateDataEnabled("/trade")).toBe(true);
    expect(privateDataEnabled("/draft")).toBe(true);
  });

  it("leaves the data-bearing routes alone", () => {
    for (const route of ["/", "/rankings", "/trade", "/draft", "/waivers", "/bdvm"]) {
      expect(privateDataEnabled(route), `${route} must keep its data`).toBe(true);
    }
  });
});

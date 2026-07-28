/**
 * Nav-model IA spec — pins the R1 information architecture:
 * every routable surface stays reachable, hrefs are unique, active
 * matching is longest-prefix, and page titles derive from the model.
 */
import { describe, expect, it } from "vitest";
import {
  NAV_MODEL,
  SYSTEM_MODEL,
  MOBILE_TABS,
  PALETTE_EXTRA_TARGETS,
  flattenNav,
  paletteTargets,
  isNavActive,
  isGroupActive,
  pageTitleFor,
} from "@/lib/nav-model";

// Every user-facing route in frontend/app (excluding dynamic-only
// public-league subroutes reached from the hub, the /login page, the
// legacy /draft-capital redirect shim, and the dev-only /design style
// reference). If a new page ships, add it HERE and to the nav model.
const ROUTES_THAT_MUST_BE_REACHABLE = [
  "/",
  "/rankings",
  "/news",
  "/trending",
  "/trade",
  "/trades",
  "/finder",
  "/angle",
  "/draft",
  "/waivers",
  "/rosters",
  "/edge",
  "/intel",
  "/idptc-rookies",
  "/league",
  "/league/activity",
  "/league/phases",
  "/league-comparison",
  "/players/compare",
  "/settings",
  "/more",
  "/admin",
  "/tools/source-health",
  "/tools/ros-data-health",
  "/tools/trade-coverage",
];

const allTargets = paletteTargets();

describe("IA coverage", () => {
  it("every route is reachable from the palette targets (nav + system + extras)", () => {
    const hrefs = new Set(allTargets.map((t) => t.href));
    const missing = ROUTES_THAT_MUST_BE_REACHABLE.filter((r) => !hrefs.has(r));
    expect(missing).toEqual([]);
  });

  it("the previously nav-orphaned operator surfaces are now in the System menu", () => {
    const hrefs = SYSTEM_MODEL.items.map((i) => i.href);
    for (const orphan of [
      "/admin",
      "/tools/source-health",
      "/tools/ros-data-health",
      "/tools/trade-coverage",
    ]) {
      expect(hrefs).toContain(orphan);
    }
  });

  it("palette targets are deduped and every entry has href + label", () => {
    const hrefs = allTargets.map((t) => t.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
    for (const t of allTargets) {
      expect(t.href).toMatch(/^\//);
      expect(t.label).toBeTruthy();
    }
  });

  it("mobile tabs are a subset of the model's destinations", () => {
    const hrefs = new Set(allTargets.map((t) => t.href));
    for (const tab of MOBILE_TABS) {
      expect(hrefs.has(tab.href)).toBe(true);
      expect(tab.icon).toBeTruthy();
    }
  });

  it("group hrefs point at one of their own items (parent click lands in-group)", () => {
    for (const group of NAV_MODEL) {
      if (!group.items) continue;
      expect(group.items.map((i) => i.href)).toContain(group.href);
    }
  });

  it("the dev-only /design route is deliberately NOT navigable", () => {
    expect(allTargets.some((t) => t.href === "/design")).toBe(false);
  });
});

describe("active matching", () => {
  it("is longest-prefix: deep league routes light the right item", () => {
    expect(isNavActive("/league", "/league/activity")).toBe(true);
    expect(isNavActive("/league/activity", "/league/activity")).toBe(true);
    expect(isNavActive("/league/activity", "/league")).toBe(false);
  });

  it("home matches only exactly", () => {
    expect(isNavActive("/", "/")).toBe(true);
    expect(isNavActive("/", "/rankings")).toBe(false);
  });

  it("/trade does not light /trades (no partial-segment match)", () => {
    expect(isNavActive("/trade", "/trades")).toBe(false);
    expect(isNavActive("/trade", "/trade/simulate")).toBe(true);
  });

  it("group active state fires for any child route", () => {
    const trade = NAV_MODEL.find((g) => g.key === "trade");
    expect(isGroupActive(trade, "/finder")).toBe(true);
    expect(isGroupActive(trade, "/angle")).toBe(true);
    expect(isGroupActive(trade, "/rankings")).toBe(false);
  });
});

describe("pageTitleFor", () => {
  it("derives titles from the model (no hand-maintained map)", () => {
    expect(pageTitleFor("/rankings")).toBe("Rankings");
    expect(pageTitleFor("/finder")).toBe("Signal Blotter");
    // /arbitrage holds the Arbitrage Finder label now; /finder computes
    // no arbitrage and its old label is what produced the phantom in
    // backlog #6.
    expect(pageTitleFor("/arbitrage")).toBe("Arbitrage Finder");
    expect(pageTitleFor("/tools/source-health")).toBe("Source Health");
    expect(pageTitleFor("/")).toBe("Home");
  });

  it("keeps contextual labels for deep public-league routes", () => {
    expect(pageTitleFor("/league/franchise/jason")).toBe("Franchise");
    expect(pageTitleFor("/league/rivalry/a-vs-b")).toBe("Rivalry");
    expect(pageTitleFor("/league/weekly/2025/3/1")).toBe("Matchup");
  });

  it("prefers the longest matching href", () => {
    expect(pageTitleFor("/league/activity")).toBe("Activity");
    expect(pageTitleFor("/league")).toBe("Hub");
  });

  it("falls back to the brand for unknown routes", () => {
    expect(pageTitleFor("/nonexistent")).toBe("Chase Upside");
  });
});

describe("flattenNav", () => {
  it("flattens groups to leaves and direct entries to themselves", () => {
    const flat = flattenNav(NAV_MODEL);
    expect(flat.some((i) => i.href === "/rankings" && i.group === null)).toBe(true);
    expect(flat.some((i) => i.href === "/finder" && i.group === "Trade")).toBe(true);
  });

  it("extra palette targets carry compare-players", () => {
    expect(PALETTE_EXTRA_TARGETS.some((t) => t.href === "/players/compare")).toBe(true);
  });
});

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
  MOBILE_TABS_PUBLIC,
  PALETTE_EXTRA_TARGETS,
  flattenNav,
  paletteTargets,
  isNavActive,
  isGroupActive,
  pageTitleFor,
  systemItemsFor,
} from "@/lib/nav-model";
import { isPublicPath } from "@/lib/public-routes";

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
  "/arbitrage",
  "/angle",
  "/draft",
  "/waivers",
  "/rosters",
  "/phases",
  "/edge",
  "/bdvm",
  "/intel",
  "/idptc-rookies",
  "/league",
  "/league/activity",
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

  it("logged-out mobile tabs include a way to sign in", () => {
    // Filtering the authed tabs by "is public" left Home + Menu and no
    // Sign in anywhere in the mobile chrome — a logged-out phone
    // visitor could not reach /login from the nav at all.
    const hrefs = MOBILE_TABS_PUBLIC.map((t) => t.href);
    expect(hrefs).toContain("/login");
    for (const tab of MOBILE_TABS_PUBLIC) {
      expect(isPublicPath(tab.href), tab.href).toBe(true);
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

  it("compare-players is in a menu, not palette-only", () => {
    // It used to live in PALETTE_EXTRA_TARGETS, so the only way to
    // find it was to already know it existed.
    const inMenus = flattenNav(NAV_MODEL).map((i) => i.href);
    expect(inMenus).toContain("/players/compare");
  });

  it("no group mixes public and private children for a logged-out visitor", () => {
    // The nav filters group children by public/private when logged
    // out; a group whose PUBLIC children are all gone must disappear
    // entirely rather than render as an empty menu.
    for (const group of NAV_MODEL) {
      if (!group.items) continue;
      const publicItems = group.items.filter((i) => isPublicPath(i.href));
      if (publicItems.length === 0) continue;
      // If a group survives for logged-out visitors, its own href must
      // be public too — otherwise clicking the group label bounces
      // them to /login from a menu that looked available.
      expect(isPublicPath(group.href), `${group.label} group href`).toBe(true);
    }
  });
});

describe("naming canon", () => {
  /*
   * A leaf's nav label IS the page's name.  Eight pages used to
   * disagree with their own nav entry — "Counter-Pitch" opened a page
   * titled "Trade Finder" while "Signal Blotter" opened one titled
   * "Finder" and "Arbitrage Finder" opened "Arbitrage".  Three tools,
   * four "finder" labels.  These tests pin the resolved names; the
   * page <h1>s are asserted against the same strings in
   * __tests__/components/page-title-canon.test.jsx.
   */
  const CANON = {
    "/rankings": "Rankings",
    "/trending": "Trending",
    "/idptc-rookies": "Rookie Board",
    "/players/compare": "Compare Players",
    "/bdvm": "Fundamental Values",
    "/news": "News",
    "/trade": "Trade Calculator",
    "/angle": "Package Builder",
    "/arbitrage": "Arbitrage",
    "/trades": "Trade History",
    "/rosters": "Team Strength",
    "/waivers": "Waivers",
    "/draft": "Draft Board",
    "/phases": "Win-now vs Rebuild",
    "/edge": "Source Disagreement",
    "/intel": "Manager Activity",
    "/league": "Hub",
    "/league/activity": "Activity",
    "/league-comparison": "Scoring Comparison",
  };

  it("every canonical route carries its canonical label in the nav", () => {
    const byHref = new Map(flattenNav(NAV_MODEL).map((i) => [i.href, i.label]));
    for (const [href, label] of Object.entries(CANON)) {
      expect(byHref.get(href), href).toBe(label);
    }
  });

  it("pageTitleFor agrees with the nav label for every canonical route", () => {
    for (const [href, label] of Object.entries(CANON)) {
      expect(pageTitleFor(href), href).toBe(label);
    }
  });

  it("no two destinations share a label", () => {
    // The failure this prevents: two menu entries a user cannot tell
    // apart, which is exactly how the finder trio happened.
    const labels = allTargets.map((t) => t.label);
    const dupes = labels.filter((l, i) => labels.indexOf(l) !== i);
    expect(dupes).toEqual([]);
  });

  it("no label reuses a retired name", () => {
    const retired = [
      "Signal Blotter",
      "Player Screener",
      "Counter-Pitch",
      "Sharp Tracker",
      "Rookie Lab",
      "Arbitrage Finder",
      "League Comp",
      "Edge",
      "Fundamentals",
      "Calculator",
    ];
    const labels = new Set(allTargets.map((t) => t.label));
    for (const name of retired) {
      expect(labels.has(name), `retired label "${name}" is back`).toBe(false);
    }
  });
});

describe("system menu", () => {
  it("hides operator surfaces from non-admins", () => {
    const hrefs = systemItemsFor({ isAdmin: false }).map((i) => i.href);
    expect(hrefs).toContain("/settings");
    expect(hrefs).toContain("/more");
    for (const ops of [
      "/admin",
      "/tools/source-health",
      "/tools/ros-data-health",
      "/tools/trade-coverage",
    ]) {
      expect(hrefs, ops).not.toContain(ops);
    }
  });

  it("shows every operator surface to admins", () => {
    const hrefs = systemItemsFor({ isAdmin: true }).map((i) => i.href);
    for (const item of SYSTEM_MODEL.items) {
      expect(hrefs).toContain(item.href);
    }
  });

  it("defaults to the non-admin view when the flag is absent", () => {
    expect(systemItemsFor().map((i) => i.href)).not.toContain("/admin");
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
    const trades = NAV_MODEL.find((g) => g.key === "trades");
    expect(isGroupActive(trades, "/arbitrage")).toBe(true);
    expect(isGroupActive(trades, "/angle")).toBe(true);
    expect(isGroupActive(trades, "/rankings")).toBe(false);
  });
});

describe("pageTitleFor", () => {
  it("derives titles from the model (no hand-maintained map)", () => {
    expect(pageTitleFor("/rankings")).toBe("Rankings");
    expect(pageTitleFor("/arbitrage")).toBe("Arbitrage");
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
    // /news is the one remaining direct (group-less) top-level entry.
    expect(flat.some((i) => i.href === "/news" && i.group === null)).toBe(true);
    // /rankings is now a leaf of the Rankings group — grouping it costs
    // no click because the group label itself links there.
    expect(flat.some((i) => i.href === "/rankings" && i.group === "Rankings")).toBe(true);
    expect(flat.some((i) => i.href === "/edge" && i.group === "Market")).toBe(true);
  });

  it("extra palette targets keep Home reachable by name", () => {
    expect(PALETTE_EXTRA_TARGETS.some((t) => t.href === "/")).toBe(true);
  });
});

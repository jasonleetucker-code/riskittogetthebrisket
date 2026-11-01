/**
 * Route inventory — every real page route is accounted for, and the
 * committed inventory agrees with the live nav model and route gates.
 *
 * Source of the inventory: docs/ui/evidence/route_inventory_2026-11-01.json
 * (UX navigation audit, docs/ui/UX_NAVIGATION_AUDIT_2026-11-01.md).
 *
 * WHY THIS EXISTS.  nav-model.test.js pins reachability against a
 * HAND-MAINTAINED list of routes.  A page that was never added to that
 * list was never checked, which is how /market/sharp-people shipped as a
 * live private page that no signed-in user could find (its one inbound
 * link was on an admin page).  This test walks frontend/app instead, so a
 * new page.jsx fails here until somebody decides where it lives.
 *
 * What is HAND-authored in the JSON (and only reviewed here):
 *   name, purpose, audience, task, status, notes.
 * What is DERIVED and must agree (stored in the JSON for readers, checked
 * here so it cannot go stale):
 *   access   ← lib/public-routes.js
 *   nav      ← lib/nav-model.js (menus, drawer, palette, tabs, sections,
 *              capability, admin-only) + the dashboard Quick actions
 *
 * Regenerating the derived block after a deliberate nav change:
 *   UPDATE_ROUTE_INVENTORY=1 npx vitest run __tests__/route-inventory.test.js
 * then review the JSON diff — that diff IS the IA change.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  MOBILE_TABS,
  MOBILE_TABS_PUBLIC,
  NAV_MODEL,
  SYSTEM_MODEL,
  flattenNav,
  paletteTargets,
} from "@/lib/nav-model";
import {
  isPublicPath,
  isSelfAuthedPagePath,
  isUnlistedPagePath,
} from "@/lib/public-routes";
import { QUICK_ACTIONS } from "@/components/terminal/QuickActions";

const FRONTEND = path.resolve(__dirname, "..");
const APP = path.join(FRONTEND, "app");
const INVENTORY_PATH = path.resolve(
  FRONTEND,
  "..",
  "docs",
  "ui",
  "evidence",
  "route_inventory_2026-11-01.json",
);

/** Every page route under app/, as "/a/[b]" patterns (api excluded). */
function pageRoutes() {
  const out = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (full === path.join(APP, "api")) continue;
        walk(full);
      } else if (entry.name === "page.jsx" || entry.name === "page.js") {
        const rel = path.relative(APP, dir).split(path.sep).join("/");
        // POSIX separators always, so the committed JSON (and regeneration)
        // is identical on Windows and Linux CI.
        const file = path.relative(FRONTEND, full).split(path.sep).join("/");
        out.push({ route: rel ? `/${rel}` : "/", file });
      }
    }
  };
  walk(APP);
  return out.sort((a, b) => a.route.localeCompare(b.route));
}

/** A concrete sample URL for a dynamic pattern ("/a/[b]" → "/a/b"). */
const sampleUrl = (route) => route.replace(/\[([^\]]+)\]/g, "$1");
const pathOf = (href) => href.split("?")[0];
/** Static prefix of a route (everything before the first dynamic segment). */
const staticPrefix = (route) => (route.includes("[") ? route.split("/[")[0] : route);

const ALL_CAPABILITIES_ON = Object.fromEntries(
  flattenNav(NAV_MODEL)
    .filter((i) => i.capability)
    .map((i) => [i.capability, { available: true }]),
);

function accessFor(route) {
  const url = sampleUrl(route);
  if (isUnlistedPagePath(url)) return "unlisted";
  if (isSelfAuthedPagePath(url)) return "self_authed";
  if (isPublicPath(url)) return "public";
  return "private";
}

function derivedNav(route) {
  const menuItems = [];
  for (const group of NAV_MODEL) {
    const leaves = group.items && group.items.length ? group.items : [group];
    for (const item of leaves) {
      if (pathOf(item.href) === route) menuItems.push({ group: group.label, item });
    }
  }
  for (const item of SYSTEM_MODEL.items) {
    if (pathOf(item.href) === route) menuItems.push({ group: SYSTEM_MODEL.label, item });
  }
  const palette = paletteTargets({ capabilities: ALL_CAPABILITIES_ON, isAdmin: true }).filter(
    (t) => pathOf(t.href) === route,
  );
  const capabilities = [...new Set(menuItems.map((m) => m.item.capability).filter(Boolean))];
  const sections = [...new Set(menuItems.map((m) => m.item.section).filter(Boolean))];
  return {
    // Desktop top-bar menus, the mobile drawer and /more render the same
    // groups (one model), so one field answers all three.
    menuGroup: menuItems.length ? menuItems[0].group : null,
    menuLabels: menuItems.map((m) => m.item.label),
    section: sections.length ? sections.join(" / ") : null,
    capability: capabilities.length ? capabilities.join(" + ") : null,
    adminOnly: menuItems.some((m) => m.item.adminOnly === true),
    palette: palette.length > 0,
    mobileTabSignedIn: MOBILE_TABS.some((t) => t.href === route),
    mobileTabSignedOut: MOBILE_TABS_PUBLIC.some((t) => t.href === route),
    homeQuickAction: QUICK_ACTIONS.some((a) => pathOf(a.href) === route),
    // A signed-out visitor is offered a menu entry only for public pages
    // (TopBar/MobileChrome filter by isPublicPath).
    signedOutMenu: menuItems.length > 0 && isPublicPath(route),
  };
}

const reachabilityOf = (row, nav) => {
  if (nav.menuGroup || nav.palette || nav.mobileTabSignedIn || nav.mobileTabSignedOut) {
    return "nav";
  }
  if ((row.contextualFrom || []).length > 0) return "contextual";
  return "direct_url_only";
};

const pages = pageRoutes();
let inventory = JSON.parse(fs.readFileSync(INVENTORY_PATH, "utf-8"));

if (process.env.UPDATE_ROUTE_INVENTORY === "1") {
  const fileByRoute = new Map(pages.map((p) => [p.route, p.file]));
  for (const row of inventory.routes) {
    const nav = derivedNav(row.route);
    row.file = fileByRoute.get(row.route) || null;
    row.access = row.access === "redirect" || row.access === "dev" ? row.access : accessFor(row.route);
    row.nav = nav;
    row.reachable = reachabilityOf(row, nav);
  }
  fs.writeFileSync(INVENTORY_PATH, `${JSON.stringify(inventory, null, 2)}\n`, "utf-8");
  inventory = JSON.parse(fs.readFileSync(INVENTORY_PATH, "utf-8"));
}

const rows = inventory.routes;
const byRoute = new Map(rows.map((r) => [r.route, r]));

describe("route inventory covers every page route", () => {
  it("every page.jsx under app/ has exactly one inventory row, and no row is stale", () => {
    const onDisk = pages.map((p) => p.route);
    const inJson = rows.map((r) => r.route);
    expect(new Set(inJson).size).toBe(inJson.length);
    expect(onDisk.filter((r) => !byRoute.has(r))).toEqual([]);
    expect(inJson.filter((r) => !onDisk.includes(r))).toEqual([]);
  });

  it("every row names its page file, and the file exists", () => {
    const fileByRoute = new Map(pages.map((p) => [p.route, p.file]));
    for (const row of rows) {
      expect(row.file, row.route).toBeTruthy();
      // Stored as POSIX on every OS: a backslash here means the JSON was
      // regenerated with OS separators and would fail on Linux CI.
      expect(row.file.includes("\\"), `${row.route} file path must be POSIX`).toBe(false);
      expect(row.file, row.route).toBe(fileByRoute.get(row.route));
      expect(fs.existsSync(path.join(FRONTEND, ...row.file.split("/"))), row.file).toBe(true);
    }
  });

  it("every row carries the hand-authored audit fields with known values", () => {
    const statuses = Object.keys(inventory.statuses);
    for (const row of rows) {
      for (const field of ["name", "purpose", "audience", "task"]) {
        expect(row[field], `${row.route}.${field}`).toBeTruthy();
      }
      expect(statuses, `${row.route}.status`).toContain(row.status);
      expect(Object.keys(inventory.accessClasses), `${row.route}.access`).toContain(row.access);
    }
  });
});

describe("derived facts agree with the live gates and nav model", () => {
  it("access class matches lib/public-routes.js", () => {
    for (const row of rows) {
      if (row.access === "redirect" || row.access === "dev") continue;
      expect(row.access, row.route).toBe(accessFor(row.route));
    }
  });

  it("nav placement matches lib/nav-model.js (regenerate with UPDATE_ROUTE_INVENTORY=1)", () => {
    for (const row of rows) {
      expect(row.nav, row.route).toEqual(derivedNav(row.route));
      expect(row.reachable, row.route).toBe(reachabilityOf(row, row.nav));
    }
  });

  it("every contextual link the inventory claims really exists in that file", () => {
    for (const row of rows) {
      const needle = staticPrefix(row.route);
      for (const rel of row.contextualFrom || []) {
        const text = fs.readFileSync(path.join(FRONTEND, rel), "utf-8");
        // Preceded by a quote, or by `}` for a template like `${origin}/league/…`.
        const pattern = new RegExp(`(["'\`]|\\})${needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}["'\`/?$]`);
        expect(pattern.test(text), `${rel} does not link ${row.route}`).toBe(true);
      }
    }
  });
});

describe("no orphaned live pages", () => {
  it("every WORKING page is reachable from nav or an in-app contextual link", () => {
    const orphans = rows
      .filter((r) => r.status === "working" && r.reachable === "direct_url_only")
      .map((r) => r.route);
    expect(orphans).toEqual([]);
  });

  it("redirect rows really only redirect", () => {
    for (const row of rows.filter((r) => r.access === "redirect")) {
      const text = fs.readFileSync(path.join(FRONTEND, row.file), "utf-8");
      expect(/redirect\(|router\.replace\(/.test(text), row.route).toBe(true);
      expect(row.nav.menuGroup, row.route).toBeNull();
    }
  });

  it("hidden, unlisted, dev and self-authed pages are never offered in a menu", () => {
    for (const row of rows) {
      if (["intentionally_hidden", "dev_reference", "redirect"].includes(row.status)) {
        expect(row.nav.menuGroup, row.route).toBeNull();
        expect(row.nav.palette, row.route).toBe(false);
      }
    }
  });

  it("a disabled-by-flag page is offered only behind a capability (never unconditionally)", () => {
    for (const row of rows.filter((r) => r.status === "disabled_by_flag")) {
      if (row.nav.menuGroup) expect(row.nav.capability, row.route).toBeTruthy();
    }
  });
});

describe("public / private boundary in the menus", () => {
  it("no private route is offered to a signed-out visitor", () => {
    for (const row of rows) {
      if (row.nav.signedOutMenu || row.nav.mobileTabSignedOut) {
        expect(row.access, row.route).toBe("public");
      }
    }
  });

  it("every admin-only menu entry is a private page", () => {
    for (const row of rows.filter((r) => r.nav.adminOnly)) {
      expect(row.access, row.route).toBe("private");
    }
  });
});

describe("no broken internal links from navigation surfaces", () => {
  const patterns = pages.map((p) => ({
    route: p.route,
    re: new RegExp(`^${p.route.replace(/\[[^\]]+\]/g, "[^/]+")}$`),
  }));
  const resolves = (href) => {
    const p = pathOf(href);
    // Routing-layer redirects declared in next.config.mjs.
    if (p === "/draft-capital") return true;
    return patterns.some(({ re }) => re.test(p));
  };

  it("every nav-model, palette, tab and quick-action href resolves to a page", () => {
    const hrefs = [
      ...flattenNav(NAV_MODEL).map((i) => i.href),
      ...SYSTEM_MODEL.items.map((i) => i.href),
      ...paletteTargets({ capabilities: ALL_CAPABILITIES_ON, isAdmin: true }).map((i) => i.href),
      ...MOBILE_TABS.map((t) => t.href),
      ...MOBILE_TABS_PUBLIC.map((t) => t.href),
      ...QUICK_ACTIONS.map((a) => a.href),
    ];
    expect(hrefs.filter((h) => !resolves(h))).toEqual([]);
  });

  it("every RelatedLinks href in a page resolves to a nav-model destination", () => {
    const targets = new Set(
      paletteTargets({ capabilities: ALL_CAPABILITIES_ON, isAdmin: true }).map((t) => t.href),
    );
    const bad = [];
    for (const page of pages) {
      const text = fs.readFileSync(path.join(FRONTEND, page.file), "utf-8");
      for (const m of text.matchAll(/<RelatedLinks\s+hrefs=\{\[([^\]]*)\]\}/g)) {
        for (const h of m[1].matchAll(/"([^"]+)"/g)) {
          if (!targets.has(h[1])) bad.push(`${page.route} -> ${h[1]}`);
        }
      }
    }
    expect(bad).toEqual([]);
  });
});

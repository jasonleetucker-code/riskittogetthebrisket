/**
 * Every page route resolves a specific browser-tab title.
 *
 * The root layout supplies only the generic "Chase Upside"; each route
 * segment must override it, either from a `layout.js` (pageMetadata) or from
 * the page's own metadata / generateMetadata (dynamic public-league pages).
 * Labels come from nav-model (the one owner of page names).
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { GENERIC_TITLE, TITLE_SUFFIX, pageMetadata, pageTitle } from "@/lib/page-metadata";
import { NAV_MODEL, SYSTEM_MODEL, pageTitleFor } from "@/lib/nav-model";

const APP = path.resolve(__dirname, "../app");

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) walk(full, out);
    else if (/^page\.(jsx|js)$/.test(e.name)) out.push(dir);
  }
  return out;
}

const routes = walk(APP).map((d) => ({
  dir: d,
  route: "/" + path.relative(APP, d).split(path.sep).join("/"),
}));

function layoutFile(dir) {
  for (const n of ["layout.js", "layout.jsx"]) {
    const f = path.join(dir, n);
    if (fs.existsSync(f)) return f;
  }
  return null;
}

/** Where does this route's title come from?  "page" | "layout:<route>" | null */
function titleSource({ dir, route }) {
  const page = ["page.jsx", "page.js"].map((n) => path.join(dir, n)).find((f) => fs.existsSync(f));
  if (/export (const metadata|async function generateMetadata|function generateMetadata)/.test(fs.readFileSync(page, "utf8"))) {
    return { kind: "page" };
  }
  for (let d = dir; d.startsWith(APP) && d !== APP; d = path.dirname(d)) {
    const lf = layoutFile(d);
    if (lf && /export const metadata/.test(fs.readFileSync(lf, "utf8"))) {
      return { kind: "layout", file: lf, route: "/" + path.relative(APP, d).split(path.sep).join("/") };
    }
  }
  return { kind: "none" };
}

describe("page titles", () => {
  it("finds the app routes", () => {
    expect(routes.length).toBeGreaterThan(50);
  });

  it("every page route has a specific title source below the root layout", () => {
    const missing = routes.filter((r) => titleSource(r).kind === "none").map((r) => r.route);
    expect(missing).toEqual([]);
  });

  it("every layout-supplied title is specific, suffixed and not the generic brand", () => {
    for (const r of routes) {
      const src = titleSource(r);
      if (src.kind !== "layout") continue;
      const m = fs.readFileSync(src.file, "utf8").match(/pageMetadata\("([^"]+)"\)/);
      expect(m, `${src.file} must call pageMetadata("<route>")`).toBeTruthy();
      // The layout must name the route segment it lives in (a child inherits it).
      expect(m[1]).toBe(src.route);
      const title = pageMetadata(m[1]).title;
      expect(title).not.toBe(GENERIC_TITLE);
      expect(title.endsWith(` — ${TITLE_SUFFIX}`)).toBe(true);
    }
  });

  it("every page route's own label is specific (nav-model or override)", () => {
    for (const { route } of routes) {
      const t = pageTitle(route);
      // Pages with their own metadata (dynamic league pages, /design, waiver-wire) are exempt
      // from the helper's label table but must still not read as generic via the helper
      // unless they are covered by their own metadata export.
      const own = titleSource({ dir: path.join(APP, route), route }).kind === "page";
      if (!own) expect(t, route).not.toBe(GENERIC_TITLE);
    }
  });

  it("uses the nav labels verbatim for nav destinations", () => {
    for (const g of NAV_MODEL) {
      for (const i of g.items || []) {
        expect(pageTitle(i.href)).toBe(`${pageTitleFor(i.href)} — ${TITLE_SUFFIX}`);
      }
    }
    for (const i of SYSTEM_MODEL.items) {
      expect(pageTitle(i.href)).toBe(`${pageTitleFor(i.href)} — ${TITLE_SUFFIX}`);
    }
    expect(pageTitle("/trade")).toBe("Trade Calculator — Chase Upside");
    expect(pageTitle("/rosters")).toBe("Team Strength — Chase Upside");
  });

  it("dynamic pages that compute their own titles keep them", () => {
    for (const route of [
      "/league/franchise/[owner]",
      "/league/rivalry/[pair]",
      "/league/week/[season]/[week]",
      "/league/weekly/[season]/[week]/[matchup]",
      "/league/articles/[season]/[week]",
      "/league/player/[playerId]",
      "/league",
    ]) {
      const r = routes.find((x) => x.route === route);
      expect(r, route).toBeTruthy();
      expect(titleSource(r).kind, route).toBe("page");
    }
  });

  it("the root layout stays the generic fallback only", () => {
    const root = fs.readFileSync(path.join(APP, "layout.jsx"), "utf8");
    expect(root).toMatch(/title: "Chase Upside"/);
  });
});

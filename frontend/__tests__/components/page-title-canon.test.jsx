/**
 * page-title-canon — the `<h1>` half of the naming canon.
 *
 * ── Why this file exists ───────────────────────────────────────────────
 * `__tests__/nav-model.test.js` has claimed since it was written that
 *
 *   "the page <h1>s are asserted against the same strings in
 *    __tests__/components/page-title-canon.test.jsx."
 *
 * This file did not exist. `grep -rn "page-title-canon" frontend/`
 * returned exactly one hit: the comment above, claiming it did. So the
 * canon's three consumers — nav label, `pageTitleFor()`, and the page's
 * own `<h1>` — had the first two pinned and the third pinned by
 * nothing, behind a comment saying otherwise. That is
 * `docs/ORCHESTRATION.md` §6.15's "guard whose stated purpose and
 * actual predicate differ".
 *
 * The consequence, measured: PR #625 renamed /trade's heading from
 * "Trade Builder" to "Trade Calculator" on 2026-07-29. No fast test
 * objected. The only artifact that did was the nightly Playwright
 * suite — which was already red, stayed red for two more nights, and
 * went from 13 failures to 19.
 *
 * ── What it asserts, and why in two halves ─────────────────────────────
 * "The page's <h1> equals its canon name" cannot be checked by
 * rendering the pages: /draft is 5,185 lines, /trade 2,105, and they
 * need auth, providers, and live contract data. Rendering them here
 * would be a slow, flaky integration test that fails for reasons
 * unrelated to naming.
 *
 * So it is split into two cheap, total assertions whose conjunction is
 * the property we want:
 *
 *   1. MECHANISM — both PageHeader components turn `title` into the
 *      page's single <h1>. Rendered for real, once per canon name.
 *   2. WIRING — every canon route passes its canon string to a
 *      PageHeader. Read from source, because that is the fact that
 *      drifted and it is a fact about the source.
 *
 * (1) + (2) ⇒ every canon route's <h1> is its canon name, with no page
 * render required. If someone replaces PageHeader with a different
 * title mechanism, (1) fails. If someone renames a heading, (2) fails.
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { render, screen, cleanup } from "@testing-library/react";
import { describe, it, expect, afterEach } from "vitest";

import { PageHeader as DsPageHeader } from "@/components/ds/PageHeader";
import UiPageHeader from "@/components/ui/PageHeader";
import {
  CANON,
  DATA_DERIVED_TITLE_ROUTES,
  staticTitleRoutes,
} from "../helpers/naming-canon.js";

const APP_DIR = path.resolve(__dirname, "../../app");

afterEach(cleanup);

/**
 * Every `title=` passed to a `<PageHeader>` in one page file.
 *
 * Deliberately a narrow text parse rather than an AST walk, matching
 * the idiom `tests/api/test_source_registry_parity.py` already uses for
 * the source registry: we WANT this to fail loudly on an unusual edit
 * to how titles are declared, because that is drift too.
 *
 * `title={IDENT}` is resolved against module-level
 * `const IDENT = "..."` — /draft declares
 * `const DRAFT_PAGE_TITLE = "Draft Board"` and uses it twice.
 */
function pageHeaderTitles(source) {
  const constants = new Map();
  const constRe = /^\s*const\s+([A-Za-z_$][\w$]*)\s*=\s*"([^"]*)"\s*;/gm;
  for (const m of source.matchAll(constRe)) constants.set(m[1], m[2]);

  const titles = [];
  // Non-greedy up to the tag close; `[^]` would over-run into siblings.
  const headerRe = /<PageHeader\b(?<props>[\s\S]*?)(?:\/>|>)/g;
  for (const m of source.matchAll(headerRe)) {
    const t = /\btitle=(?:"([^"]*)"|\{\s*([A-Za-z_$][\w$]*)\s*\})/.exec(
      m.groups.props,
    );
    if (!t) continue;
    if (t[1] !== undefined) titles.push(t[1]);
    else if (constants.has(t[2])) titles.push(constants.get(t[2]));
    else titles.push(`{${t[2]}}`); // unresolved — surfaces in the diff
  }
  return titles;
}

function pageFileFor(route) {
  for (const ext of ["jsx", "js"]) {
    const p = path.join(APP_DIR, route, `page.${ext}`);
    if (fs.existsSync(p)) return p;
  }
  return null;
}

describe("page title canon — mechanism", () => {
  it("ds/PageHeader renders its title as the page's single h1", () => {
    render(<DsPageHeader title="Trade Calculator" />);
    const h1s = screen.getAllByRole("heading", { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent("Trade Calculator");
  });

  it("ui/PageHeader renders its title as the page's single h1", () => {
    render(<UiPageHeader title="Trade Calculator" />);
    const h1s = screen.getAllByRole("heading", { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent("Trade Calculator");
  });

  it("every canon name survives as an accessible h1 name", () => {
    // Guards the class of name that a heading component can mangle:
    // "Win-now vs Rebuild" (hyphen), "Waivers / FA"-style slashes,
    // "Fundamental Values" (case). Accessible-name computation, not
    // string identity, is what the E2E specs match on.
    for (const name of Object.values(CANON)) {
      render(<DsPageHeader title={name} />);
      expect(
        screen.getByRole("heading", { level: 1, name }),
        `canon name ${name} must be reachable by accessible name`,
      ).toBeInTheDocument();
      cleanup();
    }
  });
});

describe("page title canon — wiring", () => {
  it("every canon route has a page file", () => {
    const missing = Object.keys(CANON).filter((r) => !pageFileFor(r));
    expect(missing, "canon routes with no page.jsx/page.js").toEqual([]);
  });

  it("every canon route passes its canon name to a PageHeader", () => {
    const wrong = [];
    for (const route of staticTitleRoutes()) {
      const file = pageFileFor(route);
      if (!file) continue; // covered by the test above
      const titles = pageHeaderTitles(fs.readFileSync(file, "utf8"));
      if (!titles.includes(CANON[route])) {
        wrong.push({ route, expected: CANON[route], found: titles });
      }
    }
    // A failure here means a page heading and its nav label disagree —
    // the user-visible symptom is a nav entry that opens a page called
    // something else, and the CI symptom is the Playwright suite going
    // red overnight. Fix the page, or change the canon deliberately.
    expect(wrong, "pages whose <h1> is not their canon name").toEqual([]);
  });

  it("data-derived title exemptions are documented and still needed", () => {
    for (const [route, reason] of Object.entries(DATA_DERIVED_TITLE_ROUTES)) {
      expect(route in CANON, `${route} exempted but not in the canon`).toBe(true);
      expect(
        String(reason).length,
        `${route} needs a reason, not a bare exemption`,
      ).toBeGreaterThan(40);
    }
  });

  it("no page still uses a retired page name", () => {
    // The exact strings PR #625's naming canon replaced. A page
    // reintroducing one is a rename that only half landed.
    const retired = [
      "Trade Builder",
      "Signal Blotter",
      "Counter-Pitch",
      "Arbitrage Finder",
      "Trade Finder",
      "Dynasty Trade Calculator",
    ];
    const offenders = [];
    for (const route of Object.keys(CANON)) {
      const file = pageFileFor(route);
      if (!file) continue;
      const titles = pageHeaderTitles(fs.readFileSync(file, "utf8"));
      for (const t of titles) {
        if (retired.includes(t)) offenders.push({ route, title: t });
      }
    }
    expect(offenders, "pages titled with a retired name").toEqual([]);
  });
});

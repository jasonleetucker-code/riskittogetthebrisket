/**
 * V1-131 — nav capability gating for Consensus Edge, verified against
 * the DEPLOYED production site.
 *
 * Implements steps 4-8 of
 * docs/master-site-audit/evidence/V1-131/L3_PRODUCTION_RECIPE.md:
 * `/api/auth/status` publishes `features.consensusEdge.available` (the
 * canonical predicate, not the raw flag), and every nav offer surface —
 * desktop Market menu, mobile drawer, command palette, /more site map,
 * DOM-wide anchors — honours it. The route itself stays reachable
 * either way (gating removes the OFFER, never the page).
 *
 * BOTH branches are implemented; each test asserts the branch the
 * deployed build actually reports and records it as an annotation
 * (`branch: available=<bool>`), so the report says which invariant was
 * exercised rather than pretending both were.
 */
const {
  test,
  expect,
  prodUrl,
  getJson,
  annotate,
  desktopOnly,
  mobileOnly,
} = require("./helpers");

/** Recipe step 2: the capability block, asserted to be a REAL boolean. */
async function readCapability(page, testInfo) {
  const { status, body } = await getJson(page, "/api/auth/status");
  expect(status, "/api/auth/status must answer 200 to a session").toBe(200);
  const block = body?.features?.consensusEdge;
  expect(
    block,
    "features.consensusEdge missing from /api/auth/status — an older " +
      "build is deployed; the nav still fails closed but V1-131's " +
      "capability publication is not verified",
  ).toBeTruthy();
  expect(
    typeof block.available,
    "available must be a real boolean, not a truthy stand-in",
  ).toBe("boolean");
  annotate(testInfo, "branch", `available=${block.available}`);
  return block.available;
}

/** Record the deployed SHA (recipe step 1) — best-effort, annotated. */
async function annotateDeployedSha(page, testInfo) {
  const { body } = await getJson(page, "/api/status");
  const sha =
    body?.deployedSha || body?.gitSha || body?.sha || body?.version || null;
  annotate(testInfo, "deployed-sha", sha || "not published by /api/status");
}

test.describe("V1-131: nav gating on the deployed shell", () => {
  test("capability and the board endpoint agree (recipe step 3)", async ({
    prodPage: page,
  }, testInfo) => {
    desktopOnly(test, testInfo);
    await annotateDeployedSha(page, testInfo);
    const available = await readCapability(page, testInfo);

    const res = await page.request.get(
      prodUrl("/api/consensus-edge/players"),
      { timeout: 45_000 },
    );
    const boardStatus = res.status();
    annotate(testInfo, "board-endpoint-status", String(boardStatus));

    // Disagreement is THE defect this row exists to prevent — the one
    // thing the recipe says cannot be waved through.
    if (available) {
      expect(
        boardStatus,
        "available=true but the board endpoint does not serve",
      ).toBe(200);
    } else {
      expect(
        boardStatus,
        "available=false but the board endpoint is not answering 503 — " +
          "the capability and the board disagree",
      ).toBe(503);
    }
  });

  test("desktop Market menu, palette, /more and DOM anchors honour the capability (recipe steps 4-5)", async ({
    prodPage: page,
  }, testInfo) => {
    desktopOnly(test, testInfo);
    const available = await readCapability(page, testInfo);

    await page.goto(prodUrl("/rankings"), { waitUntil: "domcontentloaded" });
    // Shell readiness: the top-nav search affordance renders once the
    // client auth check resolves (helpers/journey.js documents it as
    // the "authenticated UI is hydrated" signal).
    await expect(page.locator(".shell-search-btn")).toBeVisible({
      timeout: 60_000,
    });

    // ── Market menu ──────────────────────────────────────────────────
    await page.getByRole("button", { name: "Market menu" }).click();
    const marketMenu = page.locator('[role="menu"][aria-label="Market"]');
    await expect(marketMenu).toBeVisible();
    const menuItems = marketMenu.locator('[role="menuitem"]');
    const itemTexts = await menuItems.allInnerTexts();
    annotate(testInfo, "market-menu-items", itemTexts.join(" | "));

    // Negative control FIRST, both branches: the Market group itself
    // must be healthy, or an empty menu would "pass" the gating check.
    for (const label of [
      "Source Disagreement",
      "Sharp Tracker",
      "Sharp Roster Percentage",
    ]) {
      await expect(
        marketMenu.getByRole("menuitem", { name: new RegExp(label) }),
        `Market menu lost its "${label}" entry — the nav is broken ` +
          "generally, so the Consensus Edge assertion below would be vacuous",
      ).toBeVisible();
    }

    const ceMenuItem = marketMenu.getByRole("menuitem", {
      name: /Consensus Edge/,
    });
    if (available) {
      await expect(
        ceMenuItem,
        "available=true but the Market menu does not offer Consensus Edge",
      ).toBeVisible();
    } else {
      await expect(
        ceMenuItem,
        "available=false but the Market menu offers Consensus Edge",
      ).toHaveCount(0);
    }

    // DOM-wide anchor census, measured while the menu is OPEN so the
    // zero cannot be an artifact of a collapsed menu.
    const anchorCount = await page
      .locator('a[href="/consensus-edge"]')
      .count();
    if (available) {
      expect(
        anchorCount,
        "available=true but no /consensus-edge anchor exists with the Market menu open",
      ).toBeGreaterThan(0);
    } else {
      expect(
        anchorCount,
        'available=false but a[href="/consensus-edge"] exists in the DOM',
      ).toBe(0);
    }
    await page.keyboard.press("Escape");

    // ── Command palette ──────────────────────────────────────────────
    await page.locator(".shell-search-btn").click();
    const paletteInput = page.getByLabel("Search players, picks, and pages");
    await expect(paletteInput).toBeVisible();
    await paletteInput.fill("consensus");
    const ceOption = page.locator(".shell-palette-option", {
      has: page.locator(".shell-palette-option-name", {
        hasText: /Consensus Edge/i,
      }),
    });
    if (available) {
      await expect(
        ceOption.first(),
        "available=true but the palette returns no Consensus Edge target for 'consensus'",
      ).toBeVisible({ timeout: 15_000 });
    } else {
      // Give the palette a moment to produce whatever it will produce,
      // keyed on its own settled states rather than a sleep: either
      // options render or the explicit empty state does.
      await expect(
        page
          .locator(".shell-palette-option")
          .first()
          .or(page.locator(".shell-palette-empty")),
      ).toBeVisible({ timeout: 15_000 });
      await expect(
        ceOption,
        "available=false but the command palette offers Consensus Edge",
      ).toHaveCount(0);
    }
    const paletteNames = await page
      .locator(".shell-palette-option-name")
      .allInnerTexts();
    annotate(
      testInfo,
      "palette-results-for-consensus",
      paletteNames.join(" | ") || "(none)",
    );
    await page.keyboard.press("Escape");

    // ── /more site map ───────────────────────────────────────────────
    await page.goto(prodUrl("/more"), { waitUntil: "domcontentloaded" });
    // Scoped to the site-map panels (frontend/app/more/page.jsx,
    // .shell-sitemap-panel): observed on production run 33528409461
    // (2026-09-01), an unscoped `a.shell-menu-item[href="/edge"]` resolved
    // to TWO elements — one visible, one carrying `hidden`. The visible
    // one is confirmed correct (the run's own accessibility snapshot shows
    // exactly one "Source Disagreement" link under Market, reachable and
    // correctly labelled), so the hidden second node is not a user-facing
    // regression; scoping to the page's own site-map container makes the
    // negative control unambiguous regardless of the second node's exact
    // origin, which static review of NavMenu.jsx/TopBar.jsx did not
    // conclusively identify (NavMenu's dropdown items are conditionally
    // rendered on `open`, and the header's own persistent Market link
    // carries a different class, `shell-nav-link`, so neither is a
    // confirmed source — left for a follow-up if it recurs elsewhere).
    await expect(
      page.locator('.shell-sitemap-panel a.shell-menu-item[href="/edge"]'),
      "/more site map should list Source Disagreement (negative control)",
    ).toBeVisible({ timeout: 30_000 });
    const moreCeLinks = page.locator('a[href="/consensus-edge"]');
    if (available) {
      await expect(
        moreCeLinks.first(),
        "available=true but /more does not link Consensus Edge",
      ).toBeVisible();
    } else {
      await expect(
        moreCeLinks,
        "available=false but /more links /consensus-edge",
      ).toHaveCount(0);
    }
  });

  test("hard reload of a private route: zero consensus-edge requests, exactly one auth/status (recipe step 6)", async ({
    prodPage: page,
  }, testInfo) => {
    desktopOnly(test, testInfo);
    const available = await readCapability(page, testInfo);
    annotate(
      testInfo,
      "note",
      `network invariant asserted with available=${available} — the shell ` +
        "must never probe consensus-edge from a private route in either branch",
    );

    await page.goto(prodUrl("/rankings"), { waitUntil: "domcontentloaded" });
    await expect(page.locator(".shell-search-btn")).toBeVisible({
      timeout: 60_000,
    });

    // Count only from the reload onward — the recipe's step is a hard
    // reload of an already-loaded private route.
    const consensusEdgeRequests = [];
    let authStatusCount = 0;
    page.on("request", (req) => {
      const url = req.url();
      if (url.includes("/api/consensus-edge")) consensusEdgeRequests.push(url);
      if (url.includes("/api/auth/status")) authStatusCount += 1;
    });

    await page.reload({ waitUntil: "domcontentloaded" });
    // Settle on the page's own readiness markers, then let trailing
    // shell requests drain (bounded network-idle, not a bare sleep).
    await expect(page.locator(".shell-search-btn")).toBeVisible({
      timeout: 60_000,
    });
    await expect(
      page
        .locator(".ds-table-wrap table tbody tr.rankings-row-clickable")
        .first(),
      "the rankings board should render after reload",
    ).toBeVisible({ timeout: 60_000 });
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});

    expect(
      consensusEdgeRequests,
      "the shell made requests to /api/consensus-edge/* from a private " +
        "route — the capability must ride /api/auth/status, not a " +
        "per-page probe (this erodes V1-108)",
    ).toEqual([]);
    expect(
      authStatusCount,
      "/api/auth/status should be requested exactly once on a shell load",
    ).toBe(1);
  });

  test("the /consensus-edge route itself stays reachable (recipe step 8)", async ({
    prodPage: page,
  }, testInfo) => {
    desktopOnly(test, testInfo);
    const available = await readCapability(page, testInfo);

    await page.goto(prodUrl("/consensus-edge"), {
      waitUntil: "domcontentloaded",
    });
    await expect(
      page.getByRole("heading", { level: 1, name: /^Consensus Edge$/ }),
      "direct navigation must render the page's own <h1> — gating " +
        "removes the offer, never the route",
    ).toBeVisible({ timeout: 60_000 });
    annotate(
      testInfo,
      "route-direct-nav",
      `renders own h1 with available=${available}`,
    );
  });

  test("mobile drawer honours the capability at 390x844 (recipe step 5, mobile)", async ({
    prodPage: page,
  }, testInfo) => {
    mobileOnly(test, testInfo);
    const available = await readCapability(page, testInfo);

    await page.goto(prodUrl("/rankings"), { waitUntil: "domcontentloaded" });
    const tabbar = page.locator('nav.shell-tabbar[aria-label="Primary"]');
    await expect(tabbar).toBeVisible({ timeout: 60_000 });

    // `domcontentloaded` + the tabbar's visibility only prove the SSR
    // markup painted — the Menu button's onClick is wired by React
    // hydration, which can still be in flight. A native click landing
    // in that gap dispatches a real DOM event with nobody listening for
    // it yet, and once hydration completes there is no replay: the
    // drawer just never opens. Give hydration a bounded chance to
    // finish (same networkidle-with-fallback pattern this file already
    // uses for the desktop reload test at line ~254) before treating a
    // still-closed drawer as a real gating failure.
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});

    const menuButton = tabbar.getByRole("button", { name: /Menu/ });
    const drawerGroups = page.locator(".shell-drawer-group");
    await menuButton.click();
    try {
      await expect(drawerGroups.first()).toBeVisible({ timeout: 5_000 });
    } catch {
      // One retry covers a click that still landed pre-hydration despite
      // the networkidle wait above (e.g. a slow WebKit mobile runner) —
      // genuine gating defects fail this too, since neither attempt
      // opens the drawer.
      await menuButton.click();
      await expect(drawerGroups.first()).toBeVisible({ timeout: 15_000 });
    }

    // Negative control: the Market group renders with its ungated entries.
    const marketGroup = drawerGroups.filter({
      has: page.locator(".shell-drawer-group-label", { hasText: /^Market$/ }),
    });
    await expect(
      marketGroup,
      "mobile drawer lost its Market group — gating assertion would be vacuous",
    ).toHaveCount(1);
    for (const href of [
      "/edge",
      "/market/sharp-tracker",
      "/market/sharp-roster-percentage",
    ]) {
      await expect(
        marketGroup.locator(`a[href="${href}"]`),
        `mobile drawer Market group lost its ${href} entry`,
      ).toHaveCount(1);
    }

    const ceLinks = page.locator('a[href="/consensus-edge"]');
    if (available) {
      await expect(
        ceLinks.first(),
        "available=true but the mobile drawer does not offer Consensus Edge",
      ).toBeVisible();
    } else {
      await expect(
        ceLinks,
        "available=false but the mobile drawer offers /consensus-edge",
      ).toHaveCount(0);
    }
    annotate(
      testInfo,
      "drawer-market-links",
      (await marketGroup.locator("a").allInnerTexts()).join(" | "),
    );
  });
});

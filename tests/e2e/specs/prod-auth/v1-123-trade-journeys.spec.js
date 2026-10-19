/**
 * V1-123 Phase 1 — trade surfaces beyond /trade, on production.
 *
 * Ports ../journey-trade.spec.js's coverage of /trades, the /rankings
 * screen deep-link, /arbitrage, and POST /api/trade/finder onto a real
 * authenticated production session. Deliberately excludes that source
 * spec's "/trade renders the builder" test: v1-45-trade-surface.spec.js
 * already covers /trade in prod-auth (field-for-field against
 * POST /api/trade/simulate) — porting it again would be duplicate
 * coverage, not new evidence. This is exactly the extension
 * docs/v1-123-browser-workflow-matrix/SCOPING.md's Phase 1 calls for:
 * "extends v1-45 to /arbitrage and /trades."
 */
const { test, expect, prodUrl, getJson, annotate } = require("./helpers");

const SEL = {
  boardRow: ".ds-table-wrap table tbody tr.rankings-row-clickable",
  tradeLedgerEntry: ".trades-page a.ds-panel",
  arbitrageTradeCard: ".arbitrage-trade-card",
};

const TITLE = {
  "/rankings": "Rankings",
  "/arbitrage": "Arbitrage",
};

function titleFor(route) {
  return new RegExp(`^${TITLE[route]}$`);
}

function pageHeading(page, name) {
  return page.getByRole("heading", { level: 1, name });
}

async function awaitStreamSettled(page, { timeout = 30_000 } = {}) {
  await page
    .waitForFunction(
      () =>
        !document.querySelector('div[hidden][id^="S:"]') &&
        !document.querySelector('template[id^="B:"]'),
      null,
      { timeout },
    )
    .catch(() => {});
}

test.describe("V1-123 Phase 1: trade journeys beyond /trade (production)", () => {
  test("/trades renders history (real trades or explicit empty state) on production", async ({
    prodPage: page,
  }, testInfo) => {
    await page.goto(prodUrl("/trades"), { waitUntil: "domcontentloaded" });

    const settled = page.locator(SEL.tradeLedgerEntry).or(page.getByText(/No trades found/i));
    await expect(settled.first()).toBeVisible({ timeout: 60_000 });
    const entryCount = await page.locator(SEL.tradeLedgerEntry).count();
    annotate(
      testInfo,
      "trades-history",
      entryCount > 0 ? `${entryCount} real trade entries` : "explicit empty state",
    );
  });

  test("a /rankings screen deep-link narrows the board to its question on production", async ({
    prodPage: page,
  }, testInfo) => {
    await page.goto(prodUrl("/rankings?screen=wr-gaps"), { waitUntil: "domcontentloaded" });

    await expect(pageHeading(page, titleFor("/rankings"))).toBeVisible({ timeout: 60_000 });

    const rows = page.locator(SEL.boardRow);
    await expect(rows.first(), "screened board should render rows").toBeVisible({
      timeout: 60_000,
    });
    const count = await rows.count();
    expect(count, "wr-gaps must match at least one player on production").toBeGreaterThan(0);

    const positions = await page.locator(`${SEL.boardRow} td[data-col="pos"]`).allInnerTexts();
    expect(positions.length, "pos column should be addressable").toBeGreaterThan(0);
    const nonWr = positions.map((p) => p.trim()).filter((p) => p && !/^WR\b/.test(p));
    expect(nonWr, `wr-gaps returned non-WR rows: ${nonWr.slice(0, 5).join(", ")}`).toEqual([]);
    annotate(testInfo, "screen-filter", `${count} WR-only rows on production`);
  });

  test("/arbitrage scans and renders either trades or an explicit empty state on production", async ({
    prodPage: page,
  }, testInfo) => {
    await page.goto(prodUrl("/arbitrage"), { waitUntil: "domcontentloaded" });
    await awaitStreamSettled(page);

    await expect(pageHeading(page, titleFor("/arbitrage"))).toBeVisible({ timeout: 30_000 });
    // Owner directive 2026-10-18 (d99ac2c13f, "tools first"): Golden Upgrades
    // is the default tool and the Package Scan is its own tab, and no research
    // table renders ahead of the tools — the same contract the local journey
    // (tests/e2e/specs/journey-trade.spec.js) holds the page to.
    const tabs = page.getByRole("tab");
    await expect(tabs.first()).toHaveText("Golden Upgrades", { timeout: 30_000 });
    await page.getByRole("tab", { name: "Package Scan" }).click();
    await expect(page.getByText(/Package scan ready/i)).toBeVisible({ timeout: 30_000 });

    const teamSelect = page.getByLabel("Your team");
    await expect
      .poll(async () => teamSelect.locator("option").count(), {
        message: "team selector should populate from the contract",
        timeout: 60_000,
      })
      .toBeGreaterThan(0);

    // Read first, click only when no scan is in flight -- re-clicking is
    // not idempotent (a click on the same tick a scan settles tears the
    // result back down), so the poll must never fire a second click into
    // an in-progress scan.
    const scan = page.getByRole("button", { name: /Find trade packages|Scanning/i });
    const settled = page
      .locator(SEL.arbitrageTradeCard)
      .or(page.getByText(/No package arbitrage found/i));

    await expect
      .poll(
        async () => {
          const count = await settled.count();
          if (count > 0) return count;
          if (await scan.isEnabled()) await scan.click();
          return 0;
        },
        {
          message: "scan should resolve to trades or the explicit empty state",
          timeout: 90_000,
          intervals: [500, 1000, 2000, 3000, 5000],
        },
      )
      .toBeGreaterThan(0);

    const cardCount = await page.locator(SEL.arbitrageTradeCard).count();
    annotate(
      testInfo,
      "arbitrage-scan",
      cardCount > 0 ? `${cardCount} real trade cards` : "explicit empty state",
    );
  });

  test("/arbitrage player-level edge table and filters render real board content on production", async ({
    prodPage: page,
  }, testInfo) => {
    await page.goto(prodUrl("/arbitrage"), { waitUntil: "domcontentloaded" });
    await awaitStreamSettled(page);

    await expect(pageHeading(page, titleFor("/arbitrage"))).toBeVisible({ timeout: 30_000 });

    // Since the 2026-10-18 "tools first" directive the player-level table
    // lives in the collapsed "Player-level market research" panel, which
    // does not mount its body until opened.  Open it, then scope every
    // lookup to it — the default tool above may render its own content.
    const disclosure = page.getByRole("button", { name: "Player-level market research" });
    await expect(disclosure).toHaveAttribute("aria-expanded", "false", { timeout: 30_000 });
    await disclosure.click();
    await expect(disclosure).toHaveAttribute("aria-expanded", "true");
    // `.last()`: the innermost panel holding the disclosure (an enclosing
    // panel, if a future layout adds one, would also match the filter).
    const research = page.locator(".ds-panel").filter({ has: disclosure }).last();

    const visibleTile = research.getByText("Visible", { exact: true });
    await expect(visibleTile).toBeVisible({ timeout: 30_000 });

    const table = research.getByRole("table");
    const emptyState = research.getByText(/No player-level edges under these filters/i);
    const settled = table.or(emptyState);
    await expect(settled.first()).toBeVisible({ timeout: 30_000 });

    const hasTable = await table.isVisible().catch(() => false);
    if (hasTable) {
      const rows = table.locator("tbody tr");
      const rowCount = await rows.count();
      expect(rowCount, "player-level edge table rendered with no rows").toBeGreaterThan(0);
      annotate(testInfo, "arbitrage-player-level", `${rowCount} edge rows, populated`);
    } else {
      annotate(testInfo, "arbitrage-player-level", "explicit empty state at default threshold");
    }

    // The Players filter narrows the population (it replaced "Player
    // type") -- exercise it and require the panel to still resolve to a
    // table or the same empty state, never an error.  Asserted, not probed:
    // a filter that silently vanished used to skip this check.
    const players = research.getByLabel("Players", { exact: true });
    await expect(players).toBeVisible({ timeout: 15_000 });
    await players.selectOption("defense");
    await expect(table.or(emptyState).first()).toBeVisible({ timeout: 15_000 });
    await players.selectOption("both");
    await expect(table.or(emptyState).first()).toBeVisible({ timeout: 15_000 });
  });

  test("POST /api/trade/finder returns arbitrage trades for a real roster on production", async ({
    prodPage: page,
  }) => {
    const { status, body: contract } = await getJson(page, "/api/data?view=app");
    expect(status).toBe(200);
    const teams = contract?.sleeper?.teams || [];
    expect(
      teams.length,
      "contract served no Sleeper rosters -- the finder cannot be exercised",
    ).toBeGreaterThan(0);

    const myTeam = teams[0].name;
    const res = await page.request.post(prodUrl("/api/trade/finder"), {
      data: { myTeam, opponentTeams: ["all"] },
    });
    expect(res.status(), await res.text().catch(() => "")).toBe(200);
    const body = await res.json();

    expect(Array.isArray(body.trades), "finder response must carry a trades array").toBeTruthy();
    expect(body).toHaveProperty("metadata");
    expect(body).toHaveProperty("leagueKey");
    expect(
      body.trades.length,
      "finder returned zero trades for a real production roster",
    ).toBeGreaterThan(0);

    for (const trade of body.trades.slice(0, 5)) {
      expect(Array.isArray(trade.give)).toBeTruthy();
      expect(Array.isArray(trade.receive)).toBeTruthy();
      expect(trade.give.length).toBeGreaterThan(0);
      expect(trade.receive.length).toBeGreaterThan(0);
      for (const asset of [...trade.give, ...trade.receive]) {
        expect(String(asset.name || "").length).toBeGreaterThan(0);
      }
    }
  });
});

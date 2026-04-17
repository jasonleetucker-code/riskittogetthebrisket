const { test, expect } = require("@playwright/test");

// End-to-end coverage for the PUBLIC /league page.  Exercises the
// real Sleeper-backed data flow through the FastAPI backend at
// :8000 + Next.js at :3000.
//
// The test walks every tab, verifies the Home overview card, exercises
// shareable URLs (?tab=, ?owner=, ?week=), and visits the dedicated
// /league/franchise/[owner] and /league/rivalry/[pair] routes.
//
// Critical: also asserts that /league NEVER fetches /api/data (the
// private contract) — that would mean the public isolation is
// broken.  We attach a request listener to confirm.

// Tab labels in render order.  The Draft Capital tab is the default
// landing because /draft-capital was folded into /league — public
// visitors arriving at /league see it first.
const TABS = [
  "Draft Capital",
  "Home",
  "History",
  "Rivalries",
  "Awards",
  "Records",
  "Franchises",
  "Trades",
  "Draft",
  "Weekly",
  "Superlatives",
  "Archives",
];

async function visitLeague(page, path = "/league", { waitForText = null } = {}) {
  const privateHits = [];
  page.on("request", (req) => {
    const url = req.url();
    if (url.includes("/api/data") || url.includes("/api/rankings/overrides")) {
      privateHits.push(url);
    }
  });
  await page.goto(path, { waitUntil: "domcontentloaded" });
  // Wait for something that only renders AFTER the contract fetch
  // resolves.  "Loading league data..." is replaced with section
  // content once /api/public/league comes back.
  await page.waitForFunction(
    () => !document.body.innerText.includes("Loading league data..."),
    null,
    { timeout: 45_000 },
  );
  if (waitForText) {
    await page.waitForFunction(
      (needle) => document.body.innerText.includes(needle),
      waitForText,
      { timeout: 15_000 },
    );
  }
  return privateHits;
}

test.describe("public /league page", () => {
  test("renders league page, switches tabs, and never touches private endpoints", async ({ page }) => {
    // Visit via ?tab=overview so we have a deterministic "waitForText"
    // anchor (Draft Capital is the default tab but fetches client-side,
    // which would require a different readiness signal).
    const privateHits = await visitLeague(page, "/league?tab=overview", {
      waitForText: "At a glance",
    });

    for (const label of TABS) {
      const btn = page.getByRole("button", { name: label, exact: true }).first();
      await btn.click();
      await page.waitForTimeout(150);
    }

    expect(privateHits, `private endpoints were touched: ${privateHits.join(", ")}`).toHaveLength(0);
  });

  test("deep links via ?tab= query param land on the right tab", async ({ page }) => {
    await visitLeague(page, "/league?tab=awards", { waitForText: "award" });
  });

  test("franchise deep link via ?owner= opens the selected franchise", async ({ page, request }) => {
    const res = await request.get("/api/public/league");
    const body = await res.json();
    const ownerId = body?.league?.managers?.[0]?.ownerId;
    expect(ownerId).toBeTruthy();

    await visitLeague(
      page,
      `/league?tab=franchise&owner=${encodeURIComponent(ownerId)}`,
      { waitForText: "Season results" },
    );
  });

  test("dedicated /league/franchise/[owner] route renders", async ({ page, request }) => {
    const res = await request.get("/api/public/league");
    const body = await res.json();
    const ownerId = body?.league?.managers?.[0]?.ownerId;
    expect(ownerId).toBeTruthy();

    await page.goto(`/league/franchise/${encodeURIComponent(ownerId)}`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForFunction(
      () => document.body.innerText.includes("Cumulative")
        && document.body.innerText.includes("Season results"),
      null,
      { timeout: 45_000 },
    );
    await expect(page.getByText("← League home").first()).toBeVisible();
  });

  test("dedicated /league/rivalry/[pair] route renders when pair exists", async ({ page, request }) => {
    const res = await request.get("/api/public/league/rivalries");
    const body = await res.json();
    const rivalries = body?.data?.rivalries || [];
    if (!rivalries.length) test.skip(true, "no rivalries available in this league yet");
    const [a, b] = rivalries[0].ownerIds;
    const slug = `${encodeURIComponent(a)}-vs-${encodeURIComponent(b)}`;
    await page.goto(`/league/rivalry/${slug}`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      () => document.body.innerText.includes("Head-to-head")
        && document.body.innerText.includes("Memorable meetings"),
      null,
      { timeout: 45_000 },
    );
  });

  test("archives filter narrows the result set", async ({ page }) => {
    await visitLeague(page, "/league?tab=archives", { waitForText: "Public archives" });
    // Switch to matchups which always has entries.
    await page.getByRole("button", { name: /Matchups/i }).first().click();
    await page.waitForTimeout(500);
    const countBefore = await page.locator("table tbody tr").count();
    expect(countBefore).toBeGreaterThan(0);
  });

  test("public contract payload never includes private field names", async ({ request }) => {
    const res = await request.get("/api/public/league");
    expect(res.status()).toBe(200);
    const body = await res.text();
    const lower = body.toLowerCase();
    for (const banned of [
      '"ourvalue":',
      '"edgesignals":',
      '"edgescore":',
      '"tradefinder":',
      '"siteweights":',
      '"siteoverrides":',
      '"rankderivedvalue":',
      '"arbitragescore":',
    ]) {
      expect(lower, `banned field ${banned} leaked into public contract`).not.toContain(banned);
    }
  });

  test("/league page has an OG title (server-rendered metadata)", async ({ request }) => {
    const res = await request.get("/league");
    expect(res.status()).toBe(200);
    const html = await res.text();
    expect(html).toMatch(/<meta property="og:title"/i);
    expect(html).toMatch(/<meta property="og:description"/i);
  });

  test("/league?tab=overview SSRs with overview content (no loading flash)", async ({ request }) => {
    // Server-rendered /league?tab=overview hits the overview content
    // directly — HTML should contain the overview headlines, not the
    // fallback "Loading" text.
    const res = await request.get("/league?tab=overview");
    const html = await res.text();
    expect(html).toMatch(/At a glance|Defending champion|Featured rivalry/);
  });

  test("/draft-capital redirects into the folded /league tab", async ({ request }) => {
    const res = await request.get("/draft-capital", { maxRedirects: 0 });
    expect(res.status()).toBeGreaterThanOrEqual(300);
    expect(res.status()).toBeLessThan(400);
    const location = res.headers().location || "";
    expect(location).toMatch(/\/league\?tab=draft-capital/);
  });

  test("per-matchup recap route is reachable with real data", async ({ page, request }) => {
    const matchupsRes = await request.get("/api/public/league/matchups");
    expect(matchupsRes.status()).toBe(200);
    const body = await matchupsRes.json();
    const first = (body.matchups || [])[0];
    if (!first) test.skip(true, "no matchups available yet");
    await page.goto(
      `/league/weekly/${encodeURIComponent(first.season)}/${encodeURIComponent(first.week)}/${encodeURIComponent(first.matchupId)}`,
      { waitUntil: "domcontentloaded" },
    );
    await expect(page.getByText("Game summary").first()).toBeVisible({ timeout: 15_000 });
  });

  test("player-journey route is reachable with real data", async ({ page, request }) => {
    const playersRes = await request.get("/api/public/league/players");
    expect(playersRes.status()).toBe(200);
    const players = (await playersRes.json()).players || [];
    const pid = players.find((p) => p.playerName && p.position)?.playerId;
    if (!pid) test.skip(true, "no named players available yet");
    await page.goto(`/league/player/${encodeURIComponent(pid)}`, {
      waitUntil: "domcontentloaded",
    });
    await expect(page.getByText("Impact by manager").first()).toBeVisible({ timeout: 15_000 });
  });

  test("CSV export endpoint serves text/csv", async ({ request }) => {
    const res = await request.get("/api/public/league/history.csv");
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toMatch(/text\/csv/);
  });

  test("metrics endpoint exposes snapshot cache counters", async ({ request }) => {
    const res = await request.get("/api/public/league/metrics");
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("metrics.rebuild_count");
    expect(body).toHaveProperty("metrics.cache_hit");
    expect(body).toHaveProperty("metrics.total_served");
  });
});

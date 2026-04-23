/**
 * Critical smoke suite — catches the kind of regression that makes
 * the whole site white-screen.  Every test here is a lightweight
 * "does X route render without throwing" check.  We deliberately
 * don't assert on specific data content (that's for unit tests);
 * this layer exists to stop regressions where a chunk is missing,
 * a component crashes on mount, or an endpoint returns a non-2xx.
 *
 * Add a test here whenever a deploy-time regression slips through.
 * The most expensive part of an outage isn't the fix — it's
 * knowing you broke something before the user tells you.
 */
const { test, expect } = require("@playwright/test");

const PUBLIC_ROUTES = [
  { path: "/", mustHave: /Risk It/i },
  { path: "/league", mustHave: /League|Rivalries|Standings|Champions/i },
  { path: "/login", mustHave: /Sign in/i },
];

const AUTH_GATED_ROUTES = [
  { path: "/rankings", mustHave: /Rankings|Players/i },
  { path: "/trade", mustHave: /Trade/i },
  { path: "/draft", mustHave: /Draft/i },
  { path: "/edge", mustHave: /Edge/i },
  { path: "/rosters", mustHave: /Roster/i },
  { path: "/settings", mustHave: /Settings/i },
  { path: "/more", mustHave: /More/i },
  { path: "/tools/trade-coverage", mustHave: /Trade Coverage/i },
];

const PUBLIC_API_ROUTES = [
  "/api/health",
  "/api/data",
  "/api/data/rank-history?days=30",
  "/api/terminal",
];

const AUTH_GATED_API_ROUTES = [
  "/api/user/state",
  "/api/trade/simulate",
];

test.describe("critical smoke — public routes", () => {
  for (const { path, mustHave } of PUBLIC_ROUTES) {
    test(`GET ${path} renders with no console errors`, async ({ page }) => {
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      page.on("console", (msg) => {
        if (msg.type() === "error") {
          const text = msg.text();
          // Chrome noise that doesn't indicate a real problem
          if (/Failed to load resource/i.test(text)) return;
          errors.push(text);
        }
      });
      const res = await page.goto(path, { waitUntil: "networkidle", timeout: 30_000 });
      expect(res?.status(), `${path} should return 200`).toBeLessThan(400);
      await expect(page.locator("body")).toContainText(mustHave, { timeout: 10_000 });
      expect(errors, `${path} should not log JS errors`).toEqual([]);
    });
  }
});

test.describe("critical smoke — auth-gated routes redirect to /login", () => {
  for (const { path } of AUTH_GATED_ROUTES) {
    test(`GET ${path} (unauthenticated) redirects without crashing`, async ({ page }) => {
      const res = await page.goto(path, { waitUntil: "domcontentloaded", timeout: 30_000 });
      expect(res?.status(), `${path} should not 500`).toBeLessThan(500);
      // Redirect → /login?next=... OR a 401 page.  Either is fine,
      // we just need the route to not crash.
      const url = page.url();
      const body = await page.locator("body").innerText();
      expect(
        url.includes("/login") || body.length > 0,
        `${path} should redirect or render something`,
      ).toBeTruthy();
    });
  }
});

test.describe("critical smoke — public API", () => {
  for (const path of PUBLIC_API_ROUTES) {
    test(`GET ${path} returns 2xx (or 503 if cold)`, async ({ request }) => {
      const res = await request.get(path);
      // /api/data returns 503 when the first scrape hasn't completed;
      // /api/terminal does the same.  Both are acceptable — we're
      // checking the route EXISTS and doesn't 404 / 500, not that
      // the backend has data.
      expect(
        [200, 503].includes(res.status()),
        `${path} returned ${res.status()}`,
      ).toBeTruthy();
      // Body should be valid JSON (or empty for 503).
      if (res.status() === 200) {
        const body = await res.json();
        expect(body).toBeDefined();
      }
    });
  }
});

test.describe("critical smoke — auth-gated API returns 401 when unauthenticated", () => {
  test("GET /api/user/state → 401", async ({ request }) => {
    const res = await request.get("/api/user/state");
    expect(res.status()).toBe(401);
  });

  test("POST /api/trade/simulate → 401", async ({ request }) => {
    const res = await request.post("/api/trade/simulate", {
      data: { playersIn: [], playersOut: [] },
    });
    expect(res.status()).toBe(401);
  });

  test("POST /api/user/signals/dismiss → 401", async ({ request }) => {
    const res = await request.post("/api/user/signals/dismiss", {
      data: { signalKey: "test::tag" },
    });
    expect(res.status()).toBe(401);
  });
});

test.describe("critical smoke — terminal endpoint contracts", () => {
  test("GET /api/terminal returns publicMode payload when anonymous", async ({ request }) => {
    const res = await request.get("/api/terminal");
    if (res.status() === 503) {
      test.info().annotations.push({
        type: "skip",
        description: "live contract not loaded yet",
      });
      return;
    }
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.authenticated).toBe(false);
    expect(body.meta?.publicMode).toBe(true);
    // Private fields should be nulled / empty.
    expect(body.team).toBeNull();
    expect(body.signals).toEqual([]);
    expect(body.portfolio).toBeNull();
    // Public fields should still be populated when data exists.
    expect(body.movers).toBeDefined();
    expect(Array.isArray(body.movers.league)).toBe(true);
    expect(Array.isArray(body.movers.top150)).toBe(true);
    expect(body.trendWindows).toEqual([7, 30, 90, 180]);
  });

  test("rank-history endpoint clamps days to MAX_SNAPSHOTS", async ({ request }) => {
    const res = await request.get("/api/data/rank-history?days=9999");
    if (res.status() === 503) return;
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.days).toBeLessThanOrEqual(365 * 3);
    expect(body.history).toBeDefined();
  });
});

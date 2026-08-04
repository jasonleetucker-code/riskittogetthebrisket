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
// Page navigations below go through pageUrl(). Until #555 they did NOT —
// they were the last two bare `page.goto(path)` calls in the suite, and
// they were correct that way, because their subject WAS the backend's
// page proxy. That proxy is deleted, so a bare goto here now resolves
// against baseURL (:8000) and gets a 404 from a backend that serves only
// /api/. The API blocks further down deliberately keep resolving against
// baseURL — that is why baseURL stays on :8000.
const { pageUrl } = require("../helpers/journey");

const PUBLIC_ROUTES = [
  // The shell brands the chrome "Chase Upside" (renamed from "Brisket"
  // 2026-07-27; the Sleeper LEAGUE is still called "Risk It To Get The
  // Brisket" and that name is deliberately untouched).  An
  // unauthenticated visit lands on the sign-in surface.  Assert on the
  // brand, which is present in the shell on every route and every auth
  // state — this check exists to prove the route renders at all, not to
  // pin the marketing copy.
  { path: "/", mustHave: /Chase Upside/i },
  // ``/league`` is BACK in this list, on a measurement rather than on a
  // hope.  It was pulled twice for reasons that both later evaporated:
  // first the backend proxy's 5s timeout (deleted with the proxy in
  // #555), then the SSR itself at 7-19s — 15.78s p100 — which blew the
  // 15s content budget on the assertion below regardless of who served
  // it.  The note here said, correctly, that "the stated cause is gone"
  // is not the same claim as "it is fast enough now", and that it must
  // stay out until someone measured again.
  //
  // Measured 2026-08-04 against production, six samples: TTFB
  // 0.55-1.01s, total 0.75-1.20s, 91.9 KB document.  The franchise
  // deep-link that produced the 15.78s p100 is now 0.57s / 1.06s.  That
  // is ~13x under the budget, not marginally under it.
  //
  // #667 is what fixed it, and the mechanism is worth knowing before
  // anyone "optimises" it back: the page now fetches ONE section
  // (overview, 15 KB) instead of the 2.01 MB aggregate.  Size was the
  // whole problem — Next's Data Cache refuses entries over 2 MB, so
  // ``revalidate: 60`` was silently inert on the aggregate and every
  // render re-fetched and re-parsed it.  A section entry caches, so the
  // revalidate window does what it says.
  { path: "/league", mustHave: /Chase Upside/i },
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

// Endpoints in the server's _PUBLIC_API_EXACT allowlist (server.py).
// /api/data, /api/terminal, /api/data/rank-history are NOT public —
// they're auth-gated since the rankings-contract scrape gate landed.
// The auth gate is verified separately by AUTH_GATED_API_ROUTES below.
const PUBLIC_API_ROUTES = [
  "/api/health",
  "/api/leagues",
  "/api/rankings/sources",
];

const AUTH_GATED_API_ROUTES = [
  "/api/user/state",
  "/api/trade/simulate",
  "/api/data",
  "/api/data/rank-history?days=30",
  "/api/terminal",
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
      // ``networkidle`` was previously the wait condition here, but
      // the app's background fetches (auto-scrape progress polling,
      // public-league cache warm, signal-alert sweep) keep the
      // network from going truly idle within 30s — false-fail.
      // ``domcontentloaded`` is enough for these checks: we're
      // confirming the route renders + the marker text appears, not
      // measuring TTI.
      const res = await page.goto(pageUrl(path), {
        waitUntil: "domcontentloaded",
        timeout: 30_000,
      });
      expect(res?.status(), `${path} should return 200`).toBeLessThan(400);
      await expect(page.locator("body")).toContainText(mustHave, { timeout: 15_000 });
      expect(errors, `${path} should not log JS errors`).toEqual([]);
    });
  }
});

test.describe("critical smoke — auth-gated routes redirect to /login", () => {
  for (const { path } of AUTH_GATED_ROUTES) {
    test(`GET ${path} (unauthenticated) redirects without crashing`, async ({ page }) => {
      // The SUBJECT of this block changed with #555, not just its origin.
      //
      // It used to assert the BACKEND's page gate: `_require_auth_or_redirect`
      // emitted a 302 to /login?next=… . That gate is deleted, and
      // frontend/middleware.js — which already was the only gate running in
      // production, since nginx never routed a page here — is now the only
      // one anywhere. So this asserts the gate that actually protects users
      // instead of a second definition of it that had to be kept in sync.
      // (Two definitions drifting is what caused the incident middleware.js
      // was written for: every private page served 200 to anonymous
      // visitors.)
      //
      // Visible difference: the redirect is Next's 307, not the old 302.
      // Both satisfy the assertions below, which check the landing URL
      // rather than the status.
      //
      // Note how this block would have failed if the goto had been left
      // bare: line below passes on a 404 (404 < 500), and the URL check
      // fails instead — because a 404 emits no Location, so page.url()
      // never leaves the requested path. Quiet, and misleading.
      const res = await page.goto(pageUrl(path), {
        waitUntil: "domcontentloaded",
        timeout: 30_000,
      });
      expect(res?.status(), `${path} should not 500`).toBeLessThan(500);
      // This assertion used to read:
      //
      //   expect(url.includes("/login") || body.length > 0)
      //
      // The right-hand side is true of ANY rendered HTML page, so the
      // disjunction was unfalsifiable: a test named "auth-gated routes
      // redirect to /login" could not detect the auth gate opening and
      // serving private pages to anonymous visitors.  It was the only
      // test claiming that coverage, which made it worse than no test —
      // it occupied the slot where real coverage would go.
      //
      // Assert the redirect itself.  Landing anywhere other than the
      // sign-in surface means the gate did not fire.
      const url = page.url();
      expect(url, `${path} must redirect an anonymous visitor to /login`).toContain(
        "/login",
      );
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

// ── What was here: two tests that reported PASSED while executing
// nothing at all ─────────────────────────────────────────────────────
//
// "GET /api/terminal returns publicMode payload when anonymous" and
// "rank-history endpoint clamps days to MAX_SNAPSHOTS" both opened by
// checking for 401 and, on a hit, returning early — one after pushing
// an annotation of `{type: "skip"}`, which is NOT `test.skip()` and does
// not skip anything. Playwright reported both as PASSED.
//
// Both endpoints are auth-gated and return 401 to an anonymous request
// (measured, not assumed). This is an ANONYMOUS spec. So every
// assertion in both bodies was unreachable, permanently, and the suite
// counted two more green tests for it. That is worse than no test: it
// occupies the slot where real coverage would go — the same finding as
// the `body.length > 0` disjunction above.
//
// They are not simply deleted; each half went where it can execute:
//
//   * the auth gate — already covered, and non-vacuously, by
//     AUTH_GATED_API_ROUTES above, which lists both `/api/terminal` and
//     `/api/data/rank-history?days=30` and asserts the 401.
//   * the terminal payload — covered by signed-in-smoke.spec.js
//     ("/api/terminal returns 200 (or 503 data_not_ready)"). The
//     anonymous `publicMode` payload it asserted stopped being live
//     behaviour when the endpoint moved out of `_PUBLIC_API_EXACT`;
//     there is no such contract left to test.
//   * the MAX_SNAPSHOTS clamp — had NO other home, so it moved to
//     signed-in-smoke.spec.js rather than being dropped with the rest.

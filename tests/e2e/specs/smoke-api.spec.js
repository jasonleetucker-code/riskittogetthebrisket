const { test, expect } = require("@playwright/test");
const {
  attachConsoleGuards,
  gotoApp,
  openTab,
  openMobilePrimary,
  isMobileProject,
} = require("../utils/app");

test.describe("startup + API sanity", () => {
  test("app boots, API contract fields exist, critical tabs render", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page);
    await gotoApp(page, request);

    const [statusResp, healthResp] = await Promise.all([
      request.get("/api/status"),
      request.get("/api/health"),
    ]);
    expect(statusResp.ok()).toBeTruthy();
    expect([200, 503]).toContain(healthResp.status());
    const status = await statusResp.json();
    const health = await healthResp.json();
    const runningFlag =
      Object.prototype.hasOwnProperty.call(status, "running")
        ? status.running
        : status.is_running;
    expect(typeof runningFlag).toBe("boolean");

    if (status.frontend_runtime && typeof status.frontend_runtime === "object") {
      expect(String(status.frontend_runtime.active || "").length).toBeGreaterThan(0);
      expect(status.frontend_runtime).toHaveProperty("raw_fallback_health");
      const rawFallbackHealth = status.frontend_runtime.raw_fallback_health;
      expect(rawFallbackHealth).toHaveProperty("status");
      expect(["ok", "warning", "missing"]).toContain(String(rawFallbackHealth.status || ""));
      expect(rawFallbackHealth).toHaveProperty("selected_source");
      expect(rawFallbackHealth).toHaveProperty("skipped_file_count");
      expect(Number(rawFallbackHealth.skipped_file_count || 0)).toBeGreaterThanOrEqual(0);
    } else {
      expect(status).toHaveProperty("has_data");
    }

    expect(health).toHaveProperty("frontend_raw_fallback");
    expect(["ok", "warning", "missing"]).toContain(String(health.frontend_raw_fallback?.status || ""));
    expect(Number(health.frontend_raw_fallback?.skipped_file_count || 0)).toBeGreaterThanOrEqual(0);
    if (Number(health.frontend_raw_fallback?.skipped_file_count || 0) > 0) {
      const warnings = Array.isArray(health.warnings) ? health.warnings : [];
      expect(warnings).toContain("frontend_raw_fallback_skipped_files");
    }

    if (status.contract && typeof status.contract === "object") {
      expect(status.contract).toHaveProperty("version");
      expect(status.contract).toHaveProperty("health");
    }

    const dataResp = await request.get("/api/data?view=app");
    expect(dataResp.ok()).toBeTruthy();
    const data = await dataResp.json();
    expect(data).toHaveProperty("players");
    expect(data).toHaveProperty("sites");
    expect(data).toHaveProperty("maxValues");
    if (Array.isArray(data.playersArray)) {
      expect(data).toHaveProperty("contractVersion");
    }

    const playerNames = Object.keys(data.players || {});
    expect(playerNames.length).toBeGreaterThan(100);

    if (Array.isArray(data.playersArray) && data.playersArray.length) {
      const firstRow = data.playersArray[0];
      expect(firstRow).toHaveProperty("canonicalName");
      expect(firstRow).toHaveProperty("position");
      expect(firstRow).toHaveProperty("values");
      expect(firstRow).toHaveProperty("valueBundle");
      expect(firstRow.valueBundle).toHaveProperty("rawValue");
      expect(firstRow.valueBundle).toHaveProperty("scoringAdjustedValue");
      expect(firstRow.valueBundle).toHaveProperty("scarcityAdjustedValue");
      expect(firstRow.valueBundle).toHaveProperty("bestBallAdjustedValue");
      expect(firstRow.valueBundle).toHaveProperty("fullValue");
      expect(firstRow.valueBundle).toHaveProperty("confidence");
      expect(firstRow.valueBundle).toHaveProperty("sourceCoverage");
      expect(firstRow.valueBundle).toHaveProperty("adjustmentTags");
      expect(firstRow.values).toHaveProperty("overall");
      expect(firstRow.values).toHaveProperty("rawComposite");
      expect(firstRow).toHaveProperty("canonicalSiteValues");
    }
    if (data.valueResolverDiagnostics && typeof data.valueResolverDiagnostics === "object") {
      expect(data.valueResolverDiagnostics).toHaveProperty("bestBallDiagnostics");
      const bb = data.valueResolverDiagnostics.bestBallDiagnostics;
      expect(bb).toHaveProperty("biggestBestBallOnlyRisers");
      expect(bb).toHaveProperty("biggestBestBallOnlyFallers");
      expect(bb).toHaveProperty("spikeWeekWinners");
      expect(bb).toHaveProperty("depthUtilityWinners");
      expect(bb).toHaveProperty("suspiciousExtremeBestBallMovers");
    }

    if (isMobileProject(testInfo)) {
      await openMobilePrimary(page, "calculator");
      await expect(page.locator("#tab-calculator")).toHaveClass(/active/);
      await openMobilePrimary(page, "rookies");
      await expect(page.locator("#tab-rookies")).toHaveClass(/active/);
      await openMobilePrimary(page, "more");
      await expect(page.locator("#tab-more")).toHaveClass(/active/);
    } else {
      await openTab(page, "calculator");
      await expect(page.locator("#tab-calculator")).toHaveClass(/active/);
      await openTab(page, "rookies");
      await expect(page.locator("#tab-rookies")).toHaveClass(/active/);
      await openTab(page, "trades");
      await expect(page.locator("#tab-trades")).toHaveClass(/active/);
      await openTab(page, "settings");
      await expect(page.locator("#tab-settings")).toHaveClass(/active/);
    }

    guard.assertClean();
  });

  test("landing League click and public League routes stay accessible without login", async ({ page, request }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.locator("#leagueOption")).toBeVisible();

    await Promise.all([
      page.waitForURL("**/league"),
      page.locator("#leagueOption").click(),
    ]);

    await expect(page).toHaveURL(/\/league$/);
    await expect(page.locator("body")).toContainText("Public League HQ");

    const routes = [
      "/league",
      "/league/standings",
      "/league/franchises",
      "/league/awards",
      "/league/draft",
      "/league/trades",
      "/league/records",
      "/league/money",
      "/league/constitution",
      "/league/history",
      "/league/league-media",
    ];

    for (const route of routes) {
      const resp = await request.get(route, { maxRedirects: 0 });
      expect(resp.status(), `${route} status`).toBe(200);
      const authority = String(resp.headers()["x-route-authority"] || "");
      expect(
        ["public-static-league-shell", "public-league-inline-fallback-shell"].includes(authority),
        `${route} route authority`,
      ).toBeTruthy();
      const finalPath = new URL(resp.url()).pathname;
      expect(finalPath, `${route} final path`).toBe(route);

      const html = await resp.text();
      expect(html, `${route} league shell marker`).toContain("Public League HQ");
      if (authority === "public-static-league-shell") {
        expect(html, `${route} league script marker`).toContain("/Static/league/league.js");
      } else {
        expect(html, `${route} fallback marker`).toContain("League shell fallback is active");
      }
      expect(html, `${route} should not auth redirect`).not.toContain("?jason=1");
      expect(html, `${route} should not serve login shell`).not.toContain('id="jasonLoginPanel"');
      expect(html, `${route} should not 500`).not.toContain("Internal Server Error");
    }
  });

  test("League public routes keep basic mobile/tablet layout stability", async ({ page }, testInfo) => {
    if (!String(testInfo.project.name || "").startsWith("mobile-") && !String(testInfo.project.name || "").startsWith("tablet-")) {
      test.skip();
    }

    for (const route of [
      "/league",
      "/league/standings",
      "/league/franchises",
      "/league/awards",
      "/league/draft",
      "/league/trades",
      "/league/records",
      "/league/money",
      "/league/constitution",
      "/league/history",
      "/league/league-media",
    ]) {
      await page.goto(route, { waitUntil: "domcontentloaded" });
      await expect(page.locator("body")).toContainText("Public League HQ");

      const layout = await page.evaluate(() => {
        const root = document.documentElement;
        const navLinks = document.querySelectorAll("nav a, #leagueNav a, .nav a").length;
        const overflowPx = Math.max(document.body.scrollWidth, root.scrollWidth) - root.clientWidth;
        const hasFatalMarker =
          document.body.textContent?.includes("Internal Server Error") ||
          document.body.textContent?.includes("Traceback");
        return {
          navLinks,
          overflowPx,
          hasFatalMarker: Boolean(hasFatalMarker),
        };
      });

      expect(layout.hasFatalMarker, `${route} should not hard-fail`).toBeFalsy();
      expect(layout.navLinks, `${route} should render League navigation`).toBeGreaterThan(4);
      expect(layout.overflowPx, `${route} should not have extreme horizontal overflow`).toBeLessThan(220);
    }
  });

  test("route authority map and headers are explicit for critical routes", async ({ request }) => {
    const runtimeResp = await request.get("/api/runtime/route-authority");
    expect(runtimeResp.ok()).toBeTruthy();
    const runtime = await runtimeResp.json();
    expect(runtime).toHaveProperty("configuredFrontendRuntime");
    expect(runtime).toHaveProperty("activeFrontendRuntime");
    expect(runtime).toHaveProperty("routes");
    expect(runtime.routes["/"].runtimeAuthority).toBe("public-static-landing-shell");
    expect(
      ["public-static-league-shell", "public-league-inline-fallback-shell"].includes(
        String(runtime.routes["/league"].runtimeAuthority || ""),
      ),
    ).toBeTruthy();
    expect(runtime.routes["/league"].nextProxyFallbackEnabled).toBeFalsy();
    expect(runtime.routes["/league"].fallbackEnabled).toBeTruthy();
    expect(runtime.routes["/league"].fallbackAuthority).toBe("public-league-inline-fallback-shell");
    const leagueSourcePages = Array.isArray(runtime?.artifacts?.frontendLeagueSourcePages)
      ? runtime.artifacts.frontendLeagueSourcePages
      : [];
    expect(
      leagueSourcePages.length,
      "frontend/app/league page.* files should be absent unless explicit runtime cutover is in progress",
    ).toBe(0);
    if (runtime?.artifacts?.frontendNextBuild?.exists) {
      const warnings = Array.isArray(runtime?.warnings) ? runtime.warnings : [];
      expect(
        warnings.some((w) => /non-authoritative/i.test(String(w || ""))),
        "when frontend/.next exists, route-authority warnings should mark it non-authoritative",
      ).toBeTruthy();
    }
    for (const route of [
      "/league/standings",
      "/league/franchises",
      "/league/awards",
      "/league/draft",
      "/league/trades",
      "/league/records",
      "/league/money",
      "/league/constitution",
      "/league/history",
      "/league/league-media",
    ]) {
      expect(runtime.routes).toHaveProperty(route);
      expect(runtime.routes[route].handler).toBe("serve_league_entry");
      expect(runtime.routes[route].sourceAuthority).toBe("/league/{league_path:path}");
    }
    expect(runtime).toHaveProperty("deployReadiness");
    expect(runtime.deployReadiness).toHaveProperty("leagueShell");
    expect(runtime.deployReadiness.leagueShell.runtimeFallbackEnabled).toBeTruthy();
    expect(runtime.routes["/app"].access).toBe("auth-gated");
    expect(runtime.routes["/rankings"].access).toBe("auth-gated");
    expect(runtime.routes["/trade"].access).toBe("auth-gated");
    expect(runtime.routes["/calculator"].access).toBe("auth-gated");
    expect(runtime.routes["/calculator"].handler).toBe("serve_calculator");
    expect(runtime.routes["/calculator"].runtimeAuthority).toBe("private-trade-compat-redirect");
    expect(runtime.routes["/calculator"].redirectTarget).toBe("/trade");

    const rootResp = await request.get("/", { maxRedirects: 0 });
    expect(rootResp.status()).toBe(200);
    expect(rootResp.headers()["x-route-authority"]).toBe("public-static-landing-shell");

    const leagueResp = await request.get("/league", { maxRedirects: 0 });
    expect(leagueResp.status()).toBe(200);
    expect(
      ["public-static-league-shell", "public-league-inline-fallback-shell"].includes(
        String(leagueResp.headers()["x-route-authority"] || ""),
      ),
    ).toBeTruthy();
    const standingsResp = await request.get("/league/standings", { maxRedirects: 0 });
    expect(standingsResp.status(), "/league/standings status").toBe(200);
    expect(
      ["public-static-league-shell", "public-league-inline-fallback-shell"].includes(
        String(standingsResp.headers()["x-route-authority"] || ""),
      ),
    ).toBeTruthy();

    const privateUnauthed = [
      ["/app", "/?next=/app&jason=1"],
      ["/rankings", "/?next=/rankings&jason=1"],
      ["/trade", "/?next=/trade&jason=1"],
      ["/calculator", "/?next=/calculator&jason=1"],
    ];
    for (const [route, expectedLocation] of privateUnauthed) {
      const resp = await request.get(route, { maxRedirects: 0 });
      expect(resp.status(), `${route} unauth status`).toBe(302);
      expect(resp.headers()["x-route-authority"], `${route} unauth authority`).toBe("auth-gate-redirect");
      expect(resp.headers()["location"], `${route} unauth redirect`).toBe(expectedLocation);
    }

    const username = process.env.E2E_JASON_USERNAME || "jasonleetucker";
    const password = process.env.E2E_JASON_PASSWORD || "e2e-local-password";
    const loginResp = await request.post("/api/auth/login", {
      data: { username, password, next: "/app" },
    });
    expect(loginResp.ok()).toBeTruthy();

    for (const route of ["/app", "/rankings", "/trade"]) {
      const resp = await request.get(route, { maxRedirects: 0 });
      expect(resp.status(), `${route} authed status`).toBe(200);
      const authority = String(resp.headers()["x-route-authority"] || "");
      expect(
        ["private-static-dashboard-shell", "private-next-proxy-shell"].includes(authority),
        `${route} authed authority`
      ).toBeTruthy();
    }

    const calculatorResp = await request.get("/calculator", { maxRedirects: 0 });
    expect(calculatorResp.status(), "/calculator authed status").toBe(302);
    expect(calculatorResp.headers()["x-route-authority"]).toBe("private-trade-compat-redirect");
    expect(calculatorResp.headers()["location"]).toBe("/trade");
  });

  test("Yahoo coverage is explicit in source health and final payload", async ({ request }) => {
    const [statusResp, dataResp] = await Promise.all([
      request.get("/api/status"),
      request.get("/api/data?view=app"),
    ]);
    expect(statusResp.ok()).toBeTruthy();
    expect(dataResp.ok()).toBeTruthy();

    const status = await statusResp.json();
    const data = await dataResp.json();

    const sourceHealth = status.source_health && typeof status.source_health === "object"
      ? status.source_health
      : {};
    const sourceCounts = sourceHealth.source_counts && typeof sourceHealth.source_counts === "object"
      ? sourceHealth.source_counts
      : {};
    const sourceRuntime = sourceHealth.source_runtime && typeof sourceHealth.source_runtime === "object"
      ? sourceHealth.source_runtime
      : {};
    const sourceFailures = Array.isArray(sourceHealth.source_failures)
      ? sourceHealth.source_failures
      : [];

    const yahooSourceCount = Number(sourceCounts.yahoo || 0);
    const rows = Array.isArray(data.playersArray)
      ? data.playersArray
      : Object.values(data.players || {});

    const yahooRows = rows.filter((row) => {
      if (!row || typeof row !== "object") return false;
      const canonical = row.canonicalSiteValues && typeof row.canonicalSiteValues === "object"
        ? row.canonicalSiteValues
        : row._canonicalSiteValues && typeof row._canonicalSiteValues === "object"
        ? row._canonicalSiteValues
        : {};
      const yahooVal = Number(canonical.yahoo ?? row.yahoo ?? 0);
      return Number.isFinite(yahooVal) && yahooVal > 0;
    });

    const yahooRowsWithAdjustedValues = yahooRows.filter((row) => {
      if (!row || typeof row !== "object") return false;
      const bundle = row.valueBundle && typeof row.valueBundle === "object" ? row.valueBundle : {};
      const adjusted = Number(
        bundle.fullValue ??
          row.fullValue ??
          row._finalAdjusted ??
          row._leagueAdjusted ??
          row._composite ??
          0,
      );
      return Number.isFinite(adjusted) && adjusted > 0;
    });

    const yahooFailure = sourceFailures.find((entry) => {
      if (!entry || typeof entry !== "object") return false;
      const src = String(entry.source || "").toLowerCase();
      return src === "yahoo";
    });

    if (yahooSourceCount > 0) {
      expect(yahooRows.length, "Yahoo has source rows but no final player rows").toBeGreaterThan(0);
      expect(yahooRowsWithAdjustedValues.length, "Yahoo rows missing adjusted/final values").toBeGreaterThan(0);
      expect(yahooFailure, "Yahoo should not report failed/partial when source rows exist").toBeFalsy();
      return;
    }

    const partial = new Set(
      Array.isArray(sourceRuntime.partial_sources) ? sourceRuntime.partial_sources : [],
    );
    const timedOut = new Set(
      Array.isArray(sourceRuntime.timed_out_sources) ? sourceRuntime.timed_out_sources : [],
    );
    const failed = new Set(
      Array.isArray(sourceRuntime.failed_sources) ? sourceRuntime.failed_sources : [],
    );
    const explicitYahooFailure =
      partial.has("Yahoo") ||
      timedOut.has("Yahoo") ||
      failed.has("Yahoo") ||
      Boolean(yahooFailure);

    expect(
      explicitYahooFailure,
      "Yahoo disappeared without explicit source failure/partial signal",
    ).toBeTruthy();
  });

  test("DynastyNerds value schema is explicit and wired through final payload", async ({ request }) => {
    const [statusResp, dataResp] = await Promise.all([
      request.get("/api/status"),
      request.get("/api/data?view=app"),
    ]);
    expect(statusResp.ok()).toBeTruthy();
    expect(dataResp.ok()).toBeTruthy();

    const status = await statusResp.json();
    const data = await dataResp.json();

    const sourceHealth = status.source_health && typeof status.source_health === "object"
      ? status.source_health
      : {};
    const sourceCounts = sourceHealth.source_counts && typeof sourceHealth.source_counts === "object"
      ? sourceHealth.source_counts
      : {};
    const sourceRuntime = sourceHealth.source_runtime && typeof sourceHealth.source_runtime === "object"
      ? sourceHealth.source_runtime
      : {};
    const sourceFailures = Array.isArray(sourceHealth.source_failures)
      ? sourceHealth.source_failures
      : [];

    const settings = data.settings && typeof data.settings === "object"
      ? data.settings
      : {};
    const sourceModes = settings.sourceModes && typeof settings.sourceModes === "object"
      ? settings.sourceModes
      : {};
    const schemaDiagnostics = settings.sourceSchemaDiagnostics && typeof settings.sourceSchemaDiagnostics === "object"
      ? settings.sourceSchemaDiagnostics
      : {};

    const dynastyNerdsSourceCount = Number(sourceCounts.dynastyNerds || 0);
    const dynastyNerdsMode = String(sourceModes.DynastyNerds || "").toLowerCase();
    const rows = Array.isArray(data.playersArray)
      ? data.playersArray
      : Object.values(data.players || {});

    const dynastyNerdsRows = rows.filter((row) => {
      if (!row || typeof row !== "object") return false;
      const canonical = row.canonicalSiteValues && typeof row.canonicalSiteValues === "object"
        ? row.canonicalSiteValues
        : row._canonicalSiteValues && typeof row._canonicalSiteValues === "object"
        ? row._canonicalSiteValues
        : {};
      const val = Number(canonical.dynastyNerds ?? row.dynastyNerds ?? 0);
      return Number.isFinite(val) && val > 0;
    });
    const dynastyNerdsValueLikeRows = dynastyNerdsRows.filter((row) => {
      const canonical = row.canonicalSiteValues && typeof row.canonicalSiteValues === "object"
        ? row.canonicalSiteValues
        : row._canonicalSiteValues && typeof row._canonicalSiteValues === "object"
        ? row._canonicalSiteValues
        : {};
      const val = Number(canonical.dynastyNerds ?? row.dynastyNerds ?? 0);
      return Number.isFinite(val) && val >= 1000;
    });
    const dynastyNerdsRowsWithAdjustedValues = dynastyNerdsRows.filter((row) => {
      if (!row || typeof row !== "object") return false;
      const bundle = row.valueBundle && typeof row.valueBundle === "object" ? row.valueBundle : {};
      const adjusted = Number(
        bundle.fullValue ??
          row.fullValue ??
          row._finalAdjusted ??
          row._leagueAdjusted ??
          row._composite ??
          0,
      );
      return Number.isFinite(adjusted) && adjusted > 0;
    });
    const dynastyNerdsSite = Array.isArray(data.sites)
      ? data.sites.find((site) => String(site?.key || "").toLowerCase() === "dynastynerds")
      : null;
    const dynastyNerdsSiteMax = Number(dynastyNerdsSite?.max || 0);

    const dynastyNerdsFailure = sourceFailures.find((entry) => {
      if (!entry || typeof entry !== "object") return false;
      return String(entry.source || "").toLowerCase() === "dynastynerds";
    });

    if (dynastyNerdsSourceCount > 0) {
      expect(dynastyNerdsMode, "DynastyNerds must run in value mode when source rows exist").toBe("value");
      expect(dynastyNerdsRows.length, "DynastyNerds has source rows but no final player rows").toBeGreaterThan(0);
      expect(dynastyNerdsRowsWithAdjustedValues.length, "DynastyNerds rows missing adjusted/final values").toBeGreaterThan(0);
      expect(dynastyNerdsValueLikeRows.length, "DynastyNerds rows look rank-like (no value-scale rows >= 1000)").toBeGreaterThan(0);
      expect(dynastyNerdsSiteMax, "DynastyNerds site max should be value-scale").toBeGreaterThan(900);
      if (schemaDiagnostics.DynastyNerds && typeof schemaDiagnostics.DynastyNerds === "object") {
        expect(String(schemaDiagnostics.DynastyNerds.expectedMode || "").toLowerCase()).toBe("value");
        expect(Boolean(schemaDiagnostics.DynastyNerds.schemaDrift)).toBeFalsy();
      }
      expect(dynastyNerdsFailure, "DynastyNerds should not report failed/partial when value-mode rows exist").toBeFalsy();
      return;
    }

    const partial = new Set(
      Array.isArray(sourceRuntime.partial_sources) ? sourceRuntime.partial_sources : [],
    );
    const timedOut = new Set(
      Array.isArray(sourceRuntime.timed_out_sources) ? sourceRuntime.timed_out_sources : [],
    );
    const failed = new Set(
      Array.isArray(sourceRuntime.failed_sources) ? sourceRuntime.failed_sources : [],
    );
    const explicitDynastyNerdsFailure =
      partial.has("DynastyNerds") ||
      timedOut.has("DynastyNerds") ||
      failed.has("DynastyNerds") ||
      Boolean(dynastyNerdsFailure);

    expect(
      explicitDynastyNerdsFailure,
      "DynastyNerds disappeared without explicit source failure/partial signal",
    ).toBeTruthy();
  });

  test("IDPTradeCalc coverage is explicit across offensive and IDP players", async ({ request }) => {
    const [statusResp, dataResp] = await Promise.all([
      request.get("/api/status"),
      request.get("/api/data?view=app"),
    ]);
    expect(statusResp.ok()).toBeTruthy();
    expect(dataResp.ok()).toBeTruthy();

    const status = await statusResp.json();
    const data = await dataResp.json();

    const sourceHealth = status.source_health && typeof status.source_health === "object"
      ? status.source_health
      : {};
    const sourceCounts = sourceHealth.source_counts && typeof sourceHealth.source_counts === "object"
      ? sourceHealth.source_counts
      : {};
    const sourceRuntime = sourceHealth.source_runtime && typeof sourceHealth.source_runtime === "object"
      ? sourceHealth.source_runtime
      : {};
    const sourceFailures = Array.isArray(sourceHealth.source_failures)
      ? sourceHealth.source_failures
      : [];

    const idpTradeCalcSourceCount = Number(sourceCounts.idpTradeCalc || 0);
    const posMap = data?.sleeper?.positions && typeof data.sleeper.positions === "object"
      ? data.sleeper.positions
      : {};
    const rowEntries = Array.isArray(data.playersArray)
      ? data.playersArray.map((row) => {
        const fallbackName = String(row?.canonicalName || row?.name || "").trim();
        return {
          name: fallbackName,
          row,
        };
      })
      : Object.entries(data.players || {}).map(([name, row]) => ({ name, row }));

    const normalizePosBucket = (rawPos) => {
      const pos = String(rawPos || "").toUpperCase().trim();
      if (["DE", "DT", "EDGE"].includes(pos)) return "DL";
      if (["CB", "S"].includes(pos)) return "DB";
      if (["QB", "RB", "WR", "TE", "DL", "LB", "DB"].includes(pos)) return pos;
      return "";
    };

    const idpRows = rowEntries.filter(({ row }) => {
      if (!row || typeof row !== "object") return false;
      const canonical = row.canonicalSiteValues && typeof row.canonicalSiteValues === "object"
        ? row.canonicalSiteValues
        : row._canonicalSiteValues && typeof row._canonicalSiteValues === "object"
        ? row._canonicalSiteValues
        : {};
      const val = Number(canonical.idpTradeCalc ?? row.idpTradeCalc ?? 0);
      return Number.isFinite(val) && val > 0;
    });

    const idpRowsWithAdjustedValues = idpRows.filter(({ row }) => {
      if (!row || typeof row !== "object") return false;
      const bundle = row.valueBundle && typeof row.valueBundle === "object" ? row.valueBundle : {};
      const adjusted = Number(
        bundle.fullValue ??
          row.fullValue ??
          row._finalAdjusted ??
          row._leagueAdjusted ??
          row._composite ??
          0,
      );
      return Number.isFinite(adjusted) && adjusted > 0;
    });

    const coverage = {
      offense: 0,
      idp: 0,
      byPos: { QB: 0, RB: 0, WR: 0, TE: 0, DL: 0, LB: 0, DB: 0 },
    };
    for (const { name, row } of idpRows) {
      const rowPos = String(row?.position || row?.pos || row?.playerPosition || "").toUpperCase();
      const pos = normalizePosBucket(rowPos || posMap[name] || "");
      if (!pos) continue;
      coverage.byPos[pos] += 1;
      if (["QB", "RB", "WR", "TE"].includes(pos)) coverage.offense += 1;
      if (["DL", "LB", "DB"].includes(pos)) coverage.idp += 1;
    }

    const idpTradeCalcFailure = sourceFailures.find((entry) => {
      if (!entry || typeof entry !== "object") return false;
      return String(entry.source || "").toLowerCase() === "idptradecalc";
    });

    if (idpTradeCalcSourceCount > 0) {
      expect(idpRows.length, "IDPTradeCalc has source rows but no final player rows").toBeGreaterThan(0);
      expect(idpRowsWithAdjustedValues.length, "IDPTradeCalc rows missing adjusted/final values").toBeGreaterThan(0);
      expect(coverage.offense, "IDPTradeCalc offensive coverage missing from final payload").toBeGreaterThan(0);
      expect(coverage.idp, "IDPTradeCalc IDP coverage missing from final payload").toBeGreaterThan(0);
      for (const key of ["QB", "RB", "WR", "TE", "DL", "LB", "DB"]) {
        expect(coverage.byPos[key], `IDPTradeCalc ${key} coverage missing`).toBeGreaterThan(0);
      }
      expect(idpTradeCalcFailure, "IDPTradeCalc should not report failed/partial when source rows exist").toBeFalsy();
      return;
    }

    const partial = new Set(
      Array.isArray(sourceRuntime.partial_sources) ? sourceRuntime.partial_sources : [],
    );
    const timedOut = new Set(
      Array.isArray(sourceRuntime.timed_out_sources) ? sourceRuntime.timed_out_sources : [],
    );
    const failed = new Set(
      Array.isArray(sourceRuntime.failed_sources) ? sourceRuntime.failed_sources : [],
    );
    const explicitIdpTradeCalcFailure =
      partial.has("IDPTradeCalc") ||
      timedOut.has("IDPTradeCalc") ||
      failed.has("IDPTradeCalc") ||
      Boolean(idpTradeCalcFailure);

    expect(
      explicitIdpTradeCalcFailure,
      "IDPTradeCalc disappeared without explicit source failure/partial signal",
    ).toBeTruthy();
  });
});

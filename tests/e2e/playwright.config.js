const fs = require("node:fs");
const path = require("node:path");
const { defineConfig, devices } = require("@playwright/test");

const isWin = process.platform === "win32";

// ── Chromium resolution ────────────────────────────────────────────────
// Preference order:
//   1. E2E_CHROMIUM_PATH — explicit override, always wins.
//   2. A pre-installed build under PLAYWRIGHT_BROWSERS_PATH whose
//      revision doesn't match this @playwright/test version.  Sandboxed
//      agent containers ship e.g. /opt/pw-browsers/chromium-1194 while
//      the pinned revision is newer; Playwright would refuse to launch
//      and tell you to run `playwright install`, which those containers
//      can't do.  Auto-detecting the newest present build makes the
//      suite runnable with no manual step.
//   3. Playwright's own managed download (normal dev + CI).
function resolveChromiumPath() {
  if (process.env.E2E_CHROMIUM_PATH) return process.env.E2E_CHROMIUM_PATH;
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH;
  if (!root || root === "0" || !fs.existsSync(root)) return undefined;
  let candidates;
  try {
    candidates = fs
      .readdirSync(root)
      .filter((name) => /^chromium-\d+$/.test(name))
      .map((name) => ({
        rev: Number(name.split("-")[1]),
        bin: path.join(root, name, "chrome-linux", "chrome"),
      }))
      .filter((c) => fs.existsSync(c.bin))
      .sort((a, b) => b.rev - a.rev);
  } catch {
    return undefined;
  }
  if (!candidates.length) return undefined;
  // Only step in when the version Playwright wants isn't already there;
  // otherwise let Playwright use its own managed binary.
  try {
    const { chromium } = require("@playwright/test");
    if (fs.existsSync(chromium.executablePath())) return undefined;
  } catch {
    /* executablePath() throws when the browser isn't installed — that
       is exactly the case we're covering, so fall through. */
  }
  return candidates[0].bin;
}

const chromiumExecutablePath = resolveChromiumPath();

// ── Self-booted backend environment ────────────────────────────────────
// Only applies when this config boots the stack itself (no
// E2E_BASE_URL).  Without these the backend either refuses to start or
// serves a shape the suite can't test against — the difference between
// "one command works" and "every agent re-derives the setup":
//
//   ALLOW_DEFAULT_LOGIN_DEV — server.py raises at import without
//     JASON_LOGIN_PASSWORD.  This is a hard boot failure, and its
//     downstream symptoms (health 503, /api/data 401) read like "no
//     data" rather than "the backend never started".
//   E2E_TEST_MODE + E2E_TEST_SECRET — unlock /api/test/create-session.
//     Without them every signed-in spec skips and the run looks green
//     while testing nothing.
//   E2E_TEST_USERNAME — the throwaway identity test sessions assume.
//     The endpoint fails closed without it (it used to default to the
//     operator's real, admin-allowlisted username).
//   RATE_LIMIT_BYPASS_IPS — the public-API limiter (60/min, 1000/hour
//     per IP) drains mid-run; the 429s surface as bogus auth/render
//     failures.
//   PLAYWRIGHT_BROWSERS_PATH — pointed at an empty dir so the startup
//     scrape fails fast at browser launch.  The suite must test the
//     committed snapshot, deterministically, and never reach out to
//     live ranking sites.
const selfBooted = !process.env.E2E_BASE_URL;

// Deterministic across the runner and every worker process (each
// worker re-requires this config, so a random value would differ per
// worker and the fixture's secret wouldn't match the server's).  Only
// defaulted when we boot the server ourselves — against an external
// stack an absent secret must keep meaning "skip signed-in specs".
if (selfBooted && !process.env.E2E_TEST_SECRET) {
  process.env.E2E_TEST_SECRET = "e2e-local-insecure-secret";
}

const noScrapeBrowsersDir = path.join(__dirname, ".no-browsers");
if (selfBooted) {
  try {
    fs.mkdirSync(noScrapeBrowsersDir, { recursive: true });
  } catch {
    /* best effort — the scrape failing to launch is the goal either way */
  }
}

const backendEnv = {
  UPTIME_CHECK_ENABLED: "false",
  ALLOW_DEFAULT_LOGIN_DEV: "1",
  E2E_TEST_MODE: "1",
  E2E_TEST_SECRET: process.env.E2E_TEST_SECRET || "",
  E2E_TEST_USERNAME: process.env.E2E_TEST_USERNAME || "e2e-test-user",
  RATE_LIMIT_BYPASS_IPS: "127.0.0.1",
  PLAYWRIGHT_BROWSERS_PATH: noScrapeBrowsersDir,
};

module.exports = defineConfig({
  testDir: "./specs",
  // Verifies the stack can actually serve the suite (snapshot loaded,
  // test sessions unlocked, authenticated /api/data populated) and
  // fails with a fix-it message instead of letting specs time out or
  // silently skip.  See global-setup.js for why the obvious signals
  // (/api/health 503, /api/data 401) are misleading here.
  globalSetup: require.resolve("./global-setup.js"),
  timeout: 90_000,
  expect: {
    timeout: 15_000,
  },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // Retries stay at 1 so `trace: "on-first-retry"` below still captures a
  // failing attempt — that trace is what makes a flake debuggable at all.
  // What changes here is what a retried pass MEANS.
  //
  // Playwright's run status for "failed attempt 0, passed attempt 1" is
  // `passed`, exit 0: the test is filed as FLAKY and the run is green.
  // Measured 2026-08-05 by grepping every workflow and all of tests/e2e/:
  // NOTHING read that flaky count.  So `e2e.yml`'s close step — gated on
  // `success() && github.ref == 'refs/heads/main'` — would CLOSE the
  // `e2e-failures` tracker on a run that watched a critical journey fail
  // and then pass, and it iterates `.[]`, so it drains every open one.
  // Its stated premise is "a green run of THIS workflow is the all-clear
  // by construction".  A silent retry in front of it broke that premise.
  //
  // #718 scoped that close step to mainline runs — it fixed WHO may speak
  // for main.  This is the half it explicitly left open: HOW MUCH one
  // green run proves.
  //
  // There IS a live intermittent failure for a retry to launder: React
  // 19.2 defers its Suspense reveal, so a staged copy of a boundary sits
  // in `<div hidden id="S:n">` until `$RV` runs, and any non-`.first()`
  // locator inside it throws a strict-mode violation.  The suite's only
  // two windows onto that shape are journey-trade.spec.js (/arbitrage)
  // and waivers-smoke.spec.js (/waivers) — one retry hides both.
  //
  // Those specs now call `awaitStreamSettled()`, so the TRANSIENT case
  // no longer reaches an assertion.  This key still matters: what remains
  // behind a retry is a PERMANENT duplicate, which is a genuine defect,
  // and every other flake the suite has yet to meet.  (An earlier version
  // of this comment called the transient case a product defect; it is
  // React's documented behaviour — see helpers/journey.js.)
  //
  // THIS LIVES IN THE CONFIG, NOT IN stack-death-reporter.js, AND THAT
  // PLACEMENT IS THE WHOLE POINT.  A `--reporter=…` on the command line
  // REPLACES the reporter array below and unloads every guard in that
  // file — see its header, and what prod-e2e-smoke.yml did for its entire
  // history.  A CLI flag cannot unload a config key, and
  // `--fail-on-flaky-tests` can only set it TRUE: program.js emits
  // `true` or `undefined`, never `false`, and common/config.js resolves
  // `takeFirst(cliOverride, userConfig, false)`.  Putting the predicate
  // in the reporter would have rebuilt the exact defect this PR removes.
  //
  // The predicate is Playwright's own `TestCase.outcome() === "flaky"`
  // (runner/failureTracker.js), evaluated BEFORE onEnd — the same word
  // the HTML report prints.  stack-death-reporter.js adds a banner
  // explaining the red; it deliberately returns no status.
  //
  // E2E_ALLOW_FLAKY=1 is the hatch for a human chasing something else
  // locally.  tests/e2e/test_e2e_harness_guards.py fails the PR if a
  // workflow sets it, or if `retries` keeps a non-zero CI branch while
  // this key goes missing.
  failOnFlakyTests: !!process.env.CI && !process.env.E2E_ALLOW_FLAKY,
  workers: process.env.CI ? 1 : undefined,
  outputDir: "test-results",
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report" }],
    // Aborts the run if the stack dies partway through, so a dead
    // frontend reports as "the stack died" instead of manufacturing a
    // dozen connection-refused failures that read as a mass product
    // regression.  See stack-death-reporter.js.
    [require.resolve("./stack-death-reporter.js")],
  ],
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:8000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    ...(chromiumExecutablePath
      ? { launchOptions: { executablePath: chromiumExecutablePath } }
      : {}),
  },
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : [
        {
          cwd: "../..",
          // Env comes from `backendEnv` above — do NOT inline vars in
          // the command string; Windows and POSIX disagree on the
          // syntax and the list is long enough that drift is certain.
          command: isWin ? "python server.py" : "python server.py",
          env: backendEnv,
          // /api/status (not /api/health) — health intentionally
          // answers 503 while "degraded", which is the steady state
          // in offline/CI environments where the startup scrape
          // can't run.  /api/status always answers 200 once the app
          // is up, and the cached contract is primed during the
          // lifespan hook BEFORE the port binds, so "status answers"
          // ⇒ "data is served".
          url: "http://127.0.0.1:8000/api/status",
          timeout: 240_000,
          reuseExistingServer: true,
        },
        {
          // Next.js frontend — and since #555 the ONLY thing serving a
          // page, so this server is not optional for page specs.  (The
          // old note here justified the production build by the backend
          // proxy's 5s timeout, which a dev-mode first-compile would
          // exceed and 503 through.  That proxy is deleted.)  The
          // production build stays, for the reason underneath: a
          // dev-mode first-compile is slow and variable, and page specs
          // measured against it flake on their own content budgets
          // rather than on anything real.  Override with
          // E2E_FRONTEND_CMD (e.g. "npm run start" in CI after an
          // explicit build step, or point at an already-running dev
          // server — reuseExistingServer skips this entirely when
          // :3000 already answers).
          cwd: "../../frontend",
          command:
            process.env.E2E_FRONTEND_CMD ||
            "npm run build:nocheck && npm run start",
          url: "http://127.0.0.1:3000",
          timeout: 600_000,
          reuseExistingServer: true,
        },
      ],
  projects: [
    {
      name: "desktop-1366",
      use: {
        browserName: "chromium",
        viewport: { width: 1366, height: 768 },
      },
    },
    {
      // Chromium-based mobile viewport — equivalent layout coverage to
      // mobile-390 / mobile-430 below, but without requiring webkit.
      // Used for the public /league page suite which doesn't depend on
      // Safari-specific behavior.
      name: "mobile-chromium",
      use: {
        browserName: "chromium",
        viewport: { width: 390, height: 844 },
        hasTouch: true,
        isMobile: true,
      },
    },
    {
      name: "mobile-390",
      use: {
        ...devices["iPhone 13"],
        viewport: { width: 390, height: 844 },
      },
    },
    {
      name: "mobile-430",
      use: {
        ...devices["iPhone 14 Pro Max"],
        viewport: { width: 430, height: 932 },
      },
    },
  ],
});

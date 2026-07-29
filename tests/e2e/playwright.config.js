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
          // Next.js frontend.  server.py proxies all page routes to
          // :3000 with a 5s timeout (see server.py::_proxy_next), so a
          // dev-mode first-compile (often >5s) would 503 through the
          // proxy and flake page tests.  Default to a production
          // build + start for deterministic timings; override with
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

const { defineConfig, devices } = require("@playwright/test");

const isWin = process.platform === "win32";

// Escape hatch for environments with a pre-installed Chromium whose
// revision doesn't match this @playwright/test version (sandboxes,
// air-gapped runners).  Point E2E_CHROMIUM_PATH at a chrome binary
// (e.g. /opt/pw-browsers/chromium-1194/chrome-linux/chrome) to launch
// it directly instead of the revision-pinned download.  Unset by
// default — normal local runs and CI use `playwright install chromium`.
const chromiumExecutablePath = process.env.E2E_CHROMIUM_PATH || undefined;

module.exports = defineConfig({
  testDir: "./specs",
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
          command: isWin
            ? "set UPTIME_CHECK_ENABLED=false&& python server.py"
            : "UPTIME_CHECK_ENABLED=false python server.py",
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

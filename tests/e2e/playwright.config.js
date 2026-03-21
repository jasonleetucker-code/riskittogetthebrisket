const { defineConfig, devices } = require("@playwright/test");
const path = require("path");

const isWin = process.platform === "win32";
const e2eJasonPassword = process.env.E2E_JASON_PASSWORD || "e2e-local-password";
const repoRoot = path.resolve(__dirname, "..", "..");
const playwrightArtifactsDir = path.join(repoRoot, "tmp", "playwright");

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
  outputDir: path.join(playwrightArtifactsDir, "test-results"),
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: path.join(playwrightArtifactsDir, "playwright-report") }],
  ],
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:8000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        cwd: "../..",
        command: isWin
          ? "set PYTHONUTF8=1&& set PYTHONIOENCODING=utf-8&& set FRONTEND_RUNTIME=static&& set SCRAPE_STARTUP_ENABLED=false&& set SCRAPE_SCHEDULER_ENABLED=false&& set UPTIME_CHECK_ENABLED=false&& python server.py"
          : "FRONTEND_RUNTIME=static SCRAPE_STARTUP_ENABLED=false SCRAPE_SCHEDULER_ENABLED=false UPTIME_CHECK_ENABLED=false python server.py",
        env: {
          ...process.env,
          JASON_LOGIN_PASSWORD: e2eJasonPassword,
        },
        url: "http://127.0.0.1:8000/api/health",
        timeout: 240_000,
        reuseExistingServer: true,
      },
  projects: [
    {
      name: "desktop-1366",
      use: {
        browserName: "chromium",
        viewport: { width: 1366, height: 768 },
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
    {
      name: "tablet-820",
      use: {
        ...devices["iPad (gen 7)"],
        viewport: { width: 820, height: 1180 },
      },
    },
  ],
});

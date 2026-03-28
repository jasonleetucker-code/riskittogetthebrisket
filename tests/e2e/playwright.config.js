const { defineConfig, devices } = require("@playwright/test");

const isWin = process.platform === "win32";

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
  },
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        cwd: "../..",
        command: isWin
          ? "set FRONTEND_RUNTIME=next&& set UPTIME_CHECK_ENABLED=false&& python server.py"
          : "FRONTEND_RUNTIME=next UPTIME_CHECK_ENABLED=false python server.py",
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
  ],
});

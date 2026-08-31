const fs = require("node:fs");
const path = require("node:path");
const { defineConfig } = require("@playwright/test");

/**
 * Playwright config for the PRODUCTION-AUTH verification specs
 * (tests/e2e/specs/prod-auth/).
 *
 * A deliberately separate config from playwright.config.js, for three
 * reasons:
 *
 *   1. **No stack.** These specs run against the deployed production
 *      site — no webServer, no global-setup contract priming, no
 *      test-session minting. Booting the local stack for them would be
 *      wrong twice over (it is not the thing being verified, and the
 *      sandbox has no production credentials).
 *   2. **No collection overlap.** The default config's testDir is
 *      ./specs, which contains this directory; playwright.config.js
 *      carries a matching `testIgnore` so the default suite's size is
 *      unchanged. This config is the ONLY way these specs are collected.
 *   3. **No retries.** A production verification run must not launder a
 *      flake into a pass — a spec that fails once against prod is a
 *      finding to read, not to retry away.
 *
 * Runs only from the production-verification CI workflow, which supplies:
 *   PROD_ORIGIN               e.g. https://chaseupside.com
 *   PROD_SESSION_COOKIE_FILE  file containing ONLY the jason_session
 *                             cookie VALUE
 * Without both, every spec skips with an explicit message (see
 * specs/prod-auth/helpers.js) — so an accidental local run is loudly
 * inert, never red and never green-by-vacuity (the skip count says so).
 */

// Same pre-installed-Chromium fallback as playwright.config.js — needed
// so `--list` (and dry runs) work in sandboxed agent containers whose
// browser revision doesn't match this @playwright/test version. Kept as
// a copy rather than require()-ing the default config, whose import has
// side effects (env defaulting, directory creation) that belong to the
// self-booted stack only.
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
  try {
    const { chromium } = require("@playwright/test");
    if (fs.existsSync(chromium.executablePath())) return undefined;
  } catch {
    /* not installed — fall through to the detected build */
  }
  return candidates[0].bin;
}

const chromiumExecutablePath = resolveChromiumPath();

module.exports = defineConfig({
  testDir: "./specs/prod-auth",
  // Production pages carry real data over a real network; budgets are
  // sized for that, not for the local snapshot.
  timeout: 180_000,
  expect: {
    timeout: 20_000,
  },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  // No retries, ever — see the header. failOnFlakyTests is kept anyway
  // so a future retries edit cannot silently reintroduce laundering.
  retries: 0,
  failOnFlakyTests: true,
  workers: 1,
  // Separate output dirs so a prod-auth run never clobbers (or uploads
  // as) the default suite's artifacts.
  outputDir: "test-results-prod-auth",
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report-prod-auth" }],
    // The JSON report is the EVIDENCE artifact, not a convenience.
    //
    // Specs record which branch of a multi-state render actually ran by
    // pushing onto `testInfo.annotations` (helpers.js::annotate) — e.g.
    // V1-45's `states-observed: finalRosterSimulation: populated`. Those
    // annotations exist only in a structured report: the `list` reporter
    // prints pass/fail lines and drops them, and the `html` folder is not
    // uploaded. Without this, a green tick proves the spec passed but not
    // WHICH state production produced — and V1-45's L4 bar is a statement
    // about the observed state, so the run could not answer its own
    // question. Inferring the branch from a pass would be exactly the
    // "infer rather than read" error this lane exists to prevent.
    //
    // Absolute path via `__dirname`: Playwright resolves a reporter's
    // relative `outputFile` against the cwd, which is the repo root here
    // and NOT where `outputDir` above lands (that one is config-relative).
    // Pinning it removes the discrepancy rather than depending on it.
    ["json", { outputFile: path.join(__dirname, "prod-auth-results.json") }],
  ],
  use: {
    // Deliberately NO baseURL: every navigation and API call builds its
    // absolute URL through helpers.js::prodUrl(PROD_ORIGIN), so a spec
    // cannot accidentally hit a relative (and therefore nonexistent)
    // origin.
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    ...(chromiumExecutablePath
      ? { launchOptions: { executablePath: chromiumExecutablePath } }
      : {}),
  },
  projects: [
    {
      name: "prod-desktop",
      use: {
        browserName: "chromium",
        viewport: { width: 1366, height: 768 },
      },
    },
    {
      name: "prod-mobile",
      use: {
        browserName: "chromium",
        viewport: { width: 390, height: 844 },
        hasTouch: true,
        isMobile: true,
      },
    },
  ],
});

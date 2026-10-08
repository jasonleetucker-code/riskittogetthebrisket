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
  // ONE reporter, and it is the sanitized one (security S3). This repo,
  // its Actions logs and its artifacts are PUBLIC, and these specs run
  // against PRODUCTION with a real session cookie. `list`/`dot` print full
  // assertion output (Received values = private data) into the public log,
  // `json` records it with stdout/stderr, and `html` embeds traces — a
  // failed run's trace carried the session cookie 154x (run 37690745794).
  //
  // prod-auth-safe-reporter.js writes tests/e2e/prod-auth-results.json —
  // still the EVIDENCE artifact: specs record which branch of a multi-state
  // render ran via `testInfo.annotations` (helpers.js::annotate), and the
  // safe report keeps every annotation, the status and the FIRST LINE of
  // any failure. Nothing else. Pinned by
  // tests/e2e/test_prod_auth_artifact_safety.py.
  reporter: [[path.join(__dirname, "prod-auth-safe-reporter.js")]],
  use: {
    // Deliberately NO baseURL: every navigation and API call builds its
    // absolute URL through helpers.js::prodUrl(PROD_ORIGIN), so a spec
    // cannot accidentally hit a relative (and therefore nonexistent)
    // origin.
    // NEVER capture production into files (security S3): a trace records
    // every request header (the session cookie) and every response body
    // (private board/roster data); screenshots and video show private
    // pages. A production finding is debugged from the sanitized report's
    // annotations and by re-running locally — not from a public artifact.
    trace: "off",
    screenshot: "off",
    video: "off",
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
      // `@desktop-only` in a test title = an API-contract or desktop-layout
      // check that a 390px viewport cannot add evidence to. Filtered here,
      // at collection, rather than collected-then-skipped: a skip inflates
      // the run's skip count without saying anything about production.
      // (Older specs still gate with helpers.js::desktopOnly; both work.)
      grepInvert: /@desktop-only/,
      use: {
        browserName: "chromium",
        viewport: { width: 390, height: 844 },
        hasTouch: true,
        isMobile: true,
      },
    },
  ],
});

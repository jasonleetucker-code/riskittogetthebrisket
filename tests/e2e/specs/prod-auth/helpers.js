/**
 * Shared fixture + helpers for the production-auth verification specs.
 *
 * These specs run against the DEPLOYED production site with a real
 * session cookie.  They are read-only over the product: navigation, DOM
 * reads and network observation only — the single POST they make is
 * `/api/trade/simulate`, a pure computation endpoint that mutates
 * nothing.
 *
 * Env contract (both required; the fixture skips cleanly otherwise):
 *   PROD_ORIGIN               e.g. https://chaseupside.com
 *   PROD_SESSION_COOKIE_FILE  path to a file containing ONLY the VALUE
 *                             of the `jason_session` cookie
 *
 * The cookie value is never logged, never annotated, and never included
 * in an assertion message — treat every failure path here as one that
 * ends up in CI logs.
 */
const fs = require("node:fs");
const base = require("@playwright/test");

const ORIGIN = String(process.env.PROD_ORIGIN || "").replace(/\/+$/, "");
const COOKIE_FILE = String(process.env.PROD_SESSION_COOKIE_FILE || "");

/** Both env vars present — the only mode these specs run in. */
function isConfigured() {
  return Boolean(ORIGIN && COOKIE_FILE);
}

/**
 * Absolute production URL for a path.  Every navigation in these specs
 * goes through here — there is no local webServer and no baseURL split,
 * so this is the prod-auth analogue of helpers/journey.js::pageUrl().
 */
function prodUrl(path) {
  if (!ORIGIN) throw new Error("PROD_ORIGIN is not set");
  return ORIGIN + path;
}

/** Read the cookie VALUE from the file. Never log the return value. */
function readCookieValue() {
  const raw = fs.readFileSync(COOKIE_FILE, "utf-8").trim();
  if (!raw) {
    throw new Error(
      `PROD_SESSION_COOKIE_FILE (${COOKIE_FILE}) is empty — it must ` +
        "contain only the jason_session cookie value.",
    );
  }
  if (/\r|\n/.test(raw)) {
    throw new Error(
      "PROD_SESSION_COOKIE_FILE contains multiple lines — expected the " +
        "bare cookie value on one line.",
    );
  }
  return raw;
}

/**
 * GET a JSON API endpoint with the session cookie (page.request shares
 * the browser context's cookie jar).  Returns { status, body } — body is
 * null when the response is not JSON.
 */
async function getJson(page, path, { timeoutMs = 45_000 } = {}) {
  const res = await page.request.get(prodUrl(path), { timeout: timeoutMs });
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON — caller branches on status */
  }
  return { status: res.status(), body };
}

/** Record an observed value into the test report, visibly and durably. */
function annotate(testInfo, type, description) {
  testInfo.annotations.push({ type, description: String(description) });
}

/**
 * Loose person-name normalization for cross-source joins (board display
 * name vs Sleeper roster spelling).  Lowercase alphanumerics only, with
 * common suffixes dropped.  Used to COMPARE, never to invent identity:
 * callers report which matches needed it.
 */
function normName(name) {
  return String(name || "")
    .toLowerCase()
    .replace(/\b(jr|sr|ii|iii|iv|v)\b\.?/g, "")
    .replace(/[^a-z0-9]/g, "");
}

/**
 * Replicas of the two display formatters SimulationPanel uses
 * (frontend/app/trade/trade-sections.jsx).  Replicated so the spec can
 * state the EXPECTED rendering from the backend response — the
 * assertion is "the page shows the backend's number under the backend's
 * formatting", so the formatter must match character-for-character
 * (note fmtSigned's U+2212 minus).
 */
function fmtSigned(n) {
  const v = Math.round(Number(n) || 0);
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toLocaleString("en-US")}`;
}

function strengthText(v) {
  const n = Number(v);
  return Number.isFinite(n) ? Math.round(n).toLocaleString("en-US") : "—";
}

/** Gate a test to one of the two prod-auth projects. */
function desktopOnly(test, testInfo) {
  test.skip(
    testInfo.project.name !== "prod-desktop",
    "desktop-viewport check — runs on the prod-desktop project only",
  );
}

function mobileOnly(test, testInfo) {
  test.skip(
    testInfo.project.name !== "prod-mobile",
    "mobile-viewport check — runs on the prod-mobile project only",
  );
}

/**
 * `prodPage` fixture: a page whose browser context carries the real
 * production session cookie, verified live against /api/auth/status
 * before any test body runs.
 *
 * Skip vs fail policy, deliberately split:
 *   - env unset            → SKIP (these specs only run in the
 *                            production-verification workflow; a default
 *                            local/CI run must not fail on their absence)
 *   - cookie file unreadable, or the cookie does not authenticate
 *                          → FAIL loudly. The workflow supplied
 *                            credentials and they do not work; reporting
 *                            that as a skip would read as "fine".
 */
const test = base.test.extend({
  prodPage: async ({ page, context }, use) => {
    if (!isConfigured()) {
      base.test.skip(
        true,
        "PROD_ORIGIN / PROD_SESSION_COOKIE_FILE not set — prod-auth " +
          "specs run only in the production verification workflow",
      );
      return;
    }
    const value = readCookieValue();
    await context.addCookies([
      {
        name: "jason_session",
        value,
        url: ORIGIN,
        httpOnly: true,
        secure: ORIGIN.startsWith("https"),
        sameSite: "Lax",
      },
    ]);

    const { status, body } = await getJson(page, "/api/auth/status");
    if (status !== 200 || !body || body.authenticated !== true) {
      throw new Error(
        `The supplied session cookie did not authenticate against ` +
          `${ORIGIN}/api/auth/status (HTTP ${status}, authenticated=` +
          `${body ? body.authenticated : "n/a"}). This is a REAL failure ` +
          "— the workflow supplied credentials and they do not work. " +
          "(The cookie value itself is deliberately not printed.)",
      );
    }

    await use(page);
  },
});

/**
 * `publicPage` fixture: an ANONYMOUS page against production.
 *
 * W1-12 verifies the PUBLIC Week 1 pregame surface, which by definition
 * must work with no session — so asserting it through `prodPage` would
 * prove the wrong thing. It lives in this file rather than a second
 * harness because the origin, the skip policy and the URL builder are
 * the same ones; only the cookie differs, and duplicating the rest is
 * how two prod harnesses start disagreeing about which origin they hit.
 *
 * Skips on a missing PROD_ORIGIN only. It deliberately does NOT require
 * PROD_SESSION_COOKIE_FILE: needing a credential to check that
 * something is reachable without one would be self-defeating.
 */
const publicTest = base.test.extend({
  publicPage: async ({ page, context }, use) => {
    if (!ORIGIN) {
      base.test.skip(
        true,
        "PROD_ORIGIN not set — production specs run only in the " +
          "production verification workflow",
      );
      return;
    }
    // Prove anonymity rather than assume it: a leftover cookie from
    // another spec's context would silently turn a public check into an
    // authenticated one, and it would still pass.
    await context.clearCookies();
    await use(page);
  },
});

module.exports = {
  test,
  publicTest,
  expect: base.expect,
  ORIGIN,
  isConfigured,
  prodUrl,
  getJson,
  annotate,
  normName,
  fmtSigned,
  strengthText,
  desktopOnly,
  mobileOnly,
};

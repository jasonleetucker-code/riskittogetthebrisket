/**
 * Screenshot import — production availability probe (CQ-11).
 *
 * `GET /api/trade/import-screenshot/status` is how /trade decides whether the
 * "Import trade from screenshot" dialog can read an image.  Against the
 * DEPLOYED site, with a real member session, this proves the endpoint answers
 * one of exactly two honest states:
 *
 *   - `available: true`  — `reason: null` and the engine names a version;
 *   - `available: false` — `reason` is a NAMED code (e.g.
 *     `tesseract_not_installed`, `tesseract_not_runnable`), never a blank
 *     "unavailable".
 *
 * And that the payload is availability FACTS only: exactly the documented
 * keys, no numbers at all (no values, counts or scores can ride on it), and
 * `Cache-Control: no-store`.
 *
 * Read-only: one GET.  It never uploads an image — the upload route needs a
 * member's own screenshots (CQ-12, owner-only) and a POST from this suite
 * would need an allowlisted, reviewed reason.
 *
 * Annotations publish only the HTTP status, booleans and the reason CODE
 * (an API enum), per tests/e2e/prod-auth-annotation-allowlist.js.
 */
const { test, expect, prodUrl, annotate } = require("./helpers");

const STATUS_PATH = "/api/trade/import-screenshot/status";
const STATUS_KEYS = ["available", "enabled", "engine", "reason", "version"];
const REASON_CODE = /^[a-z][a-z0-9_]{2,39}$/;

test.describe("screenshot import status (CQ-11)", () => {
  test("@desktop-only status reports available, or names why it is not", async ({ prodPage }, testInfo) => {
    const res = await prodPage.request.get(prodUrl(STATUS_PATH), { timeout: 45_000 });
    annotate(testInfo, "screenshot-status-http", res.status());
    expect(res.status(), `${STATUS_PATH} must answer a signed-in member`).toBe(200);
    expect(res.headers()["cache-control"] || "", "status must not be cached").toContain("no-store");

    const body = await res.json();
    expect(Object.keys(body).sort(), "exactly the documented status keys").toEqual(STATUS_KEYS);
    const noValues = Object.values(body).every((v) => typeof v !== "number");
    annotate(testInfo, "screenshot-status-no-values", noValues);
    expect(noValues, "the status carries availability facts only — no numbers").toBe(true);

    expect(body.engine).toBe("tesseract");
    expect(typeof body.available, "available is a boolean").toBe("boolean");
    expect(typeof body.enabled, "enabled is a boolean").toBe("boolean");
    annotate(testInfo, "screenshot-status-available", body.available);
    annotate(testInfo, "screenshot-status-enabled", body.enabled);

    const versionPresent = typeof body.version === "string" && body.version.length > 0;
    annotate(testInfo, "screenshot-status-version-present", versionPresent);

    if (body.available) {
      expect(body.reason, "an available engine carries no reason").toBeNull();
      expect(versionPresent, "an available engine names its version").toBe(true);
      annotate(testInfo, "screenshot-status-reason", "none");
    } else {
      expect(typeof body.reason, "unavailable must name a reason").toBe("string");
      expect(body.reason, "the reason is a code, not prose").toMatch(REASON_CODE);
      annotate(testInfo, "screenshot-status-reason", body.reason);
    }
  });
});

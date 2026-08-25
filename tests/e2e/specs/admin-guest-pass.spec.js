/**
 * V1-101 (#779) — `/admin` renders guest-pass expiry without crashing.
 *
 * THE DEFECT this pins.
 * `GuestPassPanel` was extracted out of `/settings` and its two calls to
 * `fmtPassExpiry` came with it, while the definition stayed behind as
 * dead code in `app/settings/page.jsx`. `/admin` then hit the global
 * client-side error boundary with `Can't find variable: fmtPassExpiry`
 * on every load that had a pass to list. Repaired by moving the helper
 * into `frontend/lib/guest-pass-format.js`, a module export that cannot
 * be orphaned by extracting its caller.
 *
 * WHY AN E2E TEST WHEN A COMPONENT TEST ALREADY EXISTS.
 * `frontend/__tests__/components/admin/GuestPassPanel.test.jsx` covers
 * the reachability condition and passes — but it cannot, in principle,
 * catch the class of bug that caused #779. That was a MODULE-SCOPE
 * failure in the built client bundle: an identifier that resolved during
 * a jsdom render of the component in isolation, but did not exist in the
 * chunk the browser actually downloaded. A test that imports the
 * component directly supplies the very scope whose absence was the bug.
 * Only the real production build, loaded by a real browser, can see it.
 *
 * That distinction is the whole reason V1-101 is an L4 row: component
 * evidence is real, and it is L2 — it is not proof the deployed surface
 * consumes the canonical helper.
 *
 * THE REACHABILITY CONDITION IS THE POINT.
 * The crash needed a NON-EMPTY pass list — `fmtPassExpiry` is called
 * once per row and once for a freshly minted token, so an empty-state
 * smoke test renders zero rows, calls it zero times, and passes over a
 * page that would explode for the operator. The list is stubbed here
 * rather than minted, because the bug lives in the CLIENT BUNDLE and is
 * indifferent to where the rows came from — and stubbing makes the row
 * count deterministic instead of dependent on whatever passes happen to
 * exist on the box.
 *
 * NOT COVERED HERE, deliberately: whether the DEPLOYED production build
 * serves this. That is the remaining L4 requirement and it needs a
 * deployed SHA, not a local one. The recipe is in
 * `docs/master-site-audit/evidence/V1-101/L4_PRODUCTION_RECIPE.md`.
 */
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled } = require("../helpers/journey");

// Fixed epochs so the rendered strings are deterministic.
const HOUR = 3600;
const nowSec = () => Math.floor(Date.now() / 1000);

function passFixture() {
  const now = nowSec();
  return {
    passes: [
      {
        id: 1,
        note: "e2e-active-pass",
        createdBy: "e2e",
        createdAtEpoch: now - HOUR,
        // ~3h out: the panel's relative branch renders "in 3h".
        expiresAtEpoch: now + 3 * HOUR,
        revokedAtEpoch: null,
        isRevoked: false,
        isExpired: false,
        isActive: true,
      },
      {
        id: 2,
        // MISSING IS NEVER ZERO: a pass with no stamped expiry must
        // render an em dash, not "1970". Epoch 0 is a real instant, so
        // this is the case a naive `new Date(epoch * 1000)` gets wrong.
        note: "e2e-no-expiry-pass",
        createdBy: "e2e",
        createdAtEpoch: now - 2 * HOUR,
        expiresAtEpoch: null,
        revokedAtEpoch: null,
        isRevoked: false,
        isExpired: false,
        isActive: false,
      },
    ],
  };
}

test.describe("signed-in: /admin guest passes", () => {
  // The app registers a service worker (`frontend/public/sw.js`). Once
  // it is installed it handles page fetches, and `page.route()` does not
  // intercept those — so the stub below applied on a cold profile and
  // was silently bypassed afterwards, letting the panel receive the real
  // 404 ("Server error (404) … No passes yet."). That presented as an
  // intermittent failure of an assertion about something else entirely.
  test.use({ serviceWorkers: "block" });

  test("renders expiry for a non-empty pass list, with no client error", async ({
    authedPage,
  }) => {
    const clientErrors = [];
    authedPage.on("pageerror", (err) => clientErrors.push(String(err)));

    // A URL PREDICATE, not a glob. This context sets `baseURL` to the
    // API origin while pages are served from `E2E_PAGE_ORIGIN`, and a
    // string pattern is resolved against baseURL — so a glob silently
    // failed to match, the panel received the real 404 ("Server error
    // (404) … No passes yet."), and the test failed on an empty list
    // rather than on the thing it is about. A predicate on `pathname`
    // cannot be confused by either origin.
    await authedPage.route(
      (url) => url.pathname === "/api/admin/guest-passes",
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(passFixture()),
        }),
    );

    await authedPage.goto(pageUrl("/admin"), { waitUntil: "domcontentloaded" });
    await awaitStreamSettled(authedPage);

    // The panel must actually be on the page. Without this the whole
    // test passes vacuously on a /admin that rendered "Not authorized".
    await expect(authedPage.getByText("Guest access")).toBeVisible();

    // The reachability condition: rows present, so fmtPassExpiry ran.
    await expect(authedPage.getByText("e2e-active-pass")).toBeVisible();

    // The exact failure mode of #779 — an identifier missing from the
    // shipped chunk surfaces as a pageerror, not as a failed assertion.
    expect(
      clientErrors,
      `Client-side error(s) on /admin: ${clientErrors.join(" | ")}`,
    ).toEqual([]);

    // The helper's real output, not just "the page did not crash".
    await expect(authedPage.getByText(/in 3h/)).toBeVisible();
    // ...and its missing-value branch renders an em dash rather than a
    // 1970 date. Asserted on the row, so a stray em dash elsewhere in
    // the shell cannot satisfy it.
    const emptyRow = authedPage
      .locator("tr", { hasText: "e2e-no-expiry-pass" })
      .first();
    await expect(emptyRow).toContainText("—");
    await expect(emptyRow).not.toContainText("1970");
  });
});

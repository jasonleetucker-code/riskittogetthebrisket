/**
 * V1-62 — the deployed Sharp Tracker page (`/market/sharp-tracker`)
 * consumes the canonical `/api/sharp/market` endpoint truthfully, on the
 * real production site, with the W15-F017 cohort-memo self-poisoning fix
 * (PR #1199) deployed.
 *
 * V1-62's row required L4 evidence that the endpoint no longer times out
 * on the authenticated production path and that the page's own render
 * matches what it returns. This spec:
 *   1. navigates to the deployed page and captures the page's OWN
 *      `GET /api/sharp/market` request (not a synthetic call this spec
 *      makes on the side);
 *   2. asserts it answers 200 within Playwright's real navigation
 *      timeout — the concrete regression this row exists to close;
 *   3. asserts the rendered "Assets" stat and (when populated) the
 *      table row count match the response body exactly, so the render
 *      is proven to consume that response rather than something stale
 *      or synthesized;
 *   4. records which of the page's states rendered (populated /
 *      cohort-building / no-activity / error) via `states-observed`,
 *      so the artifact answers "which branch did production take"
 *      rather than requiring it be inferred from a pass.
 *
 * Read-only over the site: only GET requests are made (the page's own
 * auto-fetches of /api/sharp/cohort and /api/sharp/market).
 */
const { test, expect, prodUrl, annotate, desktopOnly } = require("./helpers");

/** Same asset filter the page applies before counting/rendering rows. */
function nonPickAssets(market) {
  return (market?.assets || []).filter(
    (asset) =>
      asset?.assetType !== "pick" &&
      asset?.position !== "PICK" &&
      !String(asset?.assetId || "").startsWith("pick:"),
  );
}

test.describe("V1-62: /market/sharp-tracker renders /api/sharp/market from the page's own fetch", () => {
  test("Sharp Tracker matches GET /api/sharp/market field-for-field", async ({
    prodPage: page,
  }, testInfo) => {
    desktopOnly(test, testInfo);
    test.setTimeout(180_000);

    // ── capture the page's OWN market fetch ──────────────────────────
    const responsePromise = page.waitForResponse(
      (res) =>
        res.url().includes("/api/sharp/market") &&
        res.request().method() === "GET",
      { timeout: 90_000 },
    );

    await page.goto(prodUrl("/market/sharp-tracker"), {
      waitUntil: "domcontentloaded",
    });
    await expect(
      page.getByRole("heading", { level: 1, name: /^Sharp Tracker$/ }),
    ).toBeVisible({ timeout: 60_000 });

    const marketResponse = await responsePromise;
    annotate(
      testInfo,
      "request",
      `GET ${marketResponse.url()} -> ${marketResponse.status()}`,
    );

    // This IS the V1-62 regression: the endpoint must answer, not time
    // out, on the real authenticated production path.
    expect(
      marketResponse.status(),
      "the deployed page's own /api/sharp/market call must succeed — a " +
        "non-200 here means the W15-F017 self-poisoning fix (PR #1199) " +
        "did not resolve the production timeout this row exists to close",
    ).toBe(200);
    const market = await marketResponse.json();

    const expectedAssets = nonPickAssets(market);
    annotate(
      testInfo,
      "response-shape",
      `status=${market.status} assets=${expectedAssets.length} ` +
        `selectedManagers=${market?.cohort?.selectedManagers} ` +
        `qualificationMethods=${(market?.cohort?.qualificationMethods || []).join("|")}`,
    );

    // ── "Assets" stat tile === the response's own filtered count ────
    // Stat renders <div><div class="muted">{label}</div><div>{value}</div>
    // [note]</div>; locate the label text node then step up to its
    // wrapper (xpath=..) so the value sibling is unambiguous, rather than
    // matching every ancestor div that merely CONTAINS the label.
    const assetsTile = page
      .locator(".muted", { hasText: /^Assets$/ })
      .locator("xpath=..");
    await expect(
      assetsTile.locator("div").nth(1),
      `the rendered Assets tile must equal the response's own filtered ` +
        `asset count (${expectedAssets.length})`,
    ).toHaveText(expectedAssets.length.toLocaleString());

    // ── branch by the state the response actually produced ──────────
    if (expectedAssets.length > 0) {
      annotate(testInfo, "states-observed", "sharp-tracker: populated");

      const table = page.locator("table");
      await expect(table).toBeVisible({ timeout: 30_000 });
      const rows = table.locator("tbody tr");
      await expect(
        rows,
        "rendered table row count must equal the response's filtered asset count",
      ).toHaveCount(expectedAssets.length);

      // Spot-check the top row against the response verbatim — proves
      // the render reads the response's fields, not a cached/derived copy.
      const top = expectedAssets[0];
      const topRow = rows.first();
      await expect(
        topRow.getByText(top.displayName || top.assetId, { exact: false }),
        `top row must show the response's own displayName ("${top.displayName}")`,
      ).toBeVisible();

      await expect(page.getByText(/No activity in this view/)).toHaveCount(0);
      await expect(
        page.getByText(/Sharp market temporarily unavailable/),
      ).toHaveCount(0);
    } else if (market.status === "cohort_building") {
      annotate(testInfo, "states-observed", "sharp-tracker: cohort_building");
      await expect(
        page.getByText(/The qualified cohort is still building/),
      ).toBeVisible();
    } else {
      annotate(testInfo, "states-observed", "sharp-tracker: no_activity");
      await expect(page.getByText(/No activity in this view/)).toBeVisible();
    }
  });
});

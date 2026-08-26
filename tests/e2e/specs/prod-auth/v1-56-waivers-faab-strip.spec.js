/**
 * V1-56 — the /waivers league-FAAB context strip on the DEPLOYED
 * production site renders the analytics API's numbers, and renders
 * missing data as an explicit unavailable state, never as zeros.
 *
 * The strip is FaabHeaderStat (frontend/components/waivers/
 * ManualAddDrop.jsx): three StatTiles — "Your FAAB", "League average
 * bid", "League median bid" — fed by
 * GET /api/public/league/faabAnalytics?leagueKey=… (the page's own
 * fetch, captured here rather than re-derived, so the comparison is
 * against exactly the payload the page consumed).
 *
 * MISSING IS NEVER ZERO, both directions:
 *   - with bid history (`totalBidsAnalyzed > 0`), the tiles must equal
 *     `$${Math.round(v)}` of the API's mean/median — including a
 *     MEASURED $0 median, which is this league's most common answer
 *     and must render as "$0", not be hidden;
 *   - without bid history, the tiles must read "—" (or the strip be
 *     absent), never "$0".
 * The spec asserts whichever state the live payload produces and
 * annotates it.
 */
const {
  test,
  expect,
  prodUrl,
  annotate,
  desktopOnly,
} = require("./helpers");

test.describe("V1-56: /waivers league-FAAB context strip", () => {
  test("the strip equals the faabAnalytics payload the page fetched", async ({
    prodPage: page,
  }, testInfo) => {
    desktopOnly(test, testInfo);

    // Capture the page's OWN analytics fetch. Registered before goto so
    // the response cannot land first.
    const analyticsPromise = page
      .waitForResponse(
        (res) =>
          res.url().includes("/api/public/league/faabAnalytics") &&
          res.request().method() === "GET",
        { timeout: 60_000 },
      )
      .catch(() => null);

    await page.goto(prodUrl("/waivers"), { waitUntil: "domcontentloaded" });
    await expect(
      page.getByRole("heading", { level: 1, name: /^Waivers$/ }),
    ).toBeVisible({ timeout: 90_000 });

    // The ephemeral verifier has no persisted team preference. Establish the
    // team-scoped prerequisite through the same TeamSwitcher a user uses.
    const teamSwitcher = page.locator(".team-switcher").first();
    await expect(teamSwitcher).toBeVisible({ timeout: 30_000 });
    const needsTeam = await teamSwitcher.evaluate((node) =>
      node.classList.contains("team-switcher--needs"),
    );
    if (needsTeam) {
      await teamSwitcher.locator(".team-switcher-toggle").click();
      const option = teamSwitcher.locator(".team-switcher-option").first();
      await expect(option).toBeVisible({ timeout: 15_000 });
      const chosen = (await option.innerText()).trim();
      await option.click();
      annotate(testInfo, "team-context", `selected through TeamSwitcher: ${chosen}`);
    } else {
      annotate(
        testInfo,
        "team-context",
        `already resolved by the shell: ${(await teamSwitcher.innerText()).trim()}`,
      );
    }

    const analyticsRes = await analyticsPromise;
    let data = null;
    if (analyticsRes) {
      annotate(
        testInfo,
        "analytics-fetch",
        `${analyticsRes.status()} ${new URL(analyticsRes.url()).pathname}${new URL(analyticsRes.url()).search}`,
      );
      if (analyticsRes.status() === 200) {
        const json = await analyticsRes.json().catch(() => null);
        // The strip reads one level down (`json.data`) — the nesting
        // ManualAddDrop.jsx documents.
        data = json?.data ?? null;
      }
    } else {
      annotate(
        testInfo,
        "analytics-fetch",
        "no faabAnalytics request observed within 60s",
      );
    }

    const tileValue = (label) =>
      page
        .locator("div.ds-stat")
        .filter({
          has: page.locator(".ds-stat__label", {
            hasText: new RegExp(`^${label}$`),
          }),
        })
        .locator(".ds-stat__value");

    const avgTile = tileValue("League average bid");
    const medianTile = tileValue("League median bid");

    if (data && (data.leagueAvgWinningBid != null || data.leagueMedianWinningBid != null)) {
      // ── Populated payload: formatting-aware equality ───────────────
      const avg = data.leagueAvgWinningBid;
      const median = data.leagueMedianWinningBid;
      const analyzed = data.totalBidsAnalyzed;
      // Replica of the component's own evidence gate (MISSING != ZERO):
      // a zero with no observation count must render unknown, a zero
      // WITH observations is a real $0.
      const hasBidHistory =
        analyzed != null
          ? analyzed > 0
          : (avg != null && avg > 0) || (median != null && median > 0);
      const expected = (v) =>
        hasBidHistory && v != null ? `$${Math.round(v)}` : "—";

      await expect(
        avgTile,
        `League average bid must render the API's mean (${avg}, analyzed=${analyzed})`,
      ).toHaveText(expected(avg), { timeout: 30_000 });
      await expect(
        medianTile,
        `League median bid must render the API's median (${median}, analyzed=${analyzed})`,
      ).toHaveText(expected(median));
      annotate(
        testInfo,
        "state-observed",
        hasBidHistory
          ? `populated: avg=${expected(avg)} median=${expected(median)} over ${analyzed} bids` +
            (median === 0 ? " (measured $0 median rendered honestly)" : "")
          : "payload present but zero evidence — em-dash unavailable state verified",
      );
    } else {
      // ── Missing/absent analytics: explicit unavailable, never $0 ───
      const stripTiles = await avgTile.count();
      if (stripTiles > 0) {
        await expect(
          avgTile,
          "analytics unavailable but the average tile renders a figure — missing must not read as a number",
        ).toHaveText("—");
        await expect(medianTile).toHaveText("—");
        annotate(
          testInfo,
          "state-observed",
          "analytics absent: strip rendered with explicit em-dash unavailable state",
        );
      } else {
        annotate(
          testInfo,
          "state-observed",
          "analytics absent and no team context: strip absent entirely (its documented null state)",
        );
      }
      // Whichever shape, "$0" must not have been invented anywhere in
      // the bid tiles.
      await expect(avgTile.filter({ hasText: /^\$0$/ })).toHaveCount(0);
      await expect(medianTile.filter({ hasText: /^\$0$/ })).toHaveCount(0);
    }
  });
});

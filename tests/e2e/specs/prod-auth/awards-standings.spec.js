/**
 * Awards — 2026 Waiver King eligibility + Expand standings (owner directive
 * 2026-09-26), verified on the deployed public League Hub, desktop and
 * phone (prod-desktop / prod-mobile).
 *
 * Every expectation is read from the live `/api/public/league/awards`
 * payload first and then checked on the rendered page, so the run is its
 * own evidence whatever week it lands in:
 *   - 2026 Waiver King: Joel / Blaine never hold the award or an award-race
 *     rank; their real metric is in the standings, labelled ineligible; the
 *     leader is the best eligible manager;
 *   - a player award (League MVP, else Top QB) expands to the API's rows in
 *     the API's order;
 *   - Top Offense / Top Defense list every team in the API's order;
 *   - Manager of the Year / Trader of the Year / Waiver King expand;
 *   - no sideways page scroll; the toggle announces its expanded state.
 */
const { test, expect, ORIGIN, prodUrl, getJson, annotate } = require("./helpers");

const JOEL = "712035316776669184";
const BLAINE = "1303549304882892800";

function configured() {
  return Boolean(String(ORIGIN || "").trim());
}

async function noPageOverflow(page) {
  const s = await page.evaluate(() => ({
    d: document.documentElement.scrollWidth,
    v: document.documentElement.clientWidth,
  }));
  expect(s.d, "the page must not scroll sideways").toBeLessThanOrEqual(s.v + 1);
}

function card(page, key) {
  return page.locator(`article[data-award-key="${key}"]`);
}

async function expand(page, key) {
  const root = card(page, key);
  await root.scrollIntoViewIfNeeded();
  const btn = root.getByRole("button", { name: /Expand standings/ });
  await expect(btn).toHaveAttribute("aria-expanded", "false");
  await btn.click();
  await expect(root.getByRole("button", { name: /Collapse standings/ })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  const list = root.locator("[data-award-standings] ol");
  await expect(list).toBeVisible();
  return list.locator(":scope > li");
}

test.describe("Awards standings + 2026 Waiver King eligibility (production)", () => {
  test("API and page agree; Joel/Blaine cannot win 2026 Waiver King; every expansion is the backend's ranking", async ({
    page,
  }, testInfo) => {
    test.skip(!configured(), "PROD_ORIGIN is not configured");
    test.setTimeout(300_000);

    const { status, body } = await getJson(page, "/api/public/league/awards", {
      timeoutMs: 90_000,
    });
    expect(status).toBe(200);
    const data = body.data;
    const races = new Map((data.awardRaces || []).map((r) => [r.key, r]));
    const season = data.currentSeason;

    // ── 2026 Waiver King eligibility, on the API ──
    const wk = races.get("waiver_king");
    const seasonRow = (data.bySeason || []).find((s) => s.season === "2026");
    const wkAward = seasonRow && (seasonRow.awards || []).find((a) => a.key === "waiver_king");
    if (wkAward && !wkAward.awaitingEvidence) {
      expect([JOEL, BLAINE]).not.toContain(wkAward.ownerId);
    }
    if (season === "2026" && wk && !wk.awaitingEvidence) {
      expect(wk.leaders.map((l) => l.ownerId)).not.toContain(JOEL);
      expect(wk.leaders.map((l) => l.ownerId)).not.toContain(BLAINE);
      for (const row of wk.standings || []) {
        if (row.ownerId === JOEL || row.ownerId === BLAINE) {
          expect(row.eligible).toBe(false);
          expect(row.awardRank).toBeNull();
          expect(row.ineligibleLabel).toBe("Ineligible for 2026 award");
          expect(typeof row.value.pointsGained).toBe("number");
        } else {
          expect(row.eligible).toBe(true);
        }
      }
      const firstEligible = (wk.standings || []).find((r) => r.eligible);
      if (firstEligible) expect(wk.leaders[0].ownerId).toBe(firstEligible.ownerId);
    }
    annotate(
      testInfo,
      "waiver-king",
      `season=${season} winner=${wkAward ? wkAward.displayName : "none"} standings=${(wk?.standings || [])
        .map((r) => `${r.rank}:${r.displayName}:${r.value?.pointsGained}:${r.eligible ? `A${r.awardRank}` : "INELIGIBLE"}`)
        .join(" | ")}`,
    );

    await page.goto(prodUrl("/league?tab=awards"), { waitUntil: "domcontentloaded", timeout: 60_000 });
    await expect(card(page, (data.awardRaces || [])[0].key)).toBeVisible({ timeout: 60_000 });
    await noPageOverflow(page);

    // ── Waiver King on the page ──
    if (wk && (wk.standings || []).length) {
      const rows = await expand(page, "waiver_king");
      await expect(rows).toHaveCount(wk.standings.length);
      for (let i = 0; i < wk.standings.length; i++) {
        const r = wk.standings[i];
        await expect(rows.nth(i)).toContainText(r.displayName);
        await expect(rows.nth(i)).toHaveAttribute("data-eligible", r.eligible ? "true" : "false");
        if (!r.eligible) await expect(rows.nth(i)).toContainText(r.ineligibleLabel);
      }
      await noPageOverflow(page);
    }

    // ── A player award ──
    const playerKey = ["league_mvp", "top_qb"].find((k) => (races.get(k)?.standings || []).length);
    if (playerKey) {
      const api = races.get(playerKey).standings;
      const rows = await expand(page, playerKey);
      await expect(rows).toHaveCount(api.length);
      expect(api.length).toBeLessThanOrEqual(12);
      for (let i = 0; i < api.length; i++) {
        await expect(rows.nth(i)).toContainText(api[i].value.playerName);
      }
      const link = rows.first().locator("a[href^='/players/']");
      if ((await link.count()) > 0) {
        await expect(link.first()).toHaveAttribute(
          "href",
          `/players/${encodeURIComponent(api[0].value.playerId)}`,
        );
      }
      annotate(testInfo, "player-award", `${playerKey}: ${api.map((r) => r.value.playerName).join(", ")}`);
    }

    // ── Team statistics: every team, API order ──
    for (const key of ["top_offense", "top_defense"]) {
      const api = races.get(key)?.standings || [];
      if (!api.length) continue;
      const rows = await expand(page, key);
      await expect(rows).toHaveCount(api.length);
      for (let i = 0; i < api.length; i++) {
        await expect(rows.nth(i)).toContainText(api[i].displayName);
      }
      annotate(testInfo, key, api.map((r) => `${r.rank}:${r.displayName}`).join(", "));
    }

    // ── Manager awards ──
    for (const key of ["manager_of_the_year", "trader_of_the_year"]) {
      const api = races.get(key)?.standings || [];
      if (!api.length) continue;
      const rows = await expand(page, key);
      await expect(rows).toHaveCount(api.length);
      await expect(rows.first()).toContainText(api[0].displayName);
    }

    await noPageOverflow(page);
    const shot = testInfo.outputPath("awards-standings.png");
    await page.screenshot({ path: shot, fullPage: false });
    await testInfo.attach("awards-standings", { path: shot, contentType: "image/png" });
  });
});

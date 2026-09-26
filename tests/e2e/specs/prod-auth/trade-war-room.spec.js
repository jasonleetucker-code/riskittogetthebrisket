/**
 * Trade War Room — production acceptance (#792 / #1173 / #843 / #842).
 *
 * Drives the deployed /trade with a real team and real players, three trade
 * shapes, and checks the War Room against the page's OWN
 * `POST /api/trade/analyze` response (never a second computation):
 *
 *   1-for-1   — roster size unchanged, so no forced-drop cost may appear;
 *   2-for-1   — consolidation: the roster shrinks by one;
 *   1-for-2   — expansion: the roster grows by one, and at the cap a cut is
 *               required and named.
 *
 * Plus the Team Context round trip on one shape, the selected league echoed
 * back (no cross-league fallback), and no sideways page scroll — on desktop
 * AND phone (the prod-mobile project).  Everything production actually said
 * (recommendation, market gap, roster impact or its named unavailability,
 * feasibility state) is annotated, so the run is its own evidence.
 */
const { test, expect, prodUrl, getJson, annotate } = require("./helpers");

const PICK_TOKEN = /\d{4}/;
const LABELS = {
  MAKE: "Make the trade",
  LEAN_MAKE: "Lean make",
  TOO_CLOSE: "Too close / depends",
  LEAN_PASS: "Lean pass",
  PASS: "Pass",
};

function signedPpg(v) {
  const r = Math.round(v * 10) / 10;
  if (r === 0) return "±0.0";
  return `${r > 0 ? "+" : "−"}${Math.abs(r).toFixed(1)}`;
}

async function noPageOverflow(page) {
  const s = await page.evaluate(() => ({
    d: document.documentElement.scrollWidth,
    v: document.documentElement.clientWidth,
  }));
  expect(s.d, "the page must not scroll sideways").toBeLessThanOrEqual(s.v + 1);
}

async function plan(page) {
  // The FULL contract: view=app strips playersArray, and the legacy
  // players dict also names rows the materialized board never offers to
  // the /trade search (first production run: "Barrett Carter" was in the
  // dict and unsearchable). Only ranked, priced rows are the search's pool.
  const { status, body: contract } = await getJson(page, "/api/data", { timeoutMs: 120_000 });
  expect(status, "/api/data must serve the session").toBe(200);
  const teams = contract?.sleeper?.teams || [];
  const board = new Set();
  for (const p of contract?.playersArray || []) {
    const v = Number(p?.rankDerivedValue);
    if (p?.displayName && Number.isFinite(v) && v > 0 && typeof p.canonicalConsensusRank === "number") {
      board.add(p.displayName);
    }
  }
  const leagueKey = contract?.meta?.leagueKey || contract?.leagueKey || null;
  const bySize = [...teams].sort((a, b) => (b.players || []).length - (a.players || []).length);
  const my = bySize[0];
  const mine = (my.players || []).filter((p) => p && !PICK_TOKEN.test(p) && board.has(p));
  const donor = teams.find(
    (t) => t !== my && (t.players || []).filter((p) => p && !PICK_TOKEN.test(p) && board.has(p)).length >= 2,
  );
  const theirs = (donor.players || []).filter(
    (p) => p && !PICK_TOKEN.test(p) && board.has(p) && !(my.players || []).includes(p),
  );
  expect(mine.length, "need 2 board-resolvable players on my roster").toBeGreaterThanOrEqual(2);
  expect(theirs.length, "need 2 board-resolvable players on the donor roster").toBeGreaterThanOrEqual(2);
  return { leagueKey, myIdx: teams.indexOf(my), my, mine, theirs };
}

async function openWith(page, p, give, receive) {
  await page.goto(prodUrl("/trade"), { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { level: 1, name: /^Trade Calculator$/ })).toBeVisible({
    timeout: 60_000,
  });
  await page.waitForFunction(() => !document.body.innerText.includes("Loading player pool..."), null, {
    timeout: 90_000,
  });
  // The builder PERSISTS the previous trade across reloads, and the search
  // (correctly) offers no asset that is already in the trade — so without
  // this the second shape re-typed a player still on Side A and got "No
  // matches" (production run 36255440819). Start every shape empty.
  await page.getByRole("button", { name: "Clear Trade", exact: true }).click();
  await page.selectOption("#suggest-team", String(p.myIdx));
  for (const [side, names] of [
    ["A", give],
    ["B", receive],
  ]) {
    for (const name of names) {
      const input = page.getByLabel(`Search to add a player to Side ${side}`);
      await input.click();
      await input.fill(name);
      const esc = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const hit = page
        .locator(".trade-side-search-result")
        .filter({ has: page.locator(".trade-side-search-result-name", { hasText: new RegExp(`^${esc}$`) }) })
        .first();
      await expect(hit).toBeVisible({ timeout: 15_000 });
      if (side === "B" && name === receive[receive.length - 1]) {
        // The last add completes the question.  Capture the page's own
        // answer to EXACTLY this trade — an earlier partial-trade request can
        // still be in flight, and its answer must not be read as this one.
        const same = (a, b) => [...(a || [])].sort().join("|") === [...b].sort().join("|");
        const answer = page.waitForResponse(
          (r) => {
            if (!r.url().includes("/api/trade/analyze") || r.request().method() !== "POST") return false;
            const q = r.request().postDataJSON() || {};
            return same(q.playersOut, give) && same(q.playersIn, receive) && q.useTeamContext !== false;
          },
          { timeout: 120_000 },
        );
        await hit.click();
        return answer;
      }
      await hit.click();
    }
  }
  return null;
}

async function checkShape(page, testInfo, p, label, give, receive) {
  const response = await openWith(page, p, give, receive);
  // The debounce may coalesce; always read the LAST answer the room shows.
  const room = page.locator('[data-war-room="ok"]');
  await expect(room).toBeVisible({ timeout: 120_000 });
  const body = await response.json();
  expect(response.status(), `${label}: analyze answered ${response.status()}`).toBe(200);
  const req = response.request().postDataJSON() || {};
  expect(req.teamName).toBe(p.my.name);
  for (const g of give) expect(req.playersOut).toContain(g);
  for (const r of receive) expect(req.playersIn).toContain(r);
  if (p.leagueKey) expect(body.leagueKey, "no cross-league fallback").toBe(p.leagueKey);
  expect(body.teamContext).toEqual({ applied: true, mode: "team" });

  const a = body.analysis;
  await expect(room.getByText(LABELS[a.recommendation], { exact: true })).toBeVisible();
  const cap = body.rosterCapacity || {};
  const feas = a.lenses.feasibility;
  const roster = a.lenses.roster;
  if (roster.detail && roster.detail.ppg != null && (roster.available || roster.unavailableReason === "partial_projection_coverage")) {
    await expect(room.locator('[data-lens="roster"]').getByText(signedPpg(roster.detail.ppg), { exact: true })).toBeVisible();
  }
  annotate(
    testInfo,
    `war-room-${label}`,
    [
      `rec=${a.recommendation}/${a.confidence}`,
      `market=${a.lenses.market.detail?.vaAdjustedGap}`,
      `roster=${roster.available ? roster.detail.ppg : `unavailable:${roster.unavailableReason}`}`,
      `feas=${feas.detail?.state || feas.unavailableReason}`,
      `size=${cap.sizeBefore}->${cap.sizeAfter}/${cap.rosterLimit}`,
      `drops=${(cap.forcedDrops || []).map((d) => d.name).join("|")}`,
      `basis=${roster.detail?.basis?.source || "-"}`,
    ].join(" "),
  );
  await noPageOverflow(page);
  return { body, cap, feas, room };
}

test.describe("Trade War Room (production)", () => {
  test("1-for-1, 2-for-1 and 1-for-2 on a real roster, plus Asset-Only", async ({ prodPage: page }, testInfo) => {
    test.setTimeout(600_000);
    const p = await plan(page);
    annotate(testInfo, "war-room-team", `${p.my.name} (${(p.my.players || []).length} players) league=${p.leagueKey}`);

    // 1-for-1: size unchanged → no false forced-drop cost.
    const one = await checkShape(page, testInfo, p, "1for1", [p.mine[0]], [p.theirs[0]]);
    expect(one.cap.sizeAfter).toBe(one.cap.sizeBefore);
    expect(one.cap.forcedDrops || []).toEqual(one.cap.overLimitBefore > 0 ? one.cap.forcedDrops : []);
    expect(one.feas.detail?.state).not.toBe("cut_required");

    // 2-for-1 consolidation: one spot freed.
    const two = await checkShape(page, testInfo, p, "2for1", [p.mine[0], p.mine[1]], [p.theirs[0]]);
    expect(two.cap.sizeAfter).toBe(two.cap.sizeBefore - 1);

    // Asset-Only on the same trade: roster and feasibility excluded by mode.
    const offAnswer = page.waitForResponse(
      (r) => r.url().includes("/api/trade/analyze") && r.request().method() === "POST" &&
        (r.request().postDataJSON() || {}).useTeamContext === false,
      { timeout: 120_000 },
    );
    await page.getByRole("radio", { name: "Asset only" }).click();
    const off = await (await offAnswer).json();
    expect(off.teamContext).toEqual({ applied: false, mode: "asset_only" });
    await expect(
      two.room.locator('[data-lens="roster"]').getByText("Not included in Asset-Only analysis").first(),
    ).toBeVisible({ timeout: 60_000 });
    annotate(testInfo, "war-room-asset-only", `rec=${off.analysis.recommendation}`);

    // 1-for-2 expansion: one more body; at the cap a cut is required and named.
    const three = await checkShape(page, testInfo, p, "1for2", [p.mine[0]], [p.theirs[0], p.theirs[1]]);
    expect(three.cap.sizeAfter).toBe(three.cap.sizeBefore + 1);
    if (three.cap.requiresDrops === true) {
      await expect(three.room.locator('[data-lens="feasibility"]').getByText(/likely cut:/)).toBeVisible();
    }

    const shot = testInfo.outputPath("war-room-1for2.png");
    await page.screenshot({ path: shot, fullPage: false });
    await testInfo.attach("war-room-1for2", { path: shot, contentType: "image/png" });
  });
});

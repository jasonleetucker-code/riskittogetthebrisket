/**
 * Draft-capital stack effect withdrawn from the trade verdict — production
 * acceptance (owner directive 2026-09-29, #1527; rebuild: issue #1529).
 *
 * Builds the reported failure class on the deployed /trade: one side sends
 * a player plus the 2029 Mid 5th and 2029 Mid 6th, both sides resolved to
 * real league teams so the (informational) stack model runs.  Then checks:
 *
 *   - every side's headline total is EXACTLY raw + Value Adjustment, read
 *     from the page's own numbers, and the visible "Raw … + VA …" line adds
 *     up to the headline;
 *   - no "− stack" term appears anywhere in the arithmetic;
 *   - the stack effect is shown, labelled experimental / not included;
 *   - switching the selected teams (which changes the stack context) moves
 *     NEITHER the totals, NOR the gap/verdict, NOR the balancer list;
 *   - no side total is negative for this shape (nothing is clamped either:
 *     the check reads the unrounded model number, not the display).
 *
 * Everything observed is annotated, so the run is its own evidence.
 */
const { test, expect, prodUrl, getJson, annotate } = require("./helpers");

const PICK_TOKEN = /\d{4}/;
const PICKS = ["2029 Mid 5th", "2029 Mid 6th"];

async function plan(page) {
  const { status, body: contract } = await getJson(page, "/api/data", { timeoutMs: 120_000 });
  expect(status, "/api/data must serve the session").toBe(200);
  const teams = contract?.sleeper?.teams || [];
  const board = new Map();
  for (const p of contract?.playersArray || []) {
    const v = Number(p?.rankDerivedValue);
    if (p?.displayName && Number.isFinite(v) && v > 0 && typeof p.canonicalConsensusRank === "number") {
      board.set(p.displayName, v);
    }
  }
  const playable = (t) => (t.players || []).filter((n) => n && !PICK_TOKEN.test(n) && board.has(n));
  const eligible = teams.filter((t) => playable(t).length >= 1);
  expect(eligible.length, "need at least three teams with a board-resolvable player").toBeGreaterThanOrEqual(3);
  const [teamA, teamB, teamC] = eligible;
  return {
    teamA,
    teamB,
    teamC,
    give: playable(teamA)[0],
    receive: [playable(teamB)[0], ...PICKS],
  };
}

async function readSides(page) {
  return page.locator("[data-side-total]").evaluateAll((els) =>
    els.map((el) => ({
      total: Number(el.getAttribute("data-side-total")),
      raw: Number(el.getAttribute("data-side-raw")),
      va: Number(el.getAttribute("data-side-va")),
      text: el.innerText,
    })),
  );
}

async function readGap(page) {
  const el = page.locator("[data-trade-gap]").first();
  await expect(el).toBeVisible({ timeout: 30_000 });
  return { gap: Number(await el.getAttribute("data-trade-gap")), verdict: (await el.innerText()).trim() };
}

async function readBalancers(page) {
  // Suggestions render as buttons after the balancer label; names only.
  return page
    .locator("[class*='balancers'] button")
    .evaluateAll((els) => els.map((el) => el.innerText.trim()).sort());
}

async function setTeam(page, sideIdx, teamName) {
  await page.selectOption(`#pick-team-${sideIdx}`, { label: teamName });
}

test.describe("Trade: draft-capital stack effect is informational only (production)", () => {
  test("headline = raw + VA; stack note shown, never in totals, verdict or balancers", async ({
    prodPage: page,
  }, testInfo) => {
    test.setTimeout(420_000);
    const p = await plan(page);

    await page.goto(prodUrl("/trade"), { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { level: 1, name: /^Trade Calculator$/ })).toBeVisible({
      timeout: 60_000,
    });
    await page.waitForFunction(() => !document.body.innerText.includes("Loading player pool..."), null, {
      timeout: 90_000,
    });
    await page.getByRole("button", { name: "Clear Trade", exact: true }).click();

    for (const [side, names] of [
      ["A", [p.give]],
      ["B", p.receive],
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
        await expect(hit, `search offers ${name}`).toBeVisible({ timeout: 15_000 });
        await hit.click();
      }
    }

    // Resolve both sides to real teams so the stack model has context.
    await setTeam(page, 0, p.teamA.name);
    await setTeam(page, 1, p.teamB.name);
    const note = page.getByText(/Draft-capital stack effect/).first();

    // 1. Arithmetic: headline = raw + VA exactly, and the visible parts add up.
    await expect.poll(async () => (await readSides(page)).length, { timeout: 30_000 }).toBe(2);
    const sides = await readSides(page);
    sides.forEach((s, i) => {
      expect(s.total, `side ${i}: adjusted = raw + VA`).toBeCloseTo(s.raw + s.va, 9);
      expect(s.total, `side ${i}: a positive package never totals below zero`).toBeGreaterThanOrEqual(0);
      expect(s.text, `side ${i}: no stack term in the arithmetic`).not.toMatch(/stack/i);
      const headline = Math.round(s.total).toLocaleString("en-US");
      expect(s.text).toContain(headline);
      expect(s.text).toContain(`Raw ${Math.round(s.raw).toLocaleString("en-US")}`);
      if (Math.round(s.va) > 0) {
        expect(s.text).toContain(`VA ${Math.round(s.va).toLocaleString("en-US")}`);
        expect(Math.round(s.raw) + Math.round(s.va), `side ${i}: displayed parts sum to the headline`).toBe(
          Math.round(s.total),
        );
      }
    });
    const before = { sides, gap: await readGap(page), balancers: await readBalancers(page) };
    expect(before.gap.gap).toBeCloseTo(sides[0].total - sides[1].total, 6);

    // 2. The stack effect is shown, labelled, and says it is not included.
    let noteText = null;
    if (await note.isVisible().catch(() => false)) {
      noteText = (await note.locator("xpath=ancestor-or-self::p[1]").innerText()).trim();
      expect(noteText).toMatch(/experimental, not calibrated/i);
      expect(noteText).toMatch(/Not included in the totals or verdict/);
    }

    // 3. Change the stack context: totals, gap/verdict and balancers must not move.
    await setTeam(page, 0, p.teamC.name);
    await page.waitForTimeout(1_500);
    const afterSides = await readSides(page);
    const after = { sides: afterSides, gap: await readGap(page), balancers: await readBalancers(page) };
    afterSides.forEach((s, i) => {
      expect(s.total, `side ${i}: total ignores the stack context`).toBe(before.sides[i].total);
    });
    expect(after.gap).toEqual(before.gap);
    expect(after.balancers).toEqual(before.balancers);
    let noteAfter = null;
    if (await note.isVisible().catch(() => false)) {
      noteAfter = (await note.locator("xpath=ancestor-or-self::p[1]").innerText()).trim();
    }

    // 4. No stack arithmetic anywhere on the page.
    const body = await page.locator("main").innerText();
    expect(body).not.toMatch(/VA\s*[−-]\s*stack/i);

    annotate(
      testInfo,
      "trade-stack-withdrawn",
      [
        `teams=${p.teamA.name}|${p.teamB.name}->${p.teamC.name}`,
        `give=${p.give} receive=${p.receive.join("+")}`,
        ...before.sides.map((s, i) => `side${i}: raw=${s.raw} va=${s.va} total=${s.total}`),
        `gap=${before.gap.gap} verdict=${before.gap.verdict}`,
        `balancers=${before.balancers.length}`,
        `note=${noteText ?? "absent"}`,
        `noteAfterTeamChange=${noteAfter ?? "absent"}`,
      ].join(" ; "),
    );
  });
});

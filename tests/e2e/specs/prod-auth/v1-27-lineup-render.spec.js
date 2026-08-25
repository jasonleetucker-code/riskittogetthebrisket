/**
 * V1-27 / C2-U1 §10 item 2 — the DEPLOYED /terminal (the "/" war room)
 * and /rosters render starters from the server-stamped
 * `sleeper.teams[].optimalLineup`, and unpriced players are excluded
 * from the split rather than silently benched.
 *
 * docs/lineup/C2_U1_CANONICAL_LINEUP.md §10 item 2 is the one checklist
 * item `scripts/verify_lineup_production.py` cannot automate ("needs a
 * browser"); this spec is that browser half. The render markers are
 * read from the components themselves:
 *   - terminal: PortfolioSummary's `.portfolio-starters` list (slot in
 *     `.portfolio-starter-pos`, name in `.portfolio-starter-name`,
 *     SLOT order — the stamp's own `assignments` order), the
 *     starter/bench counts in `.portfolio-split-legend`, and the
 *     `.portfolio-lineup-note` truth ladder disclosure;
 *   - rosters: the "Starters only" scope's `.starter-slots-unavailable`
 *     note, which must appear exactly when a stamp is missing.
 *
 * READ-ONLY GUARANTEE: driving the team switcher would PUT
 * /api/user/state (the real user's saved selection), so every non-GET
 * to that endpoint is intercepted and answered locally — the UI works,
 * production state is never written.
 */
const {
  test,
  expect,
  prodUrl,
  getJson,
  annotate,
  normName,
  desktopOnly,
} = require("./helpers");

/** Loose person-name match: exact normalized, or last token + first initial. */
function namesMatch(a, b) {
  const na = normName(a);
  const nb = normName(b);
  if (na && na === nb) return "exact";
  const ta = String(a || "").trim().toLowerCase().split(/\s+/);
  const tb = String(b || "").trim().toLowerCase().split(/\s+/);
  if (
    ta.length > 1 &&
    tb.length > 1 &&
    normName(ta[ta.length - 1]) === normName(tb[tb.length - 1]) &&
    ta[0][0] === tb[0][0]
  ) {
    return "loose";
  }
  return null;
}

/** Trailing "· N" integer in a split-legend span. */
function trailingCount(text) {
  const m = String(text).match(/·\s*([\d,]+)\s*$/);
  return m ? Number(m[1].replace(/,/g, "")) : NaN;
}

async function blockUserStateWrites(page) {
  await page.route("**/api/user/state**", (route) => {
    const req = route.request();
    if (req.method() === "GET") return route.continue();
    // Answer the write locally so the UI proceeds — production user
    // state is never mutated by this read-only verification.
    let patch = {};
    try {
      patch = req.postDataJSON() || {};
    } catch {
      /* non-JSON body — answer empty */
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ state: patch }),
    });
  });
}

test.describe("V1-27: lineup render consumes the optimalLineup stamp", () => {
  test("terminal portfolio renders the stamped starter/bench split for a real team", async ({
    prodPage: page,
  }, testInfo) => {
    desktopOnly(test, testInfo);
    test.setTimeout(240_000);
    await blockUserStateWrites(page);

    // ── The stamps, from the authenticated contract ──────────────────
    const { status, body: contract } = await getJson(page, "/api/data?view=app");
    expect(status, "/api/data must serve the session").toBe(200);
    const teams = contract?.sleeper?.teams || [];
    expect(teams.length, "contract carries no Sleeper teams").toBeGreaterThan(0);

    const availableTeams = teams.filter(
      (t) => t?.optimalLineup?.available === true,
    );
    const slotSources = [
      ...new Set(teams.map((t) => t?.optimalLineup?.slotSource ?? "absent")),
    ];
    annotate(
      testInfo,
      "stamp-census",
      `${availableTeams.length}/${teams.length} teams carry ` +
        `optimalLineup.available=true · slotSources: ${slotSources.join(",")}`,
    );
    expect(
      availableTeams.length,
      "NO team carries an available optimalLineup stamp — the §7a serving-path regression",
    ).toBeGreaterThan(0);

    // ── Load the war room and resolve which team is displayed ────────
    await page.goto(prodUrl("/"), { waitUntil: "domcontentloaded" });
    await expect(
      page.locator('[aria-label="Team command bar"]'),
    ).toBeVisible({ timeout: 90_000 });

    const switcher = page.locator("button.team-switcher-toggle").first();
    await expect(switcher).toBeVisible({ timeout: 60_000 });
    let displayedName = (await switcher.innerText()).split("\n")[0].trim();
    let team = teams.find((t) => t.name === displayedName) || null;

    if (!team || team.optimalLineup?.available !== true) {
      // No usable pre-selected team: pick the one with the richest
      // stamp — the PUT this triggers is intercepted above, so the
      // real user's saved selection is untouched.
      const target = [...availableTeams].sort(
        (a, b) =>
          (b.optimalLineup.assignments || []).length -
          (a.optimalLineup.assignments || []).length,
      )[0];
      await switcher.click();
      await page
        .locator(".team-switcher-menu")
        .first()
        .locator('[role="option"]', { hasText: target.name })
        .first()
        .click();
      team = target;
      displayedName = target.name;
    }
    const stamp = team.optimalLineup;
    annotate(
      testInfo,
      "team-under-test",
      `${team.name} · slotSource=${stamp.slotSource} · ` +
        `${(stamp.assignments || []).length} assignments · ` +
        `${(stamp.unpriced || []).length} unpriced`,
    );

    // ── The portfolio panel, rendered from that stamp ────────────────
    const panel = page.locator(".panel--portfolio");
    await expect(panel).toBeVisible({ timeout: 60_000 });
    const startersList = panel.locator(".portfolio-starters li");
    await expect(startersList.first(), "starters list should render").toBeVisible({
      timeout: 60_000,
    });

    // Truth-ladder disclosure: with the live-rosterPositions rung the
    // note must be ABSENT (the split is a measurement, not a guess).
    if (stamp.slotSource === "sleeper_roster_positions") {
      await expect(
        panel.locator(".portfolio-lineup-note"),
        "stamp is from live rosterPositions but the panel renders a fallback note",
      ).toHaveCount(0);
    } else {
      annotate(
        testInfo,
        "lineup-note",
        `slotSource=${stamp.slotSource} — note expected: ` +
          (await panel.locator(".portfolio-lineup-note").allInnerTexts()).join(" "),
      );
    }

    // ── Starter set equality, by (slot, name) in slot order ──────────
    const renderedSlots = await panel
      .locator(".portfolio-starters li .portfolio-starter-pos")
      .allInnerTexts();
    const renderedNames = await panel
      .locator(".portfolio-starters li .portfolio-starter-name")
      .allInnerTexts();
    const stampAssignments = stamp.assignments || [];

    expect(
      renderedSlots.length,
      `rendered starter count (${renderedSlots.length}) != stamped assignment count ` +
        `(${stampAssignments.length}). Stamped: ${stampAssignments
          .map((a) => `${a.slot}:${a.player}`)
          .join(", ")} · Rendered: ${renderedSlots
          .map((s, i) => `${s}:${renderedNames[i]}`)
          .join(", ")}. A shortfall usually means a starter's board display ` +
        "name failed to join the Sleeper roster spelling — a real render-vs-stamp gap either way.",
    ).toBe(stampAssignments.length);

    expect(
      renderedSlots.map((s) => s.trim()),
      "rendered slot sequence must be the stamp's own assignment order",
    ).toEqual(stampAssignments.map((a) => String(a.slot)));

    const looseMatches = [];
    const mismatches = [];
    stampAssignments.forEach((a, i) => {
      const verdict = namesMatch(renderedNames[i], a.player);
      if (verdict === "loose") {
        looseMatches.push(`${a.slot}: "${renderedNames[i]}" ~ "${a.player}"`);
      } else if (!verdict) {
        mismatches.push(
          `${a.slot}: rendered "${renderedNames[i]}" vs stamped "${a.player}"`,
        );
      }
    });
    expect(
      mismatches,
      "rendered starters disagree with the stamp by player",
    ).toEqual([]);
    annotate(
      testInfo,
      "name-joins",
      looseMatches.length
        ? `loose display-name matches (board vs Sleeper spelling): ${looseMatches.join("; ")}`
        : "every rendered starter name matched the stamp exactly (normalized)",
    );

    // ── Split legend: counts are the stamp's, unpriced excluded ──────
    const legendSpans = panel.locator(".portfolio-split-legend > span");
    const starterLegend = await legendSpans
      .filter({ hasText: /Starters/ })
      .innerText();
    const benchLegend = await legendSpans
      .filter({ hasText: /Bench/ })
      .innerText();
    const starterCount = trailingCount(starterLegend);
    const benchCount = trailingCount(benchLegend);
    expect(
      starterCount,
      `legend starter count (${starterCount}) != stamped starters (${(stamp.starters || []).length})`,
    ).toBe((stamp.starters || []).length);

    const unpriced = stamp.unpriced || [];
    const rosterSize = (team.players || []).length;
    // Unpriced players are a THIRD state: in neither list. Bench can be
    // at most roster − starters − unpriced (unresolved names shrink it
    // further, hence ≤, never ==).
    expect(
      benchCount,
      `bench count (${benchCount}) can only hold roster (${rosterSize}) − ` +
        `starters (${starterCount}) − unpriced (${unpriced.length}) — a larger ` +
        "bench means unpriced players were silently benched",
    ).toBeLessThanOrEqual(rosterSize - starterCount - unpriced.length);
    if (unpriced.length > 0) {
      const renderedNorm = new Set(renderedNames.map(normName));
      for (const name of unpriced) {
        expect(
          renderedNorm.has(normName(name)),
          `stamped-unpriced player "${name}" is rendered as a starter`,
        ).toBe(false);
      }
      annotate(
        testInfo,
        "unpriced-state",
        `${unpriced.length} unpriced player(s) verified excluded from starters and from the bench count`,
      );
    } else {
      annotate(
        testInfo,
        "unpriced-state",
        "stamp.unpriced is empty for this team on the live board — the " +
          "exclusion arithmetic was asserted as an upper bound only; the " +
          "positive case was not exercisable and is not faked",
      );
    }
  });

  test("/rosters 'Starters only' scope is stamped-lineup-driven, with an honest unavailable state", async ({
    prodPage: page,
  }, testInfo) => {
    desktopOnly(test, testInfo);
    await blockUserStateWrites(page);

    const { status, body: contract } = await getJson(page, "/api/data?view=app");
    expect(status).toBe(200);
    const teams = contract?.sleeper?.teams || [];
    expect(teams.length).toBeGreaterThan(0);
    const allStamped = teams.every((t) => t?.optimalLineup?.available === true);
    annotate(
      testInfo,
      "stamp-census",
      `${teams.filter((t) => t?.optimalLineup?.available === true).length}/${teams.length} stamped available`,
    );

    await page.goto(prodUrl("/rosters"), { waitUntil: "domcontentloaded" });
    await expect(
      page.getByRole("heading", { level: 1, name: /^Team Strength$/ }),
    ).toBeVisible({ timeout: 90_000 });

    await page.selectOption(
      'select[aria-label="Assets counted in team totals"]',
      "starters",
    );

    // Every team still renders a portfolio row under the starters scope.
    const rows = page.locator(".roster-portfolio-table tbody tr");
    await expect
      .poll(() => rows.count(), {
        message: `starters-scope portfolio should render one row per team (${teams.length})`,
        timeout: 60_000,
      })
      .toBeGreaterThanOrEqual(teams.length);

    const note = page.locator(".starter-slots-unavailable");
    if (allStamped) {
      await expect(
        note,
        "every team carries an available stamp, yet the page claims starter totals are unavailable",
      ).toHaveCount(0);
      annotate(
        testInfo,
        "state-observed",
        "all stamps available → starter totals rendered, no unavailable note",
      );
    } else {
      await expect(
        note,
        "a team's stamp is missing but the page renders starter totals as if measured",
      ).toBeVisible();
      annotate(
        testInfo,
        "state-observed",
        "missing stamp(s) → explicit 'Starter totals unavailable' note rendered",
      );
    }
  });
});

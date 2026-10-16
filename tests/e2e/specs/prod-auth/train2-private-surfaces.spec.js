/**
 * Release train 2 (merge bc51e7e2d) — the private surfaces it shipped, verified
 * on the DEPLOYED site with the workflow's ephemeral guest session.
 *
 * Each test asserts the shipped CONTRACT SHAPE and the HONEST STATES of one
 * surface — what the owner records as the row's acceptance — never a specific
 * number that depends on which sources answered the last scrape:
 *
 *   surface                                   ledger rows
 *   ─────────────────────────────────────────  ─────────────────────────────
 *   GET /api/model-lab, /api/model-lab/{fam}  AL-0b (admin gate only — the
 *     → 403 admin_required for a guest         Lab's CONTENT needs an admin
 *                                              and stays unverified here)
 *   GET/PUT /api/user/trade-protections       C3-CON-02
 *   GET /api/players/{p}/value-movement       UI-contract§10/value-movement
 *     + the Player File "Why it moved"          (IC-7)
 *     disclosure (lazy: no fetch until opened)
 *   GET /api/roster/intelligence (core)        C2-CORE-01
 *   /waivers Droppable ← cut ladder            C2-DROP-01
 *   /rosters Trade Targets ← team.weakness     C2-WEAK-01 (consumer half)
 *   GET /api/ros/pick-projections              PICK-PROJECTOR-1652 / #1652 /
 *                                              C1-PICK-03
 *   GET /api/signals/reconciled                C6-SIG-01
 *   GET /api/league/player-impact              C5-WAR-01
 *
 * Every observed branch is ANNOTATED (helpers.js::annotate → the JSON report
 * the workflow uploads), so the run says which state production produced
 * rather than leaving it to be inferred from a green tick.
 *
 * READ-ONLY, structurally:
 *   - every API call is a GET, except ONE PUT to /api/user/trade-protections
 *     that is (a) sent only after /api/auth/status proves the session is a
 *     guest pass (authMethod "guest_pass", isAdmin false), whose PUT the
 *     server refuses with 403 before reading the body, and (b) carries a body
 *     the server would itself REJECT (an unknown field → 400 invalid_body)
 *     if the guest gate ever regressed — so no outcome of this request can
 *     write user_kv;
 *   - the browser tests route EVERY /api/** request and fail closed: a GET
 *     goes through; a non-GET reaches production only if it is one of the
 *     pure computation endpoints in COMPUTE_ONLY_POSTS; PUT /api/user/state
 *     (useLeague persists a league switch there) is answered locally and
 *     never forwarded; anything else is ABORTED and fails the test. (The
 *     TeamSwitcher itself writes localStorage through useSettings, not the
 *     server.)
 *   - failure messages carry counts and ids only — never a roster name next
 *     to a value (the report is published from a public repo).
 *   - no form is submitted, nothing is saved.
 *
 * Desktop-only checks carry the `@desktop-only` title tag, which the
 * prod-mobile project filters out with `grepInvert` (prod-auth.config.js)
 * instead of collecting-then-skipping them: an API contract read at 390px
 * proves nothing more, and a skip would inflate the suite's skip count.
 */
const { test, expect, prodUrl, getJson, annotate, normName } = require("./helpers");

// ── shared, read-once inputs ──────────────────────────────────────────────

/**
 * The full contract minus the legacy players dict, read ONCE per worker:
 * the prod-auth config runs one worker, sequentially, so every test in this
 * file shares it. A worker restart (after a failure) simply re-reads it.
 */
let boardCache = null;

async function loadBoard(page) {
  if (boardCache) return boardCache;
  const { status, body } = await getJson(page, "/api/data?view=array", { timeoutMs: 120_000 });
  expect(status, "/api/data?view=array must serve the session").toBe(200);
  const rows = Array.isArray(body?.playersArray) ? body.playersArray : [];
  const ranked = rows
    .filter(
      (r) =>
        r &&
        r.assetClass !== "pick" &&
        r.playerId &&
        Number.isInteger(r.canonicalConsensusRank) &&
        Number(r.rankDerivedValue) > 0,
    )
    .sort((a, b) => a.canonicalConsensusRank - b.canonicalConsensusRank);
  expect(ranked.length, "the board carries no ranked, id-keyed players to verify against").toBeGreaterThan(0);
  const allTeams = (body?.sleeper?.teams || []).filter((t) => t && typeof t === "object");
  boardCache = {
    leagueKey: body?.meta?.leagueKey || null,
    top: ranked[0],
    // Every roster, orphans included: roster intelligence keys an orphan
    // (no ownerId) positionally, so league-wide counts compare against this.
    allTeams,
    // Teams a request can name by ownerId.
    teams: allTeams.filter((t) => t.ownerId),
  };
  return boardCache;
}

/** The session's own description of itself — the precondition for every
 *  guest-only assertion below. Never logs the cookie. */
async function sessionIdentity(page) {
  const { status, body } = await getJson(page, "/api/auth/status");
  expect(status, "/api/auth/status must answer").toBe(200);
  return {
    authMethod: body?.authMethod ?? null,
    isAdmin: body?.isAdmin === true,
    username: body?.username ?? null,
  };
}

function header(res, name) {
  return String(res.headers()[name.toLowerCase()] || "");
}

/** Non-GET endpoints a page may send to production: pure computations that
 *  mutate no league or user state. Anything else is refused. */
const COMPUTE_ONLY_POSTS = new Set([
  "POST /api/waiver/suggestions",
  "POST /api/waiver/best-available-idp",
  "POST /api/waiver/faab-recommend",
  "POST /api/rankings/overrides",
]);
/** Non-GETs answered locally and never forwarded (a league switch is
 *  persisted through it by useLeague). */
const ANSWERED_LOCALLY = new Set(["PUT /api/user/state"]);

/**
 * Route every /api/** request of the page and FAIL CLOSED: GET/HEAD pass,
 * COMPUTE_ONLY_POSTS pass, ANSWERED_LOCALLY never reaches production, and
 * every other non-GET is aborted and recorded. Returns the list the test
 * asserts empty at the end.
 */
async function guardWrites(page) {
  const refused = [];
  await page.route("**/api/**", (route) => {
    const req = route.request();
    const method = req.method();
    if (method === "GET" || method === "HEAD") return route.continue();
    const sig = `${method} ${new URL(req.url()).pathname}`;
    if (COMPUTE_ONLY_POSTS.has(sig)) return route.continue();
    if (ANSWERED_LOCALLY.has(sig)) {
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
    }
    refused.push(sig);
    return route.abort();
  });
  return refused;
}

/** Pick a real league team through the deployed TeamSwitcher (the guest pass
 *  carries no Sleeper identity, so team-scoped panels start teamless). */
async function selectFirstTeam(page, testInfo) {
  const toggle = page.locator("button.team-switcher-toggle:visible").first();
  await expect(toggle, "the shell must expose the TeamSwitcher").toBeVisible({ timeout: 60_000 });
  await toggle.click();
  const option = page.locator(".team-switcher-menu:visible .team-switcher-option").first();
  await expect(option, "the TeamSwitcher opened with no league teams").toBeVisible({ timeout: 30_000 });
  const name = (await option.locator(".team-switcher-option-name").innerText()).trim();
  await option.click();
  annotate(testInfo, "team-selected", String(Boolean(name)));
  return name;
}

/**
 * Every GET /api/roster/intelligence response the page makes, in order. A
 * guest's shared user state can preselect a team before the switcher is
 * touched, so "the first response" is not necessarily the selected team's —
 * callers pick the one whose ``team`` matches the team they selected.
 */
function collectRosterIntelligence(page) {
  const seen = [];
  page.on("response", (r) => {
    if (r.request().method() !== "GET" || !r.url().includes("/api/roster/intelligence")) return;
    seen.push(r);
  });
  return seen;
}

/** The selected team's own roster-intelligence response (latest one). */
async function responseForTeam(seen, ownerId, { droppability = false } = {}) {
  const match = () =>
    [...seen].reverse().find((r) => {
      const q = new URL(r.url()).searchParams;
      return q.get("team") === String(ownerId) && (!droppability || q.get("droppability") === "1");
    }) || null;
  await expect
    .poll(() => Boolean(match()), {
      message: `no /api/roster/intelligence request for the selected team (ownerId ${ownerId})`,
      timeout: 120_000,
    })
    .toBe(true);
  return match();
}

function ownerIdForName(board, name) {
  const want = String(name || "").trim().toLowerCase();
  const team = board.teams.find((t) => String(t.name || "").trim().toLowerCase() === want);
  expect(team, `the selected team "${name}" is not a team in the contract`).toBeTruthy();
  return String(team.ownerId);
}

const RECONCILED_PLAYER_STATES = new Set([
  "withheld",
  "conflict",
  "directional_buy_only",
  "directional_sell_only",
  "no_directional_signal",
]);
const RECONCILED_EMITTER_STATES = new Set(["observed", "unobserved", "restatement", "out_of_scope"]);
const MOVEMENT_STATUSES = new Set(["ok", "no_current_generation", "no_comparator", "unkeyed"]);
const MOVEMENT_SOURCE_STATUSES = new Set(["moved", "unchanged", "appeared", "disappeared"]);
const MOVEMENT_ROLES = new Set(["model_input", "benchmark_not_a_vote", "held_from_voting"]);
const PICK_SLOT_SOURCE = "season_simulation";
const NO_DRAFT_ORDER_RULE = "no_draft_order_rule_for_league";

// ── AL-0b: Model Lab is admin-only ───────────────────────────────────────

test.describe("Train 2: Model Lab admin gate (AL-0b)", () => {
  test("@desktop-only a guest session is refused the Lab and every family with 403", async ({
    prodPage: page,
  }, testInfo) => {
    const who = await sessionIdentity(page);
    annotate(testInfo, "session-auth-method", String(who.authMethod));
    annotate(testInfo, "session-is-admin", String(who.isAdmin === true));
    expect(
      who.isAdmin,
      "this check asserts the NON-admin gate; the workflow's session must be a guest pass",
    ).toBe(false);

    for (const path of ["/api/model-lab", "/api/model-lab/hill_curves"]) {
      const res = await page.request.get(prodUrl(path), { timeout: 45_000 });
      const body = await res.json().catch(() => null);
      annotate(testInfo, "model-lab-status", String(res.status()));
      annotate(testInfo, "model-lab-error", String(body?.error ?? "none"));
      expect(res.status(), `${path} must refuse a non-admin session`).toBe(403);
      expect(body?.error, `${path} must name the refusal`).toBe("admin_required");
      // A refusal body is never cached by a shared proxy either.
      expect(header(res, "cache-control"), `${path} refusal must be no-store`).toContain("no-store");
      // The 403 is the whole answer: no Lab payload leaks alongside it.
      expect(body && ("families" in body || "family" in body), `${path} leaked Lab content`).toBeFalsy();
    }
    // Model Lab CONTENT (families, receipts, AL-4a/AL-3b scorecards) needs an
    // admin session and is not exercised here.
    annotate(testInfo, "admin-content-exercised", "false");
  });
});

// ── C3-CON-02: persistent trade protections ──────────────────────────────

test.describe("Train 2: trade protections (C3-CON-02)", () => {
  test("@desktop-only GET serves the per-league shape; a guest PUT is refused 403 and writes nothing", async ({
    prodPage: page,
  }, testInfo) => {
    const board = await loadBoard(page);
    expect(board.leagueKey, "the contract must stamp meta.leagueKey").toBeTruthy();
    const qs = `?leagueKey=${encodeURIComponent(board.leagueKey)}`;

    // Per-league by construction: no leagueKey is a named 400, not a default.
    const noKey = await getJson(page, "/api/user/trade-protections");
    expect(noKey.status, "trade protections without a leagueKey").toBe(400);
    expect(noKey.body?.error).toBe("league_key_required");

    const res = await page.request.get(prodUrl(`/api/user/trade-protections${qs}`), { timeout: 45_000 });
    expect(res.status(), "GET trade protections must serve the session").toBe(200);
    expect(header(res, "cache-control")).toContain("no-store");
    const body = await res.json();
    expect(body.leagueKey).toBe(board.leagueKey);
    expect(typeof body.configured, "configured is a boolean").toBe("boolean");
    expect(Array.isArray(body.untouchables), "untouchables is a list").toBe(true);
    expect(Array.isArray(body.nflTeams), "nflTeams is a list").toBe(true);
    // ``null`` = no board to validate against (unknown), never an empty list
    // pretending there are no NFL teams.
    expect(
      body.nflTeamOptions === null || (Array.isArray(body.nflTeamOptions) && body.nflTeamOptions.length > 0),
      "nflTeamOptions is null (no board) or a non-empty vocabulary",
    ).toBe(true);
    expect(
      body.unresolvedUntouchables === null || Array.isArray(body.unresolvedUntouchables),
      "unresolvedUntouchables is null (no board) or a list",
    ).toBe(true);
    if (!body.configured) {
      expect(body.untouchables, "an unconfigured league stores no untouchables").toEqual([]);
      expect(body.nflTeams, "an unconfigured league stores no NFL teams").toEqual([]);
    }
    annotate(testInfo, "trade-protections-configured", String(body.configured === true));

    // ── The guest write refusal. Precondition FIRST: only a proven guest-pass
    // session may send this PUT at all.
    const who = await sessionIdentity(page);
    annotate(testInfo, "session-auth-method", String(who.authMethod));
    annotate(testInfo, "session-is-admin", String(who.isAdmin === true));
    expect(
      who.authMethod,
      "refusing to send the protections PUT from a session that is not a guest pass",
    ).toBe("guest_pass");
    expect(who.isAdmin).toBe(false);

    const put = await page.request.put(prodUrl(`/api/user/trade-protections${qs}`), {
      // An unknown field: even with the guest gate gone this would be a 400
      // invalid_body, never a write.
      data: { leagueKey: board.leagueKey, prodVerificationNeverWrites: true },
      timeout: 45_000,
    });
    const putBody = await put.json().catch(() => null);
    annotate(testInfo, "trade-protections-put-status", String(put.status()));
    annotate(testInfo, "trade-protections-put-error", String(putBody?.error ?? "none"));
    expect(put.status(), "a guest-pass PUT must be refused").toBe(403);
    expect(putBody?.error).toBe("guest_read_only");

    // And it changed nothing: the read after equals the read before.
    const after = await getJson(page, `/api/user/trade-protections${qs}`);
    expect(after.status).toBe(200);
    expect(after.body?.untouchables).toEqual(body.untouchables);
    expect(after.body?.nflTeams).toEqual(body.nflTeams);
    expect(after.body?.configured).toBe(body.configured);
  });
});

// ── IC-7: "Why it moved" ─────────────────────────────────────────────────

test.describe("Train 2: value movement (UI-contract §10 / IC-7)", () => {
  test("@desktop-only the endpoint is non-additive evidence with honest absences", async ({
    prodPage: page,
  }, testInfo) => {
    const board = await loadBoard(page);
    const pid = String(board.top.playerId);

    const missing = await getJson(page, "/api/players/prod-verify-no-such-player-000/value-movement");
    expect(missing.status, "an unknown player is a named 404, not an empty movement").toBe(404);
    expect(missing.body?.error).toBe("player_not_found");

    const res = await page.request.get(prodUrl(`/api/players/${encodeURIComponent(pid)}/value-movement`), {
      timeout: 60_000,
    });
    expect(res.status(), "value-movement must serve the session").toBe(200);
    expect(header(res, "cache-control")).toContain("no-store");
    const m = await res.json();

    expect(m.schema).toBe("value-movement/v1");
    expect(m.additive, "movement evidence is never additive").toBe(false);
    expect(m.evidenceNotCause, "movement is evidence, not an asserted cause").toBe(true);
    expect(typeof m.nonAdditiveNote === "string" && m.nonAdditiveNote.length > 0).toBe(true);
    expect(MOVEMENT_STATUSES.has(m.status), `unknown movement status ${m.status}`).toBe(true);
    expect(String(m.playerId)).toBe(pid);
    // The live board the reader is looking at travels with the answer.
    expect(m.liveBoard && typeof m.liveBoard === "object", "liveBoard block").toBe(true);
    expect(m.currentContext?.scope).toBe("current_board_only");
    // Public artifact (security S3): the movement STATUS only — never the
    // player, rank or values.
    annotate(testInfo, "value-movement-status", String(m.status));

    if (m.status === "unkeyed") return;
    // What the ledger does not store is NAMED, never re-derived.
    const unobserved = (m.unobserved || []).map((u) => u.quantity);
    for (const q of ["sourceWeights", "sourceFreshness", "voteState"]) {
      expect(unobserved, `${q} must be listed as unobserved`).toContain(q);
    }
    if (m.status !== "ok") {
      expect(m.missingReason, "a non-ok movement names its reason").toBeTruthy();
      expect(m.change, "no change is computed without both ends").toBeNull();
      return;
    }

    expect(m.current && m.previous, "an ok movement carries both ends").toBeTruthy();
    expect(typeof m.rankChangeAlignment?.sameBoardsAsRankChange).toBe("boolean");
    let moved = 0;
    for (const s of m.sources || []) {
      expect(MOVEMENT_SOURCE_STATUSES.has(s.status), `source ${s.source} status ${s.status}`).toBe(true);
      expect(MOVEMENT_ROLES.has(s.role), `source ${s.source} role ${s.role}`).toBe(true);
      // Absent at one end is "appeared/disappeared" with NO delta — never 0.
      if (s.status === "appeared" || s.status === "disappeared") {
        expect(s.delta, `${s.source} ${s.status}: absent is not zero`).toBeNull();
      } else {
        expect(typeof s.delta, `${s.source} ${s.status} carries a numeric delta`).toBe("number");
        if (s.status === "unchanged") expect(s.delta).toBe(0);
        else moved += 1;
      }
      // Non-additive by construction: no source carries a share of the move.
      for (const k of Object.keys(s)) {
        expect(/share|contribution|attribut/i.test(k), `source ${s.source} carries "${k}"`).toBe(false);
      }
    }
    annotate(testInfo, "value-movement-sources-recorded", String((m.sources || []).length));
    annotate(testInfo, "value-movement-sources-moved", String(moved));
    annotate(
      testInfo,
      "value-movement-sources-not-observed",
      String((m.sourcesNotObservedAtEitherGeneration || []).length),
    );
  });

  test("the Player File 'Why it moved' disclosure fetches only when opened and renders the evidence", async ({
    prodPage: page,
  }, testInfo) => {
    const unexpectedWrites = await guardWrites(page);
    const board = await loadBoard(page);
    const pid = String(board.top.playerId);
    const movementRequests = [];
    page.on("request", (req) => {
      if (req.url().includes("/value-movement")) movementRequests.push(req.url());
    });

    await page.goto(prodUrl(`/players/${encodeURIComponent(pid)}`), { waitUntil: "domcontentloaded" });
    const disclosure = page.getByRole("button", { name: "Why it moved", exact: true });
    await expect(disclosure, "the Player File must offer the 'Why it moved' disclosure").toBeVisible({
      timeout: 120_000,
    });
    await expect(disclosure, "the disclosure starts collapsed").toHaveAttribute("aria-expanded", "false");
    // Let the page settle; a collapsed disclosure must not have fetched.
    await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
    expect(movementRequests, "value-movement was fetched before the disclosure was opened").toEqual([]);

    const responsePromise = page.waitForResponse(
      (r) => r.url().includes("/value-movement") && r.request().method() === "GET",
      { timeout: 60_000 },
    );
    await disclosure.scrollIntoViewIfNeeded();
    await disclosure.click();
    await expect(disclosure).toHaveAttribute("aria-expanded", "true");
    const response = await responsePromise;
    expect(response.status(), "the disclosure's own fetch must succeed for the session").toBe(200);
    const payload = await response.json();
    expect(payload.additive).toBe(false);

    // useId() ids contain ":" — address the body by attribute, not "#id".
    const body = page.locator(`[id="${await disclosure.getAttribute("aria-controls")}"]`);
    await expect(body.getByText("Evidence, not a cause.", { exact: false })).toBeVisible({ timeout: 30_000 });
    if (payload.status === "ok") {
      await expect(body.getByRole("heading", { name: "Between boards" })).toBeVisible();
      await expect(body.getByRole("heading", { name: /Source evidence/ })).toBeVisible();
      await expect(body.getByText("(not additive)", { exact: true })).toBeVisible();
      await expect(body.getByRole("heading", { name: "Not recorded per board" })).toBeVisible();
    } else {
      // A non-ok movement renders its honest state, never an empty table.
      await expect(body.getByRole("heading", { name: "Between boards" })).toHaveCount(0);
    }
    annotate(testInfo, "why-it-moved-status", String(payload.status));
    annotate(testInfo, "why-it-moved-fetches", String(movementRequests.length));
    expect(unexpectedWrites, "the Player File attempted a non-allowlisted write").toEqual([]);
  });
});

// ── C2-CORE-01: meaningful core via roster intelligence ──────────────────

test.describe("Train 2: roster intelligence core (C2-CORE-01)", () => {
  test("@desktop-only one team's core: starters/reserves from the solve, unpriced kept separate", async ({
    prodPage: page,
  }, testInfo) => {
    const board = await loadBoard(page);
    expect(board.teams.length, "the contract carries no Sleeper teams").toBeGreaterThan(0);
    const team = board.teams[0];
    const qs = `?leagueKey=${encodeURIComponent(board.leagueKey)}&team=${encodeURIComponent(team.ownerId)}`;
    const res = await page.request.get(prodUrl(`/api/roster/intelligence${qs}`), { timeout: 60_000 });
    expect(res.status(), "roster intelligence must serve the session").toBe(200);
    expect(header(res, "cache-control")).toContain("no-store");
    const ri = await res.json();
    expect(ri.droppabilityIncluded, "droppability was not requested and must say so").toBe(false);
    expect(String(ri.team?.ownerId)).toBe(String(team.ownerId));
    const core = ri.team?.core;
    expect(core && typeof core.available === "boolean", "team.core.available").toBe(true);
    if (!core.available) {
      expect(core.unavailableReason, "an unavailable core names why").toBeTruthy();
      expect(core.members, "an unavailable core lists no members").toEqual([]);
      annotate(testInfo, "core-state", "unavailable");
      annotate(testInfo, "core-unavailable-reason", String(core.unavailableReason));
      return;
    }
    const starters = core.members.filter((m) => m.role === "starter");
    const reserves = core.members.filter((m) => m.role === "reserve");
    expect(starters.length + reserves.length, "every core member is a starter or a reserve").toBe(
      core.members.length,
    );
    expect(core.starterCount).toBe(starters.length);
    expect(core.reserveCount).toBe(reserves.length);
    expect(starters.length, "a priced roster has starters").toBeGreaterThan(0);
    // The third state: unpriced players are reported, never in the core and
    // never scored as zero.
    const unpriced = new Set(core.unpricedIds || []);
    for (const m of core.members) {
      // Ids only in messages: no roster name next to a value is ever published.
      expect(unpriced.has(m.playerId), `core member ${m.playerId} is also unpriced`).toBe(false);
      expect(Number.isFinite(m.value) && m.value > 0, `core member ${m.playerId} has no positive value`).toBe(true);
    }
    expect(Array.isArray(core.unfilledStarterSlots)).toBe(true);
    // Every league team is ranked in the context block.
    expect(
      Array.isArray(ri.leagueContext) && ri.leagueContext.length,
      "every roster in the league (orphans included) is ranked in leagueContext",
    ).toBe(board.allTeams.length);
    // Public artifact (security S3): never the team, nor its roster counts.
    annotate(testInfo, "core-state", "available");
    annotate(testInfo, "core-slot-source", String(core.slotSource));
  });
});

// ── C2-DROP-01: /waivers Droppable is the cut ladder ─────────────────────

test.describe("Train 2: /waivers Droppable consumes the canonical cut ladder (C2-DROP-01)", () => {
  test("@desktop-only every Droppable row is a ladder rung, in cut order; undroppable players never appear", async ({
    prodPage: page,
  }, testInfo) => {
    test.setTimeout(240_000);
    const unexpectedWrites = await guardWrites(page);
    const board = await loadBoard(page);
    const seen = collectRosterIntelligence(page);
    await page.goto(prodUrl("/waivers"), { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { level: 1, name: /^Waivers$/ })).toBeVisible({ timeout: 90_000 });
    const teamName = await selectFirstTeam(page, testInfo);
    const ownerId = ownerIdForName(board, teamName);

    const ladderRes = await responseForTeam(seen, ownerId, { droppability: true });
    expect(ladderRes.status(), "the page's own cut-ladder fetch must succeed").toBe(200);
    const ri = await ladderRes.json();
    expect(ri.droppabilityIncluded).toBe(true);
    expect(String(ri.team?.ownerId)).toBe(ownerId);
    const drop = ri.team?.droppability;
    expect(drop?.owner, "the ladder comes from its canonical owner").toBe("src/draft/displacement.py");
    const rungs = drop?.cutLadder?.rungs || [];
    const undroppable = drop?.cutLadder?.undroppable || [];
    rungs.forEach((r, i) => expect(r.rung, "rungs are numbered 1..n in cut order").toBe(i + 1));
    for (const r of rungs) {
      // An unpriced player is costed at waiver level and SAYS so — never 0.
      if (r.valueBasis === "assumedWaiver") expect(r.baseValue).toBe(r.waiverValue);
    }
    const rungByNumber = new Map(rungs.map((r) => [r.rung, r]));
    const undroppableNames = undroppable
      .map((u) => normName(u?.name || u?.canonicalName || ""))
      .filter(Boolean);

    const table = page.locator("table").filter({
      has: page.locator("caption", { hasText: "Legal releases beaten by the available pool, in cut order" }),
    });
    // DataTable renders its emptyState INSTEAD of the table, so the panel
    // shows exactly one of the two.
    const emptyTitle = page.getByText("No drop candidates", { exact: true });
    await expect(
      table.or(emptyTitle),
      "the Droppable panel must render its rows or its stated empty state",
    ).toHaveCount(1, { timeout: 60_000 });
    // Let the analysis settle (it gates on the ladder + the board).
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    const rendered = table.locator("tbody tr").filter({ has: page.locator('td[data-col="player"]') });
    const n = await rendered.count();
    const seenRungs = [];
    for (let i = 0; i < n; i += 1) {
      const row = rendered.nth(i);
      const cell = normName(await row.locator('td[data-col="player"]').innerText());
      const rungText = (await row.locator('td[data-col="rung"]').innerText()).trim();
      const rung = rungByNumber.get(Number(rungText));
      expect(rung, `Droppable row ${i + 1} shows cut "${rungText}", which is not a rung of the canonical ladder`).toBeTruthy();
      expect(
        cell.includes(normName(rung.name)),
        `Droppable row ${i + 1} (cut ${rung.rung}) does not show the ladder's player (id ${rung.playerId})`,
      ).toBe(true);
      expect(
        undroppableNames.some((u) => cell.includes(u)),
        `Droppable row ${i + 1} shows a player the ladder marks undroppable`,
      ).toBe(false);
      seenRungs.push(rung.rung);
    }
    expect([...seenRungs].sort((a, b) => a - b), "Droppable rows are in cut order").toEqual(seenRungs);
    expect(new Set(seenRungs).size, "no ladder rung is offered twice").toBe(seenRungs.length);
    // The ladder loaded (asserted above), so the page must not claim it could
    // not be read — in either branch.
    await expect(page.getByText("Drop candidates unavailable", { exact: true })).toHaveCount(0);
    await expect(page.getByText("No drop candidates shown", { exact: true })).toHaveCount(0);
    if (n === 0) {
      // Empty is stated with the ladder-OK title, never a silent blank.
      await expect(emptyTitle, "an empty Droppable list must say so with the ladder-OK title").toBeVisible();
    }
    annotate(testInfo, "droppable-rows-match-ladder", "true");
    expect(unexpectedWrites, "/waivers attempted a non-allowlisted write").toEqual([]);
  });
});

// ── C2-WEAK-01: /rosters Trade Targets read the served need ──────────────

test.describe("Train 2: /rosters Trade Targets consume team.weakness (C2-WEAK-01)", () => {
  test("@desktop-only the Top-need badge is the served weakness order, or the card says it is unavailable", async ({
    prodPage: page,
  }, testInfo) => {
    test.setTimeout(240_000);
    const unexpectedWrites = await guardWrites(page);
    const board = await loadBoard(page);
    const seen = collectRosterIntelligence(page);
    await page.goto(prodUrl("/rosters"), { waitUntil: "domcontentloaded" });
    const teamName = await selectFirstTeam(page, testInfo);
    const intelRes = await responseForTeam(seen, ownerIdForName(board, teamName));
    const card = page.locator(".trade-targets-card");
    await expect(card, "the Trade Targets card must render for a selected team").toBeVisible({
      timeout: 90_000,
    });
    await expect(card.getByText("Loading need priority…")).toHaveCount(0, { timeout: 60_000 });

    if (intelRes.status() !== 200) {
      await expect(card.locator(".trade-targets-unavailable")).toBeVisible();
      annotate(testInfo, "trade-targets-state", "intel_unavailable");
      expect(unexpectedWrites).toEqual([]);
      return;
    }
    const ri = await intelRes.json();
    const weakness = ri.team?.weakness;
    if (!weakness || weakness.available === false) {
      await expect(card.locator(".trade-targets-unavailable"), "an unmeasured need must be stated").toBeVisible();
      annotate(testInfo, "trade-targets-state", "weakness_unavailable");
    } else {
      const needs = (weakness.needs || []).filter((x) => x && x.position && x.level && x.level !== "none");
      const badge = card.locator(".trade-targets-top-need");
      await expect(badge).toBeVisible();
      if (needs.length) {
        await expect(badge, "the Top-need badge must be the served worst-first need").toContainText(
          `Top need: ${needs[0].position}`,
        );
        // At most the top two needs are listed, in the served order.
        const sections = card.locator(".trade-targets-need h4");
        const shown = await sections.allInnerTexts();
        const expected = needs.slice(0, 2).map((x) => `Need: ${x.position}`);
        expect(shown.map((s) => s.split(/\s+/).slice(0, 2).join(" "))).toEqual(expected);
      } else {
        await expect(badge).toHaveText("No starting-slot need");
      }
      // Never the needs themselves: a team's weaknesses are private.
      annotate(testInfo, "trade-targets-state", "needs_served");
    }
    expect(unexpectedWrites, "/rosters attempted a non-allowlisted write").toEqual([]);
  });
});

// ── #1652: Pick Projector slots come from the season simulation ──────────

test.describe("Train 2: Pick Projector (PICK-PROJECTOR-1652)", () => {
  test("@desktop-only slots are labelled season_simulation; a league with no recorded rule gets no forecast", async ({
    prodPage: page,
  }, testInfo) => {
    const { body: leaguesBody } = await getJson(page, "/api/leagues");
    const leagues = (Array.isArray(leaguesBody) ? leaguesBody : leaguesBody?.leagues || [])
      .map((l) => l?.key)
      .filter(Boolean);
    expect(leagues, "the registry must list dynasty_main").toContain("dynasty_main");

    for (const key of leagues) {
      const { status, body } = await getJson(page, `/api/ros/pick-projections?leagueKey=${encodeURIComponent(key)}`, {
        timeoutMs: 60_000,
      });
      expect(status, `pick projections for ${key}`).toBe(200);
      expect(body.leagueKey).toBe(key);
      if (body.error === "no_teams") {
        // Sleeper overlay unreachable: an explicit degraded state, no picks
        // invented. Proves the honest state only — the row stays unproven.
        expect(body.picks).toEqual([]);
        annotate(testInfo, `pick-projector-${key}-state`, "degraded_no_teams");
        continue;
      }
      const meta = body.meta || {};
      expect(meta.source, `${key}: slot source`).toBe(PICK_SLOT_SOURCE);
      const reason = meta.slotForecastUnavailableReason ?? null;
      if (key !== "dynasty_main") {
        // Only dynasty_main has an owner-recorded draft-order rule; any other
        // league fails closed rather than assuming reverse standings.
        expect(reason, `${key} has no recorded draft-order rule`).toBe(NO_DRAFT_ORDER_RULE);
        expect(meta.draftOrderRule ?? null).toBeNull();
      } else {
        expect(meta.draftOrderRule, "dynasty_main's recorded rule").toBe("reverse_record_lower_pf");
      }
      if (body.picks === null) {
        // Ownership unknown: refused, never zero picks.
        expect(body.error).toBe("pick_ownership_unavailable");
        expect(meta.pickOwnershipState).toBe("unavailable");
      } else {
        for (const p of body.picks) {
          if (p.projectedSlot === null) {
            expect(p.slotForecastUnavailableReason, `${p.label}: no slot must name why`).toBeTruthy();
            expect(p.confidence).toBeNull();
          } else {
            expect(p.projectedSlot, `${p.label}: never slot 0`).toBeGreaterThan(0);
            expect(p.projectedPickNumber).toBe((p.round - 1) * meta.teamCount + p.projectedSlot);
          }
        }
        if (reason === null) {
          expect(
            Array.isArray(body.projectedOrder) && body.projectedOrder.length > 0,
            `${key}: a forecast with no unavailable reason must carry the projected order`,
          ).toBe(true);
        }
      }
      annotate(testInfo, `pick-projector-${key}-state`, "served");
      annotate(testInfo, `pick-projector-${key}-source`, String(meta.source));
      annotate(testInfo, `pick-projector-${key}-reason`, String(reason ?? "none"));
    }
  });
});

// ── C6-SIG-01: Buy/Sell reconciler ───────────────────────────────────────

test.describe("Train 2: signal reconciler (C6-SIG-01)", () => {
  test("@desktop-only verdicts are deduped and labelled per emitter, never blended", async ({
    prodPage: page,
  }, testInfo) => {
    const board = await loadBoard(page);
    const team = board.teams[0];
    const qs =
      `?leagueKey=${encodeURIComponent(board.leagueKey)}&scope=roster` +
      `&team=${encodeURIComponent(team.ownerId)}`;
    const { status, body } = await getJson(page, `/api/signals/reconciled${qs}`, { timeoutMs: 90_000 });
    expect(status, "the reconciler must serve the session").toBe(200);

    expect(typeof body.reconcilerVersion).toBe("string");
    expect(body.method?.kind).toBe("dedup_and_lineage_only");
    expect(body.method?.numericBlend, "the reconciler never blends").toBe(false);
    expect(body.method?.crossEmitterWeights).toBe(false);
    expect(body.method?.conflictResolution).toBe("labelled_not_resolved");
    expect(body.method?.missingEmitter).toBe("unobserved_not_neutral");
    expect(body.method?.withheldPrecedence).toContain("canonical_quarantine");

    const ids = new Set();
    const byState = {};
    for (const e of body.emitters || []) {
      expect(ids.has(e.emitterId), `emitter ${e.emitterId} listed twice`).toBe(false);
      ids.add(e.emitterId);
      expect(RECONCILED_EMITTER_STATES.has(e.state), `${e.emitterId} state ${e.state}`).toBe(true);
      if (e.state === "unobserved") expect(e.reason, `${e.emitterId}: unobserved names why`).toBeTruthy();
      byState[e.state] = (byState[e.state] || 0) + 1;
    }
    expect(ids.size, "every registered emitter is reported").toBeGreaterThan(0);

    const players = body.players || [];
    expect(body.counts?.players).toBe(players.length);
    const playerStates = {};
    for (const p of players) {
      expect(RECONCILED_PLAYER_STATES.has(p.state), `${p.playerKey} state ${p.state}`).toBe(true);
      playerStates[p.state] = (playerStates[p.state] || 0) + 1;
      // Categorical only: no blended magnitude at the player level.
      for (const k of Object.keys(p)) {
        expect(/score|blend|weight|average|composite/i.test(k), `${p.playerKey} carries "${k}"`).toBe(false);
      }
      if (p.state === "conflict") {
        expect(p.conflict?.buy?.length && p.conflict?.sell?.length, "a conflict names both sides").toBeTruthy();
        expect(p.conflict?.resolution).toBe("not_resolved_by_reconciler");
      }
    }
    // Public artifact (security S3): never the team or its players' states.
    annotate(testInfo, "reconciler-emitters-reporting", String(ids.size));
  });
});

// ── C5-WAR-01: deterministic player impact ───────────────────────────────

test.describe("Train 2: player impact / WAR core (C5-WAR-01)", () => {
  test("@desktop-only season rows sum only known weeks; xWAR is unavailable, not reconstructed", async ({
    prodPage: page,
  }, testInfo) => {
    const board = await loadBoard(page);
    const { status, body } = await getJson(
      page,
      `/api/league/player-impact?leagueKey=${encodeURIComponent(board.leagueKey)}`,
      { timeoutMs: 120_000 },
    );
    if (status === 503 && body?.reason === "league_snapshot_mismatch") {
      annotate(testInfo, "player-impact-state", "league_snapshot_mismatch");
      return;
    }
    expect(status, "player impact must serve the session").toBe(200);
    expect(String(body.contractVersion || "")).toMatch(/^player-impact\//);
    expect(body.leagueKey).toBe(board.leagueKey);
    expect(body.xWar?.state, "xWAR has no archived distribution and is unavailable").toBe("unavailable");
    expect(body.scope?.playoffsIncluded).toBe(false);
    expect(["consistent", "contradicted_settings"]).toContain(body.settings?.state);
    expect(Array.isArray(body.priors) && body.priors.length, "labelled priors travel with the payload").toBeTruthy();
    expect("_records" in body, "per-week records are not published league-wide").toBe(false);

    const rows = body.players || [];
    const coverage = { complete: 0, partial: 0, unavailable: 0 };
    for (const r of rows) {
      for (const key of ["vorp", "war", "wab", "gameChangerPoints"]) {
        const b = r[key];
        expect(b, `${r.playerId} ${key} block`).toBeTruthy();
        expect(b.weeksKnown + b.weeksUnavailable, `${r.playerId} ${key} week accounting`).toBe(r.weeksRostered);
        // MISSING IS NEVER ZERO: no known week → total is null, not 0.
        if (b.weeksKnown === 0) expect(b.total, `${r.playerId} ${key} with no known week`).toBeNull();
        else expect(typeof b.total).toBe("number");
        const reasons = Object.values(b.unavailableReasons || {}).reduce((s, v) => s + v, 0);
        expect(reasons, `${r.playerId} ${key}: every unavailable week has a reason`).toBe(b.weeksUnavailable);
        coverage[b.coverage] = (coverage[b.coverage] || 0) + 1;
      }
    }
    annotate(testInfo, "player-impact-state", "served");
    annotate(testInfo, "player-impact-settings-state", String(body.settings?.state));
    annotate(testInfo, "player-impact-rows", String(rows.length));
  });
});

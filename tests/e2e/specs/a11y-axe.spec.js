/**
 * Automated accessibility scan — the instrument this repo did not have.
 *
 * WHAT WAS MISSING
 * ────────────────
 * There is no ESLint config anywhere in the tree, no `jsx-a11y`, no
 * axe-core, and no Playwright a11y scan. The ONLY a11y test was
 * `frontend/__tests__/a11y-tab-roles.test.js` — a structural guard on one
 * rule (`role="tab"` must have a real `tabpanel`), shipping a baseline of
 * seven known violations. `docs/C_SERIES_SCOPE_MANIFEST.md` records
 * `C8-A11Y-01` as PARTIAL for exactly this reason: "structural ratchet
 * exists, no axe-core".
 *
 * Everything else was unmeasured, which is not the same as clean. The
 * first run of this spec found, and this branch fixed:
 *
 *   /settings  label × 4              every numeric valuation control on
 *                                     the page was an unnamed input
 *   /settings  select-name × 3        three unnamed comboboxes
 *   /settings  aria-prohibited-attr   21 status dots carrying `aria-label`
 *              × 21                   on a bare <span>, which has no role
 *                                     to name
 *   /rosters   color-contrast × 57    white on saturated chips, down to
 *                                     2.85:1 against a 4.5:1 floor
 *   /rosters   scrollable-region-     a sideways-scrolling table with no
 *              focusable × 1          keyboard way in
 *
 * A RATCHET, NOT A GATE
 * ─────────────────────
 * `BASELINE` records what is known and not yet fixed, per route per
 * viewport. The suite fails on anything NEW, and equally on a baseline
 * entry that has become stale — because an allowance nobody re-checks is
 * how a backlog quietly grows back. That is the same posture
 * `a11y-tab-roles.test.js` and the decision-path coercion gate already
 * take; this is not a new convention.
 *
 * SCOPE
 * ─────
 * WCAG 2.0/2.1 A and AA only. Best-practice rules are deliberately out:
 * they are opinions, and mixing them in would make the ratchet argue
 * about taste instead of about conformance.
 *
 * COVERAGE (C8-A11Y-01, 2026-10-07)
 * ─────────────────────────────────
 * The first cut scanned 10 of ~52 page routes. It now scans EVERY route
 * family under `frontend/app`, and a coverage test at the bottom fails
 * when a page is added without being listed here, so the number cannot
 * quietly drift back. Dynamic routes resolve real ids from the same seeded
 * snapshot the rest of the suite uses (public league managers, rivalries,
 * matchups and players; the contract's own top-ranked player), so they
 * scan a POPULATED page rather than a not-found shell. Two families have
 * no fixture in the offline stack — a curated sharp person and an auction
 * room — and scan their honest empty / sign-in state with a probe id; the
 * entry says so, and it is never presented as a populated scan.
 * `/players/[playerId]` is additionally scanned section by section in
 * psi-rankings-player-a11y.spec.js; this is its whole-page landing.
 */
const fs = require("node:fs");
const path = require("node:path");
const { test, expect } = require("../helpers/auth-fixture");
const AxeBuilder = require("@axe-core/playwright").default;
const {
  awaitStreamSettled,
  contractFixture,
  isMobileProject,
  pageUrl,
} = require("../helpers/journey");

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

/**
 * Static routes — every page under frontend/app without a dynamic
 * segment. The first ten are the original high-use set and keep their
 * test names.
 */
const ROUTES = [
  "/",
  "/rankings",
  "/trade",
  "/waivers",
  "/rosters",
  "/trades",
  "/settings",
  "/admin",
  "/login",
  "/league",
  // C8-A11Y-01 extension — the rest of the private surface …
  "/admin/sharp-identities",
  "/angle",
  "/arbitrage",
  "/bdvm",
  "/consensus-edge",
  "/design",
  "/dfs",
  "/draft",
  "/edge",
  "/finder",
  "/game-day",
  "/idptc-rookies",
  "/intel",
  "/league-comparison",
  "/league/insider-trading",
  "/market/sharp-people",
  "/market/sharp-roster-percentage",
  "/market/sharp-tracker",
  "/more",
  "/news",
  "/phases",
  "/players/compare",
  "/tools/ros-data-health",
  "/tools/source-health",
  "/tools/trade-coverage",
  "/trending",
  // … the public league hub's own pages …
  "/league/activity",
  // … and the self-authenticating auction room (its own sign-in states).
  "/auction",
  "/auction/join",
  "/auction/notifications",
  "/auction/reset",
];

const enc = encodeURIComponent;

async function publicJson(page, apiPath) {
  const res = await page.request.get(apiPath);
  expect(res.status(), `GET ${apiPath} must serve the suite`).toBe(200);
  return res.json();
}

async function firstMatchup(page) {
  const body = await publicJson(page, "/api/public/league/matchups");
  const matchups = body?.matchups || [];
  expect(matchups.length, "public league must expose matchups").toBeGreaterThan(0);
  return matchups[0];
}

/**
 * Dynamic route families. `resolve` returns the concrete URL to scan from
 * real snapshot data, and FAILS (never skips) when data the snapshot is
 * known to carry is missing — a skipped scan reads exactly like a clean one.
 */
const DYNAMIC_ROUTES = [
  {
    family: "/rankings/[position]",
    resolve: async () => "/rankings/qb",
  },
  {
    family: "/players/[playerId]",
    resolve: async (page) => {
      // The app view strips `playersArray`; its legacy dict carries the
      // same identity as `_sleeperId` + `_canonicalConsensusRank` (the
      // fields buildRows reads). Accept either shape.
      const { contract } = await contractFixture(page);
      const rows = Array.isArray(contract.playersArray) && contract.playersArray.length
        ? contract.playersArray.map((p) => ({ id: p?.playerId, rank: p?.canonicalConsensusRank }))
        : Object.values(contract.players || {}).map((p) => ({
            id: p?._sleeperId,
            rank: p?._canonicalConsensusRank,
          }));
      const ranked = rows
        .filter((r) => r.id && Number.isFinite(Number(r.rank)))
        .sort((a, b) => Number(a.rank) - Number(b.rank));
      expect(ranked.length, "contract must carry ranked players with a Sleeper id").toBeGreaterThan(0);
      return `/players/${enc(ranked[0].id)}`;
    },
  },
  {
    family: "/league/franchise/[owner]",
    resolve: async (page) => {
      const body = await publicJson(page, "/api/public/league");
      const ownerId = body?.league?.managers?.[0]?.ownerId;
      expect(ownerId, "public league must expose managers").toBeTruthy();
      return `/league/franchise/${enc(ownerId)}`;
    },
  },
  {
    family: "/league/rivalry/[pair]",
    resolve: async (page) => {
      const body = await publicJson(page, "/api/public/league/rivalries");
      const rivalries = body?.data?.rivalries || [];
      expect(rivalries.length, "public league must expose rivalries").toBeGreaterThan(0);
      const [a, b] = rivalries[0].ownerIds;
      return `/league/rivalry/${enc(a)}-vs-${enc(b)}`;
    },
  },
  {
    family: "/league/player/[playerId]",
    resolve: async (page) => {
      const body = await publicJson(page, "/api/public/league/players");
      const named = (body?.players || []).find((p) => p.playerName && p.position);
      expect(named, "public league must expose named players").toBeTruthy();
      return `/league/player/${enc(named.playerId)}`;
    },
  },
  {
    family: "/league/weekly/[season]/[week]/[matchup]",
    resolve: async (page) => {
      const m = await firstMatchup(page);
      return `/league/weekly/${enc(m.season)}/${enc(m.week)}/${enc(m.matchupId)}`;
    },
  },
  {
    family: "/league/week/[season]/[week]",
    resolve: async (page) => {
      const m = await firstMatchup(page);
      return `/league/week/${enc(m.season)}/${enc(m.week)}`;
    },
  },
  {
    family: "/league/articles/[season]/[week]",
    resolve: async (page) => {
      const m = await firstMatchup(page);
      return `/league/articles/${enc(m.season)}/${enc(m.week)}`;
    },
  },
  {
    // Generated articles are cron output and may not be on disk in the
    // offline stack; the page then renders its own "not generated yet"
    // state, which is a real state with its own markup to scan.
    family: "/league/articles/[season]/[week]/[matchupId]/[mode]",
    resolve: async (page) => {
      const m = await firstMatchup(page);
      return `/league/articles/${enc(m.season)}/${enc(m.week)}/${enc(m.matchupId)}/recap`;
    },
  },
  {
    // No curated-sharp fixture ships offline: a real person when the
    // stack has one, otherwise the page's honest not-found state.
    family: "/market/sharp-people/[personId]",
    resolve: async (page) => {
      const res = await page.request.get("/api/sharp/people");
      const people = res.ok() ? (await res.json())?.people || [] : [];
      const id = people[0]?.person_id || "a11y-probe";
      return `/market/sharp-people/${enc(id)}`;
    },
  },
  {
    // No auction room exists offline; this scans the room's own
    // sign-in / unavailable state for an unknown room id.
    family: "/auction/[roomId]",
    resolve: async () => "/auction/a11y-probe",
  },
];

/**
 * Known, unfixed violations: `"route|viewport"` -> { ruleId: nodeCount }.
 * Dynamic families are keyed by their family pattern.
 *
 * The original ten routes stay EMPTY. The 2026-10-07 extension's first
 * scan (both projects, seeded offline stack) found, and the same change
 * FIXED in the components without any visual change:
 *
 *   /draft   label × 96                 team radios, team-name / budget
 *                                       inputs and every PreDraft price
 *                                       input were unnamed (aria-label)
 *   /league/franchise/[owner]           the sideways-scrolling Season
 *            scrollable-region-         results table had no keyboard way
 *            focusable × 1              in (tab stop + named group — the
 *                                       /rosters pattern)
 *
 * What remains below needs a VISUAL change to fix — a colour or an
 * underline — and the calculator's look is governed by the PSI design
 * contract (docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md), which this
 * a11y-coverage change is not authorised to alter. Each is a real WCAG AA
 * failure, recorded here so it is counted rather than invisible, and so a
 * fix makes the entry stale and fails the suite until it is deleted.
 * Owner: UI Lane 6 (docs/ui/UI_PARALLEL_LEDGER.md).
 */
const VISUAL_FIX_REQUIRED = {
  // 1.4.3 contrast: the rookie-count pill inside an inactive draft tag tab.
  "/draft": { "color-contrast": 1 },
  // 1.4.3 contrast: the active filter button's inline cyan on the
  // secondary button surface, once the comparison has loaded.
  "/league-comparison": { "color-contrast": 1 },
  // 1.4.3 contrast: the notification-devices table header cells.
  "/auction/notifications": { "color-contrast": 5 },
  // 1.4.1 use of colour: inline cyan links in franchise prose ("Ty",
  // "Full draft center →") are distinguished from text only by colour.
  "/league/franchise/[owner]": { "link-in-text-block": 2 },
};

const BASELINE = {
  "/draft|desktop": VISUAL_FIX_REQUIRED["/draft"],
  "/draft|mobile": VISUAL_FIX_REQUIRED["/draft"],
  "/league-comparison|desktop": VISUAL_FIX_REQUIRED["/league-comparison"],
  "/league-comparison|mobile": VISUAL_FIX_REQUIRED["/league-comparison"],
  "/auction/notifications|desktop": VISUAL_FIX_REQUIRED["/auction/notifications"],
  "/auction/notifications|mobile": VISUAL_FIX_REQUIRED["/auction/notifications"],
  "/league/franchise/[owner]|desktop": VISUAL_FIX_REQUIRED["/league/franchise/[owner]"],
  "/league/franchise/[owner]|mobile": VISUAL_FIX_REQUIRED["/league/franchise/[owner]"],
};

function keyFor(route, testInfo) {
  return `${route}|${isMobileProject(testInfo) ? "mobile" : "desktop"}`;
}

/**
 * Wait for the page to finish arriving before measuring it. Data-driven,
 * not a fixed sleep: React's streaming settled, the network quiet
 * (bounded — a live page that polls never goes idle), and no skeleton or
 * busy marker left. Scanning a skeleton would pass by measuring nothing.
 */
async function settle(page) {
  await awaitStreamSettled(page, { timeout: 20_000 });
  await page.waitForLoadState("networkidle", { timeout: 12_000 }).catch(() => {});
  await page
    .waitForFunction(
      () => !document.querySelector('.ds-skeleton, [aria-busy="true"]'),
      null,
      { timeout: 10_000 },
    )
    .catch(() => {});
  // Explicit loading states (ui/LoadingState, `.loading-spinner`) can
  // outlast network idle — /league-comparison's first build takes 30 s+ —
  // and a scan taken mid-load measures a different page from one taken
  // after it, which made the result timing-dependent. Wait them out
  // (bounded): the page then shows its data or its honest error state.
  await page
    .waitForFunction(
      () => !document.querySelector(".loading-state, .loading-spinner"),
      null,
      { timeout: 45_000 },
    )
    .catch(() => {});
  // A beat of grace for post-data layout (charts measure after paint).
  await page.waitForTimeout(500);
}

async function scanRoute(page, testInfo, label, url) {
  await page.goto(pageUrl(url), { waitUntil: "domcontentloaded" });
  await settle(page);

  const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  const found = {};
  for (const v of results.violations) found[v.id] = v.nodes.length;

  const allowed = BASELINE[keyFor(label, testInfo)] || {};

  // 1. Nothing new, and nothing worse than its allowance.
  const regressions = {};
  for (const [rule, count] of Object.entries(found)) {
    const budget = allowed[rule];
    if (budget == null || count > budget) regressions[rule] = { found: count, allowed: budget ?? 0 };
  }
  expect(
    regressions,
    `new or worsened accessibility violations on ${label} (${url}):\n` +
      results.violations
        .filter((v) => regressions[v.id])
        .map(
          (v) =>
            `  [${v.impact}] ${v.id}: ${v.help}\n` +
            v.nodes
              .slice(0, 3)
              .map((n) => `      ${JSON.stringify(n.target)}\n      ${(n.html || "").slice(0, 120)}`)
              .join("\n"),
        )
        .join("\n"),
  ).toEqual({});

  // 2. A baseline entry that is no longer needed is a stale allowance.
  //    Left alone it hides the next regression of the same rule.
  const stale = Object.keys(allowed).filter((rule) => !(rule in found));
  expect(
    stale,
    `${label}: these baseline allowances are fixed — delete them, or they ` +
      "will absorb the next regression of the same rule",
  ).toEqual([]);
}

for (const route of ROUTES) {
  test(`a11y: ${route} has no new WCAG A/AA violations`, async ({
    authedPage: page,
  }, testInfo) => {
    await scanRoute(page, testInfo, route, route);
  });
}

for (const { family, resolve } of DYNAMIC_ROUTES) {
  test(`a11y: ${family} has no new WCAG A/AA violations`, async ({
    authedPage: page,
  }, testInfo) => {
    const url = await resolve(page);
    await scanRoute(page, testInfo, family, url);
  });
}

// ── Coverage: every page route family under frontend/app is listed ──────
//
// Pure filesystem check — no browser, no stack. Adding a page without
// adding it here fails, which is what keeps "every route family" true.

const APP_DIR = path.resolve(__dirname, "../../../frontend/app");

function pageRouteFamilies(dir = APP_DIR, segs = []) {
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ent.isDirectory()) {
      // `api` holds route handlers, not pages.
      if (segs.length === 0 && ent.name === "api") continue;
      out.push(...pageRouteFamilies(path.join(dir, ent.name), [...segs, ent.name]));
    } else if (/^page\.(jsx?|tsx?)$/.test(ent.name)) {
      // Route groups `(name)` do not appear in the URL.
      const routeSegs = segs.filter((s) => !(s.startsWith("(") && s.endsWith(")")));
      out.push("/" + routeSegs.join("/"));
    }
  }
  return out;
}

test("a11y coverage: every page route family under frontend/app is scanned", () => {
  const families = pageRouteFamilies().sort();
  expect(families.length, "found no pages — did frontend/app move?").toBeGreaterThan(40);
  const listed = new Set([...ROUTES, ...DYNAMIC_ROUTES.map((r) => r.family)]);
  const missing = families.filter((f) => !listed.has(f));
  expect(missing, "page routes with no axe scan — add them to ROUTES / DYNAMIC_ROUTES").toEqual([]);
  const phantom = [...listed].filter((f) => !families.includes(f));
  expect(phantom, "scanned routes with no page under frontend/app — remove them").toEqual([]);
});

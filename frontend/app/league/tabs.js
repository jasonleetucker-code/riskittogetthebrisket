// Tab model for the public /league page — the ONE place that knows
// which tabs exist and which contract section each one needs.
//
// Deliberately server-safe (no "use client", no imports): both the
// server component in ./page.jsx and the client shell in
// ./LeagueClient.jsx read it.  A "use client" module's plain exports
// become client references and cannot be CALLED on the server, so the
// map could not live in LeagueClient.jsx even though that is where the
// tabs are rendered.
//
// Isolation contract (see LeagueClient.jsx): nothing here may import
// from the private canonical pipeline.  It imports nothing at all.

export const PIECE_OF_SHIT_RANKINGS_TAB = "piece-of-shit-rankings";
export const PIECE_OF_SHIT_RANKINGS_TITLE = "Piece of Shit Rankings";

// Brisket Trade Advisor (owner directive 2026-10-19): the League Hub's
// default landing tab.  It is the only tab whose EXISTENCE depends on the
// backend — the `brisket_trade_advisor` feature flag answers 503
// `advisor_unavailable/disabled` (or the route is absent, 404) and the hub
// then behaves exactly as it did before the advisor: Overview is the
// landing tab and the advisor tab is not offered.  `resolveTab` is the one
// place that rule lives; callers pass what they know about availability.
export const TRADE_ADVISOR_TAB = "trade-advisor";
export const TRADE_ADVISOR_TITLE = "Brisket Trade Advisor";
export const TRADE_ADVISOR_SUBTITLE =
  "Evaluate trades using our league's scoring, roster construction, and dynasty market.";
export const OVERVIEW_TAB = "overview";

// URL params the advisor owns.  Dropped by `leagueTabHref` whenever the
// target tab is not the advisor, so a `?team=` never leaks onto Awards.
// Every other tab's params (`owner`, `week`, `year`) keep today's
// behaviour.
export const ADVISOR_PARAMS = Object.freeze(["team", "step"]);

// Tab order + labels for the /league section nav.
export const SUB_TABS = Object.freeze([
  { key: TRADE_ADVISOR_TAB, label: "Trade Advisor" },
  // Key unchanged (every `?tab=overview` link keeps working); the label is
  // no longer "Home" because Home is now the advisor.
  { key: OVERVIEW_TAB, label: "Overview" },
  // The two AI-article tabs replace the older "This Week" structured
  // preview tab and the structured "Recaps" tab. The articles surface
  // the same H2H + form data inline (the brief is built from it), so
  // the structured-data tabs are redundant once articles are wired in.
  { key: "previews", label: "Previews" },
  { key: "recaps", label: "Recaps" },
  { key: "power", label: "Power" },
  { key: "rosTeamStrength", label: "ROS Strength" },
  { key: "rosChampionship", label: "Championship" },
  { key: "rosTradeDeadline", label: "Trade Deadline" },
  { key: "luck", label: "Luck" },
  { key: "streaks", label: "Streaks" },
  {
    key: PIECE_OF_SHIT_RANKINGS_TAB,
    label: PIECE_OF_SHIT_RANKINGS_TITLE,
  },
  { key: "history", label: "History" },
  { key: "rivalries", label: "Rivalries" },
  { key: "awards", label: "Awards" },
  { key: "records", label: "Records" },
  { key: "franchise", label: "Franchises" },
  { key: "activity", label: "Trades" },
  { key: "draft", label: "Draft" },
  { key: "weekly", label: "Weekly" },
  { key: "superlatives", label: "Superlatives" },
  { key: "archives", label: "Archives" },
  { key: "teamAssignment", label: "Team Assignment" },
  { key: "draft-capital", label: "Draft Capital" },
]);

export const VALID_TABS = new Set(SUB_TABS.map((t) => t.key));
export const DEFAULT_TAB = TRADE_ADVISOR_TAB;
// Where the hub lands when the advisor is switched off / not served.
export const ADVISOR_FALLBACK_TAB = OVERVIEW_TAB;

// Old → new tab-key aliases. Two reasons to keep these forever:
//   1. External deep links (sitemap.js, /league/week/<season>/<week>
//      back-links, anyone's bookmarks) may still use a legacy query
//      value. Without the alias they fall through to DEFAULT_TAB on
//      landing.
//   2. Internal CTAs (overview.jsx → onNavigate("matchupPreview"))
//      route through the same setActiveTab path, so aliasing in one
//      place fixes both classes of caller.
// Cheap to keep, never removed.
export const TAB_ALIASES = Object.freeze({
  matchupPreview: "previews",
  weeklyRecap: "recaps",
  conduct: PIECE_OF_SHIT_RANKINGS_TAB,
  advisor: TRADE_ADVISOR_TAB,
});

export function normalizeTabKey(key) {
  if (!key) return key;
  return TAB_ALIASES[key] || key;
}

/**
 * The tab the hub renders for a requested key.
 *
 * Unknown / missing keys land on DEFAULT_TAB (the advisor).  When the
 * advisor is unavailable (``advisorAvailable: false`` — flag off or route
 * absent) both the advisor key and the default resolve to Overview, so a
 * switched-off advisor leaves no broken landing state.
 */
export function resolveTab(key, { advisorAvailable = true } = {}) {
  const normalized = normalizeTabKey(key);
  const landing = advisorAvailable ? DEFAULT_TAB : ADVISOR_FALLBACK_TAB;
  if (!normalized || !VALID_TABS.has(normalized)) return landing;
  if (normalized === TRADE_ADVISOR_TAB && !advisorAvailable) return ADVISOR_FALLBACK_TAB;
  return normalized;
}

// The nav exactly as it was before the advisor (main @ f3e24b3470): no
// advisor tab, and Overview labelled "Home".  An off flag must change
// nothing, so this is what the hub shows whenever the advisor is not
// served.
export const OVERVIEW_LABEL_ADVISOR_OFF = "Home";
const SUB_TABS_ADVISOR_OFF = Object.freeze(
  SUB_TABS.filter((t) => t.key !== TRADE_ADVISOR_TAB).map((t) =>
    t.key === OVERVIEW_TAB ? { ...t, label: OVERVIEW_LABEL_ADVISOR_OFF } : t,
  ),
);

/**
 * The nav's tab list.  Advisor served: the advisor first and Overview
 * labelled "Overview".  Not served: the pre-advisor list, unchanged.
 */
export function visibleTabs({ advisorAvailable = true } = {}) {
  return advisorAvailable ? SUB_TABS : SUB_TABS_ADVISOR_OFF;
}

/**
 * Canonical /league href for a tab.  The landing tab carries no ``?tab=``:
 * the advisor when it is served, Overview when it is not (which is how
 * main wrote it before the advisor existed).  Advisor-only params are
 * dropped on other tabs only while the advisor is served; switched off,
 * the href is built exactly as before.
 */
export function leagueTabHref(key, currentSearch = "", extraParams = {}, { advisorAvailable = true } = {}) {
  const resolved = resolveTab(key, { advisorAvailable });
  const landing = advisorAvailable ? DEFAULT_TAB : ADVISOR_FALLBACK_TAB;
  const params = new URLSearchParams(currentSearch);
  if (resolved === landing) {
    params.delete("tab");
  } else {
    params.set("tab", resolved);
  }
  if (advisorAvailable && resolved !== TRADE_ADVISOR_TAB) {
    for (const name of ADVISOR_PARAMS) params.delete(name);
  }
  for (const [name, value] of Object.entries(extraParams)) {
    if (value === null || value === undefined || value === "") {
      params.delete(name);
    } else {
      params.set(name, String(value));
    }
  }
  const query = params.toString();
  return query ? `/league?${query}` : "/league";
}

// Which public-contract section each tab renders from.
//
// Tabs ABSENT from this map fetch their own data and need nothing from
// the contract: `trade-advisor` (its own public advisor endpoints — never
// the public-league contract, and never a value), `previews`/`recaps`
// (ArticlesSection), `power`
// (RosPowerSection reads the lazy `rosPower` section directly — the v1
// engine and its eager `power` section are retired), the four `ros*`
// tabs, `draft-capital`, and `teamAssignment` (moved to self-fetching
// 2026-09-01 when the NFL Team Affinity rewrite made it a private,
// session-gated section — see `PRIVATE_INTELLIGENCE_SECTIONS` in
// `src/public_league/public_contract.py`; it can no longer ride the
// anonymous eager aggregate the way its old points-based scoring did).
// That absence is load-bearing — it is what lets the server ship a
// contract containing only the sections the landing tab actually reads
// instead of all seventeen (2.01 MB, of which `weeklyRecap` alone is
// 378 KB that this page never renders at all since the articles tabs
// replaced it).
export const SECTION_FOR_TAB = Object.freeze({
  overview: "overview",
  luck: "luck",
  streaks: "streaks",
  [PIECE_OF_SHIT_RANKINGS_TAB]: "conduct",
  history: "history",
  rivalries: "rivalries",
  awards: "awards",
  records: "records",
  franchise: "franchise",
  activity: "activity",
  draft: "draft",
  weekly: "weekly",
  superlatives: "superlatives",
  archives: "archives",
});

/**
 * Section needed to render ``tab``, or null when the tab is
 * self-fetching.  Unknown tabs resolve through DEFAULT_TAB so a
 * hand-typed ``?tab=`` lands on the same section the UI will show.
 */
export function sectionForTab(tab, opts = {}) {
  return SECTION_FOR_TAB[resolveTab(tab, opts)] || null;
}

// "← League home" back-links on the /league/* detail pages.  Before the
// advisor they all pointed at `/league`, and with the advisor switched off
// they still must (an off flag changes nothing).  Only once the advisor is
// CONFIRMED served (bootstrap state "ready") is `/league`'s landing the
// advisor, so "League home" then names Overview explicitly.  "unknown"
// (no answer) keeps `/league`: a back-link never guesses the flag is on.
export const LEAGUE_HOME_HREF = "/league";
export const LEAGUE_OVERVIEW_HREF = `/league?tab=${OVERVIEW_TAB}`;
export function leagueHomeHrefFor(advisorBootstrap) {
  return advisorBootstrap?.state === "ready" ? LEAGUE_OVERVIEW_HREF : LEAGUE_HOME_HREF;
}

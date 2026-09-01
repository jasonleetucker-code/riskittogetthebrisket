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

// Tab order + labels for the /league section nav.
export const SUB_TABS = Object.freeze([
  { key: "overview", label: "Home" },
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
export const DEFAULT_TAB = "overview";

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
});

export function normalizeTabKey(key) {
  if (!key) return key;
  return TAB_ALIASES[key] || key;
}

export function leagueTabHref(key, currentSearch = "", extraParams = {}) {
  const normalized = normalizeTabKey(key);
  const resolved = VALID_TABS.has(normalized) ? normalized : DEFAULT_TAB;
  const params = new URLSearchParams(currentSearch);
  if (resolved === DEFAULT_TAB) {
    params.delete("tab");
  } else {
    params.set("tab", resolved);
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
// the contract: `previews`/`recaps` (ArticlesSection), `power`
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
export function sectionForTab(tab) {
  const key = normalizeTabKey(tab);
  const resolved = VALID_TABS.has(key) ? key : DEFAULT_TAB;
  return SECTION_FOR_TAB[resolved] || null;
}

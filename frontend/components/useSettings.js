"use client";

import { useCallback, useSyncExternalStore } from "react";
import { SETTINGS_KEY } from "@/lib/trade-logic";

// ── Default Settings (single source of truth) ──────────────────────────
// Covers all tuning parameters needed by every surface:
// trade calculator, rankings, edge, roster dashboard, league, settings page.
export const SETTINGS_DEFAULTS = {
  // League format
  leagueFormat: "superflex",         // "superflex" | "standard"

  // Value adjustment strengths
  //
  // tepMultiplier: null means "auto from league" — the backend derives
  // the TE-premium multiplier from the operator's Sleeper league
  // ``bonus_rec_te`` scoring setting and applies that value during the
  // blend.  A standard TEP-1.5 league (bonus_rec_te=0.5) yields 1.15;
  // a non-TEP league yields 1.0 (a no-op).  When the user drags the
  // slider on /settings, this flips from null to a finite number,
  // which ``fetchDynastyData`` then POSTs to the override endpoint as
  // an explicit override on top of the derived default.  "Reset"
  // returns it to null so the derived baseline kicks back in.
  //
  // Pre-2026-04 this defaulted to 1.15 — which silently applied a TE
  // boost to every cold-start user regardless of whether their league
  // even had a TE premium.  Moving the default to null fixes that
  // mismatch: the board you see reflects your Sleeper league.
  tepMultiplier: null,               // null = auto from Sleeper bonus_rec_te; 1.0..2.0 = explicit

  // Rankings display
  rankingsSortBasis: "full",         // "full" | "raw"
  // Source-site columns are off by default.  The rankings table's
  // headline columns (rank, player, pos, consensus, value) are what
  // most users open the page to see; the per-source value + rank
  // cells are power-user transparency data that dominates the
  // viewport — especially on mobile, where they render as a wrapping
  // chip strip below every row and push the Value column off-screen.
  // Users who want to audit per-source contributions can flip the
  // toggle from the Columns popover on /rankings or the Rankings
  // Display section on /settings.  See rankings/page.jsx for the
  // render gate.
  showSiteCols: false,



  // Per-source column visibility map ({ [sourceKey]: false } to
  // hide a specific source column on the rankings table).  Any key
  // missing from the map defaults to visible — so an empty map
  // means "show all columns".  Independent from ``siteWeights``
  // (which controls whether a source contributes to the blend) —
  // this toggle is purely about rendered column clutter.
  hiddenSiteCols: {},

  // Pick settings
  pickCurrentYear: 2026,

  // Per-user source override map.  Shape:
  //   { [sourceKey]: { include?: boolean, weight?: number } }
  // Read by `useDynastyData` → `fetchDynastyData`, which POSTs the
  // map to the backend override endpoint whenever it differs from
  // the registry defaults.  The backend re-runs the canonical
  // ranking pipeline with the overrides threaded in and returns a
  // compact delta payload that the frontend merges onto its cached
  // base contract.  An empty map (default) means "inherit everything
  // from the canonical RANKING_SOURCES registry" — every source
  // enabled at weight 1.0, no backend round-trip needed.
  siteWeights: {},

  // Trade history
  tradeHistoryWindowDays: 365,       // rolling 1-year window for trade analysis

  // Selected team (LEGACY, one-league era).  Kept for back-compat:
  // if ``selectedTeamsByLeague`` has no entry for the active league
  // but this field is set AND the active league is the registry
  // default, ``useTeam`` treats this as the default league's pick.
  // Writes still mirror here when on the default league so a roll-
  // back to a pre-migration build won't flip the user's team empty.
  selectedTeam: "",                  // Sleeper team name selection

  // True once the user (or any surface) has written ``selectedTeam``
  // at least once on this device.  Used by ``useTeam`` to distinguish
  // "never chose" from "explicitly cleared" so auto-assignment of the
  // default team does not silently re-overwrite a deliberate empty
  // selection on reload.  Written implicitly by ``update`` below —
  // any call of the shape ``update("selectedTeam", ...)`` (the
  // TeamSwitcher, the /rosters "My team..." dropdown, and any future
  // surface) flips this to true in the same localStorage write.
  selectedTeamTouched: false,

  // Per-league selected team map.  Shape:
  //   { [leagueKey]: { ownerId, teamName, rosterId?, managerName? } }
  // Takes precedence over ``selectedTeam`` when an entry exists for
  // the active league.  ``useTeam`` writes to this AND mirrors to
  // the legacy field when writing for the default league.
  selectedTeamsByLeague: {},
  // Per-league touched flags, same shape as ``selectedTeamTouched``
  // but keyed by leagueKey.  Once a user picks a team in League B
  // explicitly, auto-select never overrides their choice on that
  // league — even if their League A pick was implicit.
  selectedTeamTouchedByLeague: {},

  // ── Rest-of-Season (ROS) engine flags ─────────────────────────────
  // The ROS layer is a separate short-term contender system — it
  // never modifies dynasty values or trade math.  These flags gate
  // the new UI surfaces (added in PR1; PR2-5 wire more consumers).
  rosEnabled: true,
  // PR2 ships ros-power as a side-by-side alternative to the existing
  // power.py-based section.  Default false so ros-power is opt-in
  // until validated; when the user flips it true, the league page
  // swaps the Power tab to the ROS-driven version.
  useRosPowerRankings: false,
  // PR3 ships ros-playoff-odds.  Same opt-in pattern.
  useRosPlayoffOdds: false,
  // PR4 ships the trade-calculator ROS-fit panel + player-popup tags.
  showRosTradePanel: true,
  showRosTags: true,
  // PR3 Monte Carlo iteration count.  10k is enough for stable
  // playoff/championship odds; 50k for tighter tail estimates.
  rosSimulationCount: 10000,
  // TE premium adjustment for non-TEP-native ROS sources.  Capped
  // at 0.15 (matches spec).  0 disables the adjustment entirely.
  rosTepBoost: 0.05,
  // Per-source overrides that mirror dynasty's ``siteWeights`` shape.
  // ``{ [sourceKey]: { enabled: bool, weight: number } }``.  Empty
  // means "use registry defaults".
  rosSourceOverrides: {},
};

// ── localStorage helpers ────────────────────────────────────────────────
function readSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) return { ...SETTINGS_DEFAULTS, ...JSON.parse(raw) };
  } catch { /* ignore */ }
  return { ...SETTINGS_DEFAULTS };
}

function writeSettings(settings) {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch { /* ignore */ }
}

// ── Subscribers for cross-component sync ────────────────────────────────
let listeners = new Set();
let cached = null;

function subscribe(cb) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

function getSnapshot() {
  if (cached === null) cached = readSettings();
  return cached;
}

function getServerSnapshot() {
  return SETTINGS_DEFAULTS;
}

function notify(next) {
  cached = next;
  for (const cb of listeners) cb();
}

// Listen for storage events from other tabs
if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key === SETTINGS_KEY) {
      notify(readSettings());
    }
  });
}

/**
 * Hook to read and write user settings.
 * Changes are synced across all components using this hook.
 */
export function useSettings() {
  const settings = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const update = useCallback((key, value) => {
    const next = { ...getSnapshot(), [key]: value };
    // Any write to ``selectedTeam`` — from any caller — marks the
    // selection as user-touched.  This preserves an explicit clear
    // ("") across reloads by giving ``useTeam``'s auto-assign guard
    // a durable signal that's distinct from the empty-string default.
    if (key === "selectedTeam") next.selectedTeamTouched = true;
    writeSettings(next);
    notify(next);
  }, []);

  // Update a single per-source override field.  `field` is typically
  // `"include"` (boolean) or `"weight"` (number).  Passing `value`
  // equal to the source's registry default does NOT automatically
  // delete the entry — users who want to reset a single source
  // should use the "Reset" affordance in the settings UI, which
  // calls `clearSiteWeight` below.
  const updateSiteWeight = useCallback((siteKey, field, value) => {
    const prev = getSnapshot();
    const weights = { ...prev.siteWeights };
    weights[siteKey] = { ...(weights[siteKey] || {}), [field]: value };
    const next = { ...prev, siteWeights: weights };
    writeSettings(next);
    notify(next);
  }, []);

  // Delete every per-source override and fall back to registry
  // defaults.  Keeps all OTHER settings intact (tepMultiplier,
  // showSiteCols, etc.) so a weight reset doesn't blow away the
  // rest of the user's preferences.
  const resetSiteWeights = useCallback(() => {
    const prev = getSnapshot();
    const next = { ...prev, siteWeights: {} };
    writeSettings(next);
    notify(next);
  }, []);

  const reset = useCallback(() => {
    writeSettings(SETTINGS_DEFAULTS);
    notify({ ...SETTINGS_DEFAULTS });
  }, []);

  return { settings, update, updateSiteWeight, resetSiteWeights, reset };
}

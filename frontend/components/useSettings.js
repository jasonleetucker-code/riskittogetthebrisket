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
  // tepMultiplier / tepNativeMultiplier: two parallel knobs for the
  // TE Premium boost applied at blend time.
  //
  //   * ``tepMultiplier`` → non-TEP sources (DLF, FBG, FP consensus,
  //     Flock, etc.).  ``null`` = "no operator override", which is what
  //     lets the backend apply the MEASURED ADR-015 TE basis conversion
  //     (``te_premium.convert_te_value``, KTC's own uplift: 1.209 at the
  //     top of the board rising toward 2.05 down it).
  //   * ``tepNativeMultiplier`` → TEP-native sources (DN SF-TEP,
  //     Yahoo Boone, FP Fitzmaurice).  Default 1.10 backend-side.
  //
  // Why this is ``null`` and not a number.  It used to default to 1.15,
  // derived as ``1.0 + 0.5*0.30`` for a TEP-1.5 league.  That derivation
  // predates ADR-015 and is strictly worse than it — a flat 1.15 sits
  // BELOW the entire measured range.  Worse, the backend decides whether
  // to apply the curve from "did the operator choose a number?", and
  // ``tepMultiplierIsCustomized`` (lib/dynasty-data.js) answers yes for
  // ANY finite number.  A numeric default is therefore indistinguishable
  // from a deliberate override, so every page load for every user posted
  // ``tep_multiplier=1.15`` and silently disabled the measured curve —
  // 627 of 740 ranks and 654 tiers diverged from what ``GET /api/data``
  // serves, while the response still stamped ``isCustomized:false``.
  // Audit findings W03-F001 / W07-F001 / W08-F001.
  //
  // ``null`` is the only value the customization predicate reads as
  // "auto", which is why this knob and ``tepNativeMultiplier`` now use
  // the same sentinel. A number here is a decision and is still honoured
  // verbatim — that path is unchanged.
  //
  // KTC variants (ktc, ktcSfTep) stay exempt regardless — KTC's TE++
  // board is the canonical reference.
  tepMultiplier: null,               // null = auto (measured ADR-015 curve); 1.0..1.5 = explicit operator override
  tepNativeMultiplier: null,         // null = backend default (1.10); 1.0..1.5 = explicit operator override

  // One-time migration marker.  False/absent → ``readSettings`` returns
  // a persisted ``tepMultiplier`` of 1.15 to ``null`` exactly once.
  //
  // This REPLACES the v3 migration, which promoted ``null`` → 1.15 and
  // so actively moved users who were on the correct auto path off it,
  // permanently. Anyone still carrying that 1.15 was moved there by a
  // migration or by the old default, not by choosing it; a user who did
  // deliberately type 1.15 is indistinguishable, and the cost of being
  // wrong about them is that they get the measured curve instead of a
  // flat factor below its whole range.
  tepDefaultV4Applied: false,

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

  // (Removed) pickCurrentYear — the future-year pick discount and its
  // self-rolling current draft year are now backend-owned
  // (src/api/data_contract.py); the frontend no longer re-discounts.

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

  // Valuation lens (LI-9).  "market" is the consensus board exactly as
  // the canonical pipeline computes it — today's behaviour and the
  // deliberate default, so nothing moves until this is switched on.
  //
  // "leagueAdjusted" overlays GET /api/valuation/league-adjusted, which
  // reprices by positional scarcity measured from THIS league's twelve
  // rosters.  It is a per-league overlay rather than contract fields
  // because the contract is shared across leagues with the same
  // scoring profile — see src/league_intel/publish.py.
  //
  // Starts "market" on every device and is never auto-flipped: a value
  // lens that turned itself on would silently change every number on
  // the site, including in trade evaluation.
  valuationMode: "market",

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
  // PR2 shipped ros-power as a side-by-side alternative to the
  // existing power.py-based section.  Default flipped to true on
  // 2026-04-29 after the engine validated against ~5 weeks of live
  // standings; the new ROS-driven Power tab replaces the v1
  // PPG-based view by default.  Users who prefer v1 can flip the
  // toggle back on /settings.
  useRosPowerRankings: true,
  // PR3 shipped ros-playoff-odds.  Default flipped to true on
  // 2026-04-29; the ROS-blended Monte Carlo replaces the empirical-
  // only v1 by default.  Users who prefer v1 can flip back via
  // /settings.
  useRosPlayoffOdds: true,
  // PR4 ships the trade-calculator ROS-fit panel + player-popup tags.
  showRosTradePanel: true,
  showRosTags: true,
  // PR3 Monte Carlo iteration count.  10k is enough for stable
  // playoff/championship odds; 50k for tighter tail estimates.
  rosSimulationCount: 10000,
  // TE premium adjustment for non-TEP-native ROS sources.  Capped
  // at 0.15 (matches spec).  0 disables the adjustment entirely.
  rosTepBoost: 0.05,
  // KTC top-N cap on trade-suggestion candidacy.  Default 150 was
  // a hard constant; bumped to a configurable knob so deeper
  // formats (14-team 2QB, deep-IDP keeper) can opt into a wider
  // pool.  Server clamps to [50, 300].
  ktcSuggestionTopN: 150,
  // Per-source overrides that mirror dynasty's ``siteWeights`` shape.
  // ``{ [sourceKey]: { enabled: bool, weight: number } }``.  Empty
  // means "use registry defaults".
  rosSourceOverrides: {},
};

// ── localStorage helpers ────────────────────────────────────────────────
function readSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) {
      const merged = { ...SETTINGS_DEFAULTS, ...JSON.parse(raw) };
      // One-time TEP default migration (v4).  Return a persisted 1.15
      // to ``null`` = auto, so the backend applies the measured ADR-015
      // basis conversion instead of a flat factor that sits below its
      // entire range.
      //
      // This undoes v3, which ran the other way (null → 1.15) and so
      // took users who were correctly on auto and pinned them to the
      // override path for good.  Anyone holding 1.15 today was put there
      // by that migration or by the old numeric default; see the
      // ``tepDefaultV4Applied`` note in SETTINGS_DEFAULTS for why
      // reclaiming the ambiguous case is the right trade.
      //
      // A value the operator typed that is NOT 1.15 is untouched, and
      // once the flag is set a deliberate later 1.15 persists.
      if (!merged.tepDefaultV4Applied) {
        if (merged.tepMultiplier === 1.15) {
          merged.tepMultiplier = null;
        }
        merged.tepDefaultV4Applied = true;
        delete merged.tepDefaultV3Applied;
        writeSettings(merged);
      }
      return merged;
    }
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

// ── Hydration signal ───────────────────────────────────────────────────
//
// ``getServerSnapshot`` is what React uses for BOTH the server render and
// the client's hydration pass, so the first client render of every
// settings consumer sees SETTINGS_DEFAULTS regardless of what is in
// localStorage.  React then re-renders with ``getSnapshot``.
//
// For most settings that gap is invisible.  For ``valuationMode`` it is
// not: a user whose persisted lens is "leagueAdjusted" gets one frame of
// a toggle highlighting "Market" — which is not a cosmetic flicker but a
// claim about which board the numbers on screen came from, on a page
// where that claim decides trade verdicts.  It also costs a wasted
// round-trip, because ``useDynastyData``'s fetch effect fires once on the
// defaults and again after hydration.
//
// This is the canonical detector: the same store, read through a snapshot
// pair that differs only in which side is asking.  No extra state, no
// effect, and it flips in the same commit that brings the real settings
// in — so a consumer gating on it can never be told "hydrated" while
// still holding defaults.
function getHydratedSnapshot() {
  return true;
}

function getHydratedServerSnapshot() {
  return false;
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
  // False during SSR and the hydration pass, true from the first
  // post-hydration render on.  While false, ``settings`` is
  // SETTINGS_DEFAULTS and NOT this device's persisted values — see the
  // note above ``getHydratedSnapshot``.  Consumers whose rendering makes
  // a claim about a persisted value should gate on this.
  const hydrated = useSyncExternalStore(
    subscribe,
    getHydratedSnapshot,
    getHydratedServerSnapshot,
  );

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

  return { settings, hydrated, update, updateSiteWeight, resetSiteWeights, reset };
}

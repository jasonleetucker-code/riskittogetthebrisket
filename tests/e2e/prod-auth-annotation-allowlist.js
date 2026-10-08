/**
 * Which prod-auth annotations may be PUBLISHED, per spec file (security S3).
 *
 * The prod-auth suite runs against production with a real session, and this
 * repository is public: whatever `prod-auth-safe-reporter.js` writes is
 * readable by anyone. Specs annotate freely while they run; only an annotation
 * whose TYPE is listed here for ITS spec file, and whose description is
 * EXACTLY a value of the declared kind, reaches the report. Everything else is
 * withheld and counted per test (`withheldCount`).
 *
 * Owner directive 2026-10-08: no private data in public artifacts, sanitized
 * evidence only. So the kinds are statuses, booleans, counts, HTTP statuses,
 * enum states and fixed code-authored strings. There is no "free text" kind:
 * owner ids, player names, team names, win %, value/rank movement, roster sizes
 * tied to a team, trade recommendations and prose never match.
 *
 * Adding an entry is a privacy decision. A count or state belongs here only
 * when it describes the SITE (a status, a state, how many rows rendered), never
 * a named team, player or manager.
 */
const fs = require("node:fs");
const path = require("node:path");

/** Registry league keys (stable public keys, never Sleeper ids). */
function registryKeys() {
  try {
    const file = path.join(__dirname, "..", "..", "config", "leagues", "registry.json");
    const reg = JSON.parse(fs.readFileSync(file, "utf-8"));
    return new Set((reg.leagues || []).map((l) => l && l.key).filter((k) => typeof k === "string"));
  } catch {
    return new Set();
  }
}

const REGISTRY_KEYS = registryKeys();

/** kind name -> predicate over the annotation's description string. */
const KINDS = {
  bool: (v) => v === "true" || v === "false",
  count: (v) => /^(0|[1-9]\d{0,6})$/.test(v),
  http_status: (v) => /^[1-5]\d{2}$/.test(v),
  year: (v) => /^20\d{2}$/.test(v),
  // An API enum value (e.g. "AVAILABLE", "pregame", "cohort_building"). Used
  // only on types whose value the spec takes from an enum field.
  state: (v) => /^[A-Za-z][A-Za-z0-9_-]{0,39}$/.test(v),
  registry_key: (v) => REGISTRY_KEYS.has(v),
};

/** A fixed set of exact, code-authored strings. */
function oneOf(...values) {
  const set = new Set(values);
  return (v) => set.has(v);
}

const ALLOWLIST = {
  "game-day-team-switch.spec.js": {
    "team-switch-league": "registry_key",
    "team-switch-A-mode": "state",
    "team-switch-B-mode": "state",
    "team-switch-C-mode": "state",
    "team-switch-A-probability-state": "state",
    "team-switch-B-probability-state": "state",
    "team-switch-C-probability-state": "state",
    "team-switch-same-generation": "bool",
    "team-switch-reversal-verified": "bool",
  },
  "game-day-median-race.spec.js": {
    "median-race-league": "registry_key",
    "median-race-week": "count",
    "median-race-mode": "state",
    "median-race-state": "state",
    "median-race-teams": "count",
  },
  "league-mvp-gate.spec.js": {
    "league-mvp-gate-verified": "bool",
    "league-mvp-gate-basis": "state",
    "league-mvp-gate-playoff-field": "count",
    "league-mvp-gate-outside-count": "count",
  },
  "awards-standings.spec.js": {
    "waiver-king-season": "year",
    "waiver-king-standings-rows": "count",
    "waiver-king-ineligible-rows": "count",
    "player-award-rows": "count",
    "top_offense-rows": "count",
    "top_defense-rows": "count",
  },
  "pick-lifecycle-horizon.spec.js": {
    "retired-2026": "bool",
    "pick-rows-2026": "count",
    "pick-rows-2027": "count",
    "pick-rows-2028": "count",
    "pick-rows-2029": "count",
    "pick-rows-2030": "count",
  },
  "trade-stack-withdrawn.spec.js": {
    "trade-stack-totals-unchanged-by-team-switch": "bool",
    "trade-stack-note-shown-for-owned-first": "bool",
    "trade-stack-balancers": "count",
  },
  "trade-war-room.spec.js": {
    "war-room-1for1-requires-drops": "bool",
    "war-room-2for1-requires-drops": "bool",
    "war-room-1for2-requires-drops": "bool",
    "war-room-1for1-feasibility": "state",
    "war-room-2for1-feasibility": "state",
    "war-room-1for2-feasibility": "state",
    "war-room-asset-only-applied": "bool",
  },
  "train2-private-surfaces.spec.js": {
    "team-selected": "bool",
    "session-auth-method": "state",
    "session-is-admin": "bool",
    "model-lab-status": "http_status",
    "model-lab-error": "state",
    "admin-content-exercised": "bool",
    "trade-protections-configured": "bool",
    "trade-protections-put-status": "http_status",
    "trade-protections-put-error": "state",
    "value-movement-status": "state",
    "value-movement-sources-recorded": "count",
    "value-movement-sources-moved": "count",
    "value-movement-sources-not-observed": "count",
    "why-it-moved-status": "state",
    "why-it-moved-fetches": "count",
    "core-state": oneOf("available", "unavailable"),
    "core-unavailable-reason": "state",
    "core-slot-source": "state",
    "droppable-rows-match-ladder": "bool",
    "trade-targets-state": oneOf("intel_unavailable", "weakness_unavailable", "needs_served"),
    "pick-projector-dynasty_main-state": oneOf("served", "degraded_no_teams"),
    "pick-projector-dynasty_new-state": oneOf("served", "degraded_no_teams"),
    "pick-projector-dynasty_main-source": "state",
    "pick-projector-dynasty_new-source": "state",
    "pick-projector-dynasty_main-reason": "state",
    "pick-projector-dynasty_new-reason": "state",
    "reconciler-emitters-reporting": "count",
    "player-impact-state": oneOf("served", "league_snapshot_mismatch"),
    "player-impact-settings-state": "state",
    "player-impact-rows": "count",
  },
  "v1-131-nav-gating.spec.js": {
    "board-endpoint-status": "http_status",
    branch: oneOf("available=true", "available=false"),
  },
  "v1-123-draft-capital.spec.js": {
    "states-observed": oneOf("draft-capital: populated", "draft-capital: unavailable (explicit)"),
  },
  "v1-123-league-comparison.spec.js": {
    "states-observed": oneOf(
      "league-comparison: populated, tabs navigable",
      "league-comparison: unavailable (explicit)",
    ),
  },
  "v1-123-sharp-roster-percentage.spec.js": {
    "states-observed": oneOf("sharp-roster-percentage: populated", "sharp-roster-percentage: empty"),
  },
  "v1-123-team-strength.spec.js": {
    "states-observed": oneOf("ros-team-strength: not-ready", "ros-team-strength: unavailable"),
  },
  "v1-123-mobile-nav.spec.js": {
    tabbar: oneOf("all five tabs (Home/Ranks/Trade/News/Menu) rendered"),
    "tab-navigation": oneOf("Trade -> Ranks round trip landed on the real board"),
  },
  "v1-123-package-builder.spec.js": {
    "angle-offer-scan": oneOf("real return packages rendered", "explicit empty/validation state"),
  },
  "v1-123-rankings-journeys.spec.js": {
    sort: oneOf("asc/desc toggled and reversed on the real production board"),
    "player-popup": oneOf("opened with Our Value + Source Breakdown, closed cleanly"),
  },
  "v1-123-source-disagreement.spec.js": {
    "edge-tabs": oneOf("gaps/agreement/caution all rendered on production"),
  },
  "v1-123-trade-journeys.spec.js": {
    "trades-history": oneOf("explicit empty state"),
    "arbitrage-scan": oneOf("explicit empty state"),
    "arbitrage-player-level": oneOf("explicit empty state at default threshold"),
  },
  "v1-62-sharp-tracker.spec.js": {
    "states-observed": oneOf(
      "sharp-tracker: populated",
      "sharp-tracker: cohort_building",
      "sharp-tracker: no_activity",
    ),
  },
  "v1-45-trade-surface.spec.js": {
    "states-observed": oneOf(
      "finalRosterSimulation: populated",
      "finalRosterSimulation: capacity_uncertain",
    ),
  },
  "v1-27-lineup-render.spec.js": {
    "state-observed": oneOf(
      "all stamps available → starter totals rendered, no unavailable note",
      "missing stamp(s) → explicit 'Starter totals unavailable' note rendered",
    ),
  },
  "v1-56-waivers-faab-strip.spec.js": {
    "state-observed": oneOf(
      "payload present but zero evidence — em-dash unavailable state verified",
      "analytics absent: strip rendered with explicit em-dash unavailable state",
      "analytics absent and no team context: strip absent entirely (its documented null state)",
    ),
  },
  "w1-12-public-pregame.spec.js": {
    "w1-12-matchup-cards": "count",
    "w1-12-mobile-overflow-px": "count",
    "w1-12-first-meeting": oneOf("first-ever meeting rendered", "no first-ever meeting this week"),
    "w1-12-cta": oneOf("Full H2H preview → structured previews"),
    "w1-12-privacy": oneOf("no projection or probability language on the public page"),
  },
  "w1-16-game-day.spec.js": {
    "w1-16-endpoint-status": "http_status",
    "w1-27-mode": "state",
    "w1-28-mode": "state",
    "w1-27-probability-state": "state",
    "w1-16-mobile-overflow-px": "count",
  },
};

/**
 * `{ ok: true }` when this (spec file, type, description) may be published.
 * Unknown file, unknown type, unknown kind, or a description that is not
 * exactly a value of the kind -> not publishable.
 */
function isPublishable(file, type, description) {
  // Own properties only: a type named "constructor" or "__proto__" must not
  // resolve to something inherited from Object.prototype.
  if (typeof file !== "string" || !Object.hasOwn(ALLOWLIST, file)) return false;
  const spec = ALLOWLIST[file];
  if (typeof type !== "string" || !Object.hasOwn(spec, type)) return false;
  const entry = spec[type];
  const check = typeof entry === "function" ? entry : Object.hasOwn(KINDS, entry) ? KINDS[entry] : null;
  if (typeof check !== "function") return false;
  return typeof description === "string" && check(description) === true;
}

module.exports = { ALLOWLIST, KINDS, isPublishable, oneOf };

"use client";

import { normalizePos } from "@/lib/dynasty-data";

/**
 * starter-slots — the lineup MATERIALIZER.
 *
 * THE SERVER ASSIGNS; THIS RENDERS (C2-U1).
 *
 * This module used to answer "given a roster and a league's lineup
 * slots, which players start?" with its own two-pass greedy fill. It no
 * longer answers that question at all. `src/ros/lineup.py` is the single
 * canonical assignment owner, the contract stamps each team's solved
 * lineup on `sleeper.teams[].optimalLineup`, and `fillLineup` reads that
 * stamp — exactly the relationship `buildRows` already has with
 * `canonicalConsensusRank`.
 *
 * WHY IT WAS REMOVED RATHER THAN REPAIRED
 *
 * Measured against Sleeper's OWN awarded best-ball lineups over 10 real
 * 2025 team-weeks (`tests/league_intel/fixtures/golden_bestball_lineups.json`):
 *
 *   exact server solver   10/10 reproduces the host
 *   this two-pass greedy   5/10, short 50.14 points
 *
 * and that 50.14 splits into **34.01 points of eligibility blindness**
 * (it read a single position token, so a DL/LB hybrid was locked out of
 * half its legal slots) plus **16.13 points the ALGORITHM itself loses**
 * on a week where the greedy's slot order is wrong. The second number is
 * the load-bearing one: it is measured with the canonical eligibility
 * handed to the greedy, so shipping this file better DATA — a JavaScript
 * port of the eligibility tables — would have left points on the table
 * and a second implementation to keep in sync. A two-pass fill is
 * optimal only while slot eligibility is a laminar family, which is an
 * unstated precondition nobody was enforcing.
 *
 * WHAT SURVIVES HERE, AND WHY
 *
 * `lineupPosition` — the display vocabulary (DL/LB/DB kept distinct).
 * It is now a MIRROR of `src/ros/lineup.py::lineup_position`, held in
 * lockstep by `frontend/__tests__/starter-slots.test.js` and
 * `tests/lineup/test_single_owner.py`, the same arrangement the source
 * registry already uses. It decides no assignment; it groups rows for
 * display.
 *
 * FAIL CLOSED, NEVER RECOMPUTE
 *
 * No stamp means `available: false` — empty starters, everything on the
 * bench, and the panel says so. There is deliberately no client-side
 * fallback fill: a silent recompute is how two answers to one question
 * survive, and "we do not know this league's lineup" must not render the
 * same as "this team starts nobody".
 */

const DL_FAMILY = new Set(["DL", "DE", "DT", "EDGE", "NT"]);
const LB_FAMILY = new Set(["LB", "OLB", "ILB", "MLB"]);
const DB_FAMILY = new Set(["DB", "CB", "S", "FS", "SS"]);

/**
 * A player position resolved to the token a lineup slot is named in.
 *
 * MIRROR of `src/ros/lineup.py::lineup_position`. Display grouping only
 * — it selects no starter. Defensive players resolve to their FAMILY,
 * kept distinct, because this league starts 3 at each of DL/LB/DB, not
 * 9 defenders; collapsing them makes every defensive slot match every
 * defender and a roster stacked at one IDP position gets credited for
 * players the league has no slot for.
 */
export function lineupPosition(pos) {
  const p = normalizePos(pos);
  if (DL_FAMILY.has(p)) return "DL";
  if (LB_FAMILY.has(p)) return "LB";
  if (DB_FAMILY.has(p)) return "DB";
  // `normalizePos` maps P -> K but not PK, and a kicker must keep
  // matching the league's K slot.
  if (p === "PK") return "K";
  return p;
}

// Slots that are not part of the starting lineup. Mirrors
// `src/ros/lineup.py::NON_LINEUP_SLOTS`.
const NON_LINEUP_SLOTS = new Set(["BN", "IR", "TAXI"]);

/**
 * The starting-lineup slots in a Sleeper `rosterPositions` array.
 *
 * Kept for the panels that only need to know HOW MANY slots a league
 * runs (and which). It reads a league's declared lineup; it assigns
 * nobody to it.
 */
export function lineupSlots(sleeperRosterPositions) {
  if (!Array.isArray(sleeperRosterPositions) || sleeperRosterPositions.length === 0) {
    return [];
  }
  return sleeperRosterPositions
    .map((p) => String(p).toUpperCase())
    .filter((p) => !NON_LINEUP_SLOTS.has(p));
}

/**
 * Materialize a team's server-solved lineup against a local asset list.
 *
 * @param {object}   opts
 * @param {object[]} opts.assets   - the roster rows this page renders
 * @param {Function} opts.keyOf    - asset → the key the stamp uses. That
 *   key is the SLEEPER roster name, which is what the server iterated
 *   when it solved; a page that joins on its own display name will miss
 *   wherever the two spellings differ.
 * @param {object}   [opts.optimalLineup] - `team.optimalLineup` from the
 *   contract. Absent ⇒ `available: false`.
 *
 * @returns {{starters, bench, unpriced, assignments, slotCount,
 *   unfilledSlots, available, slotSource}}
 *
 *   `unpriced` is a THIRD state beside starters and bench: the board
 *   declined to price those players, so they neither started nor were
 *   passed over on merit. Folding them into the bench is the same
 *   missing-is-zero error one layer up.
 */
export function fillLineup({ assets, keyOf, optimalLineup }) {
  const pool = assets || [];
  const stamp = optimalLineup;

  if (!stamp || stamp.available !== true) {
    return {
      starters: [],
      bench: pool,
      unpriced: [],
      assignments: [],
      slotCount: 0,
      unfilledSlots: [],
      available: false,
      slotSource: stamp?.slotSource ?? null,
      reason: stamp?.reason ?? "no_server_lineup",
    };
  }

  const byKey = new Map();
  for (const a of pool) {
    const k = keyOf ? keyOf(a) : a?.name;
    if (k != null && !byKey.has(String(k))) byKey.set(String(k), a);
  }

  const starterKeys = new Set(stamp.starters || []);
  const unpricedKeys = new Set(stamp.unpriced || []);

  const assignments = (stamp.assignments || [])
    .map(({ slot, player }) => ({ slot, asset: byKey.get(String(player)) ?? null }))
    .filter((a) => a.asset);

  return {
    starters: pool.filter((a) => starterKeys.has(String(keyOf ? keyOf(a) : a?.name))),
    bench: pool.filter((a) => {
      const k = String(keyOf ? keyOf(a) : a?.name);
      return !starterKeys.has(k) && !unpricedKeys.has(k);
    }),
    unpriced: pool.filter((a) => unpricedKeys.has(String(keyOf ? keyOf(a) : a?.name))),
    // Slot-ordered, for anything that RENDERS the lineup. A
    // value-descending list truncated to fit a panel eats the defense
    // entirely, because IDP values sit far below offense on the board.
    assignments,
    slotCount: (stamp.slots || []).length,
    unfilledSlots: stamp.unfilledSlots || [],
    available: true,
    slotSource: stamp.slotSource ?? null,
  };
}

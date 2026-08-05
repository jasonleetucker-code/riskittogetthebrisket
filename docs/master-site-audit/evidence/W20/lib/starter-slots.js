"use client";

import { normalizePos } from "./dynasty-data.js";

/**
 * starter-slots — THE lineup-slot filler.
 *
 * One implementation of "given a roster and a league's lineup slots,
 * which players start?", shared by `portfolio-insights.js` (/terminal)
 * and `league-analysis.js` (/rosters).
 *
 * WHY THIS MODULE EXISTS
 *
 * There were six answers to that question in the tree and two of them
 * were wrong (audit 2026-07-30):
 *
 *   - `league-analysis.js` carried `STARTER_SLOTS = { QB: 2, RB: 3,
 *     WR: 4, TE: 2, DL: 2, LB: 2, DB: 2 }` — a per-position top-N with
 *     DL/LB/DB at 2 where the league starts 3 of each. It counted 17
 *     slots against a real 20 (21 minus K, which never enters), dropping
 *     the 3rd DL, 3rd LB and 3rd DB from every team on /rosters
 *     "Starters only". Replaying both models over the 2026-07-30 roster
 *     snapshot: every team undercounted, mean 10.1%, and because the
 *     error is roster-dependent the leaderboard REORDERS — 7 of 12
 *     teams move, including #2 <-> #4. (Measured on the snapshot's
 *     `_finalAdjusted` composite, the closest offline proxy for the
 *     served board; the exact percentages shift with the value scale,
 *     the missing slots and the reordering do not.)
 *   - It was also a single-league literal. Starter counts are
 *     leagueKey-scoped (CLAUDE.md, "Rankings vs. league context"), and
 *     the two live leagues share a scoring profile while running
 *     completely different lineups: `dynasty_main` is 12-team IDP with
 *     TE 2; `dynasty_new` is 10-team, no IDP, TE 1.
 *
 * TRUTH PRECEDENCE — live host first, registry second, never a literal.
 * `sleeper.rosterPositions` is what the league actually runs and is
 * already stamped per-league on the contract; `rosterSettings.starters`
 * in the registry is operator-maintained and known to drift. That is
 * the precedence the BDVM layer already set (`src/bdvm/league_config.py`),
 * and this follows it rather than inventing a second convention.
 *
 * A per-position top-N cannot express this league's lineup anyway: 3 of
 * its 21 slots are FLEX/SUPER_FLEX, so "how many WRs start" is not a
 * constant — it depends on who else is on the roster. Hence a fill, not
 * a count.
 *
 * VOCABULARY
 *
 * Callers supply `positionOf`, so this works on either position
 * vocabulary in the tree: portfolio-insights collapses DB/LB/DL/DE/DT/
 * CB/S → "IDP", while league-analysis's `posGroup` keeps DL/LB/DB
 * distinct. Both resolve, because the IDP pools below carry the generic
 * "IDP" token AND the specific ones. The distinct vocabulary is
 * strictly better: with it, a DL slot matches only defensive linemen,
 * where the collapsed vocabulary credits the top 9 defenders regardless
 * of whether the roster can actually fill 3 DL + 3 LB + 3 DB.
 */

// Which player positions can fill each Sleeper lineup slot. Without
// full coverage an unrecognized alias like WRRB_FLEX would fall
// through the strict pass, never match any player, and push valid
// starters onto the bench — skewing starter-share metrics.
const OFFENSE_FLEX = new Set(["RB", "WR", "TE"]);
const WR_RB_FLEX_POOL = new Set(["RB", "WR"]);
const WR_TE_FLEX_POOL = new Set(["WR", "TE"]);
const SUPER_FLEX_POOL = new Set(["QB", "RB", "WR", "TE"]);
const IDP_POOL = new Set(["IDP", "DL", "DE", "DT", "LB", "DB", "CB", "S"]);

export const FLEX_POOLS = {
  // Offense: all known Sleeper aliases → the same pool.
  FLEX: OFFENSE_FLEX,
  // RB/WR (no TE)
  WR_RB_FLEX: WR_RB_FLEX_POOL,
  WRRB_FLEX: WR_RB_FLEX_POOL,
  RB_WR_FLEX: WR_RB_FLEX_POOL,
  RBWR_FLEX: WR_RB_FLEX_POOL,
  // WR/TE
  REC_FLEX: WR_TE_FLEX_POOL,
  WR_TE_FLEX: WR_TE_FLEX_POOL,
  WRTE_FLEX: WR_TE_FLEX_POOL,
  WRT: WR_TE_FLEX_POOL,
  // Superflex (QB-eligible)
  SUPER_FLEX: SUPER_FLEX_POOL,
  SUPERFLEX: SUPER_FLEX_POOL,
  Q_FLEX: SUPER_FLEX_POOL,
  QB_RB_WR_TE: SUPER_FLEX_POOL,
  // IDP — both specific slot names and flex aliases.
  DL: new Set(["IDP", "DL", "DE", "DT"]),
  DE: new Set(["IDP", "DE", "DL"]),
  DT: new Set(["IDP", "DT", "DL"]),
  LB: new Set(["IDP", "LB"]),
  DB: new Set(["IDP", "DB", "CB", "S"]),
  CB: new Set(["IDP", "CB", "DB"]),
  S: new Set(["IDP", "S", "DB"]),
  IDP: IDP_POOL,
  IDP_FLEX: IDP_POOL,
  DB_LB: IDP_POOL,
  DL_LB: IDP_POOL,
  DL_DB: IDP_POOL,
  DEF_FLEX: IDP_POOL,
};

// Strict slots (no flex pool entry): these match a single normalized
// player position token exactly. K and DEF do not collapse into a flex
// pool; their slots match same-named rosters and nothing else.
const STRICT_SLOT_REMAP = {
  PK: "K",
};

const DL_FAMILY = new Set(["DL", "DE", "DT", "EDGE", "NT"]);
const LB_FAMILY = new Set(["LB", "OLB", "ILB"]);
const DB_FAMILY = new Set(["DB", "CB", "S", "FS", "SS"]);

/**
 * A player position resolved to the token that fills a lineup slot.
 *
 * THE single position vocabulary for lineup purposes. Defensive players
 * resolve to their FAMILY — DL, LB or DB, kept distinct — because this
 * league starts 3 at each of those positions, not 9 defenders. Anything
 * else (QB/RB/WR/TE/K/DEF) passes through `normalizePos` unchanged so a
 * K slot still matches a kicker and a DEF slot a team defense.
 *
 * Keeping DL/LB/DB distinct is the whole point. `FLEX_POOLS.DL`, `.LB`
 * and `.DB` each also contain the generic "IDP" token for backward
 * compatibility, so a caller that hands in an IDP-collapsed vocabulary
 * still matches *something* — but every defensive slot then matches
 * every defender, and the fill degrades to "top N defenders by value".
 * On a roster stacked at one IDP position that starts players the
 * league has no slot for. Callers should resolve through here.
 */
export function lineupPosition(pos) {
  const p = normalizePos(pos);
  if (DL_FAMILY.has(p)) return "DL";
  if (LB_FAMILY.has(p)) return "LB";
  if (DB_FAMILY.has(p)) return "DB";
  // ``normalizePos`` maps P -> K but not PK; portfolio-insights' local
  // helper mapped PK and this must not lose it, or a kicker stops
  // matching the league's K slot.
  if (p === "PK") return "K";
  return p;
}

// Slots that are not part of the starting lineup.
const NON_LINEUP_SLOTS = new Set(["BN", "IR", "TAXI"]);

/**
 * The starting-lineup slots from a Sleeper `rosterPositions` array.
 * Returns [] for a missing or empty array — callers decide what an
 * absent lineup means for them rather than inheriting a default from
 * here (see `fillLineup`'s `available` flag).
 */
export function lineupSlots(sleeperRosterPositions) {
  if (!Array.isArray(sleeperRosterPositions) || sleeperRosterPositions.length === 0) {
    return [];
  }
  return sleeperRosterPositions
    .map((p) => String(p).toUpperCase())
    .filter((p) => !NON_LINEUP_SLOTS.has(p));
}

function normalizeSlot(slot) {
  const upper = String(slot).toUpperCase();
  return STRICT_SLOT_REMAP[upper] ?? upper;
}

// The order a lineup reads in, so `assignments` renders like the league's
// own lineup card rather than in whatever order the registry map happened
// to serialize.
const SLOT_DISPLAY_ORDER = [
  "QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF",
  "DL", "LB", "DB", "IDP_FLEX",
];

// The registry spells superflex `SFLEX`; Sleeper spells it `SUPER_FLEX`,
// which is the spelling FLEX_POOLS knows. Without this the slot falls
// through to the strict pass, matches a position token nobody has, and
// silently goes unfilled — one fewer starter, no error.
const REGISTRY_SLOT_ALIASES = {
  SFLEX: "SUPER_FLEX",
  SUPERFLEX: "SUPER_FLEX",
};

/**
 * Expand a registry `rosterSettings.starters` map into a slot array.
 *
 * `{QB: 1, RB: 2, ..., SFLEX: 1, DL: 3}` → `["QB","RB","RB",…,"SUPER_FLEX",…,"DL","DL","DL"]`,
 * i.e. the same shape Sleeper's `rosterPositions` arrives in, so both can
 * feed `fillLineup` unchanged.
 *
 * This is the SECOND rung of the truth ladder: live `rosterPositions`
 * first, this next, and refusal after that — never a literal. See the
 * module docstring.
 */
export function slotsFromStarterCounts(starters) {
  if (!starters || typeof starters !== "object") return [];
  const entries = Object.entries(starters)
    .map(([slot, n]) => {
      const upper = String(slot).toUpperCase();
      return [REGISTRY_SLOT_ALIASES[upper] ?? upper, Number(n) || 0];
    })
    .filter(([, n]) => n > 0);
  entries.sort((a, b) => {
    const ia = SLOT_DISPLAY_ORDER.indexOf(a[0]);
    const ib = SLOT_DISPLAY_ORDER.indexOf(b[0]);
    // Unknown slots keep their relative order, after the known ones.
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  });
  const out = [];
  for (const [slot, n] of entries) {
    for (let i = 0; i < n; i += 1) out.push(slot);
  }
  return out;
}

/**
 * Fill a league's lineup slots greedily by value.
 *
 * Two passes so flex slots fill AFTER strict-position slots have
 * already claimed the appropriate starters. All slot-to-position
 * matching routes through FLEX_POOLS for anything flex-y, including the
 * IDP slot family (DL/LB/DB/IDP_FLEX/…).
 *
 * @param {object}   opts
 * @param {object[]} opts.assets      - any shape; read only via the two
 *   accessors below
 * @param {string[]} opts.rosterPositions - the league's Sleeper slot array
 * @param {Function} opts.positionOf  - asset → normalized position token
 * @param {Function} [opts.valueFor]  - asset → number. Defaults to
 *   `p.value`. PASS IT if your assets name the field something else:
 *   `league-analysis`'s player-meta entries carry `.meta`, and a
 *   `.value` default silently returns NaN for all of them, which makes
 *   the sort a no-op and fills slots in insertion order instead of by
 *   value. That is a wrong answer that looks like a right one.
 * @param {string[]} [opts.fallbackSlots] - slots to use when
 *   `rosterPositions` is absent. OMIT IT to get `available: false`
 *   instead of an invented lineup — see below.
 *
 * @returns {{ starters, bench, slotCount, unfilledSlots, available }}
 *   `available` is false when no lineup was supplied and no fallback
 *   was given. In that state `starters` is empty and `bench` is
 *   everything — deliberately, so a caller cannot mistake "we don't
 *   know this league's lineup" for "this team starts nobody". The old
 *   silent default here was a 9-slot non-IDP lineup, which undercounted
 *   an IDP league by 12 slots without saying so.
 */
export function fillLineup({
  assets,
  rosterPositions,
  positionOf,
  valueFor = (p) => p?.value,
  fallbackSlots = null,
}) {
  const scored = (assets || []).map((a) => {
    const v = Number(valueFor(a));
    return { asset: a, value: Number.isFinite(v) ? v : 0 };
  });
  scored.sort((a, b) => b.value - a.value);
  const pool = scored.map((s) => s.asset);
  let slots = lineupSlots(rosterPositions);
  let available = slots.length > 0;
  // Distinct from `available`, which goes true again once a fallback is
  // applied. A caller that renders the lineup needs to know the
  // difference between "this is the league's lineup" and "this is our
  // guess at one" — collapsing them is how an offence-only default gets
  // shown as if it were an IDP league's starting nine.
  let usedFallback = false;
  if (!available) {
    if (!fallbackSlots) {
      return {
        starters: [],
        bench: pool,
        assignments: [],
        slotCount: 0,
        unfilledSlots: [],
        available: false,
        usedFallback: false,
      };
    }
    slots = lineupSlots(fallbackSlots);
    available = slots.length > 0;
    usedFallback = available;
  }

  const claimed = new Set();
  const unfilledSlots = [];
  // Slot -> asset, in the league's own slot order. `starters` below is
  // value-descending, which is the wrong order for anything that renders
  // a lineup: IDP values sit far below offense on the blended board, so
  // truncating a value-sorted list to fit a panel eats the defense
  // entirely. Callers that DISPLAY the lineup should walk `assignments`.
  const assignments = slots.map((slot) => ({ slot: normalizeSlot(slot), asset: null }));

  // First pass: strict position slots.
  assignments.forEach((a) => {
    if (FLEX_POOLS[a.slot]) return;
    const match = pool.find((p) => !claimed.has(p) && positionOf(p) === a.slot);
    if (match) {
      claimed.add(match);
      a.asset = match;
    } else {
      unfilledSlots.push(a.slot);
    }
  });
  // Second pass: flex / IDP-family slots.
  assignments.forEach((a) => {
    const eligible = FLEX_POOLS[a.slot];
    if (!eligible) return;
    const match = pool.find((p) => !claimed.has(p) && eligible.has(positionOf(p)));
    if (match) {
      claimed.add(match);
      a.asset = match;
    } else {
      unfilledSlots.push(a.slot);
    }
  });

  return {
    starters: pool.filter((p) => claimed.has(p)),
    bench: pool.filter((p) => !claimed.has(p)),
    assignments: assignments.filter((a) => a.asset),
    slotCount: slots.length,
    unfilledSlots,
    available,
    usedFallback,
  };
}

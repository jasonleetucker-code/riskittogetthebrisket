// Draft-capital "stack" valuation for stack-aware trade verdicts.
//
// WHY THIS EXISTS
// ---------------
// A pick's strategic worth depends on the receiving team's existing
// draft capital (a clearly-biggest stack can outbid the field for the
// #1 rookie; an already-dominant stack saturates).  To fold that into
// a trade's fairness verdict we need, for every pick that can appear in
// a trade, a single auction-dollar value on the league's $1200 scale,
// and each team's total owned-pick auction stack.
//
// THE TIER↔SLOT PROBLEM
// ---------------------
// The draft-capital board assigns *slot* picks (`2026 Pick 1.03`) from
// last year's standings until the season starts, each with its own
// auction $.  But ranking sources express future picks as *tiers*
// (`2027 Early 1st`).  Per product spec, a tier's auction $ is the
// AVERAGE of the slot picks in its third of the round — e.g. a 12-team
// `Early 1st` = avg($ of 1.01–1.04) — scaled to team count, per round,
// then year-discounted for future classes.  The year discount is NOT
// re-derived here (the backend owns it): we read it off the board as
// the ratio of the future tier's board value to the current draft
// year's equivalent, so it stays self-rolling and in lockstep.
//
// "Stack" = every pick a team owns across all years (decision: all
// owned picks, all years).  The upcoming draft's slots come from the
// owner-attributed draft-capital payload (the authority for assigned
// slots); future-year picks come from Sleeper roster ownership.

const TIER_RE = /^(20\d{2})\s+(Early|Mid|Late)\s+([1-9])(?:st|nd|rd|th)\b/i;
const SLOT_RE = /^(20\d{2})\s+Pick\s+(\d+)\.(\d+)\b/i;
const ROUND_RE = /^(20\d{2})\s+(?:Pick\s+)?(\d+)(?:st|nd|rd|th)\b/i;

// Parse any pick asset name into { year, round, tier|null, slot|null }.
// Returns null for non-pick names.
export function parsePickAsset(name) {
  const s = String(name || "").trim();
  let m = s.match(SLOT_RE);
  if (m) {
    return { year: +m[1], round: +m[2], tier: null, slot: +m[3] };
  }
  m = s.match(TIER_RE);
  if (m) {
    return {
      year: +m[1],
      round: +m[3],
      tier: m[2].replace(/^[a-z]/, (c) => c.toUpperCase()).toLowerCase(),
      slot: null,
    };
  }
  m = s.match(ROUND_RE);
  if (m) {
    return { year: +m[1], round: +m[2], tier: null, slot: null };
  }
  return null;
}

// Inclusive [start, end] slot range (1-based) for a tier within a round
// of `teamsPerRound` slots.  Equal thirds; an indivisible remainder
// goes to Mid first, then Late (decision).  12 → Early 1-4/Mid 5-8/
// Late 9-12; 10 → 1-3 / 4-7 / 8-10; 14 → 1-4 / 5-9 / 10-14.
export function tierSlotRange(tier, teamsPerRound) {
  const T = Math.max(1, Math.floor(teamsPerRound) || 0);
  const base = Math.floor(T / 3);
  const rem = T - base * 3; // 0, 1, or 2
  const earlyN = base;
  const midN = base + (rem >= 1 ? 1 : 0);
  const lateN = base + (rem >= 2 ? 1 : 0);
  // When base is 0 (tiny leagues) fall back to whole round.
  if (earlyN + midN + lateN !== T || base === 0) return [1, T];
  const t = String(tier || "").toLowerCase();
  if (t === "early") return [1, earlyN];
  if (t === "mid") return [earlyN + 1, earlyN + midN];
  return [earlyN + midN + 1, T]; // late
}

// Positional slot-$ grid from the draft-capital payload:
// gridByRound[round] = { [slot]: dollarValue }.  These are the upcoming
// draft's per-slot dollars (owner-independent positionally).
// Keyed by YEAR → round → slot.  The Sleeper-derived payload spans two
// seasons with colliding (round, slot) pairs, so each row's own
// ``season`` disambiguates it; the workbook payload is single-season
// (no per-row season) so it falls back to ``draftCapital.season``.
export function buildSlotDollarGrid(draftCapital) {
  const grid = {};
  const picks = draftCapital?.picks;
  if (!Array.isArray(picks)) return grid;
  const fallbackYear = Number(draftCapital?.season);
  for (const p of picks) {
    const year = Number(p?.season ?? fallbackYear);
    const round = Number(p?.round);
    const slot = Number(p?.pickInRound ?? p?.slot);
    const dollar = Number(p?.dollarValue);
    if (!year || !round || !slot || !Number.isFinite(dollar)) continue;
    ((grid[year] ||= {})[round] ||= {})[slot] = dollar;
  }
  return grid;
}

function avg(nums) {
  const v = nums.filter((n) => Number.isFinite(n));
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : 0;
}

// Year-discount factor for a future class, read off the board so it
// stays in lockstep with the backend's self-rolling discount.  Returns
// 1.0 for the current draft year or when the board can't disambiguate.
function yearDiscountFactor(parsed, currentDraftYear, boardValueByName) {
  if (!currentDraftYear || parsed.year <= currentDraftYear) return 1.0;
  if (typeof boardValueByName !== "function") return 1.0;
  const tierWord = parsed.tier
    ? parsed.tier[0].toUpperCase() + parsed.tier.slice(1)
    : null;
  const ord = (r) => `${r}${["th", "st", "nd", "rd"][r] || "th"}`;
  const suffix = tierWord
    ? `${tierWord} ${ord(parsed.round)}`
    : `Pick ${parsed.round}.01`;
  const future = boardValueByName(`${parsed.year} ${suffix}`);
  const current = boardValueByName(`${currentDraftYear} ${suffix}`);
  if (future > 0 && current > 0) return future / current;
  return 1.0;
}

// Auction-dollar value of any pick asset on the $1200 scale.
//   ctx = { slotGrid (year→round→slot), teamsPerRound,
//           currentDraftYear, boardValueByName }
// An explicit slot whose YEAR is actually present in the payload uses
// that exact (year, round, slot) dollar.  Everything else (tiers,
// round-only, future years not in the payload) is the slot-average of
// the anchor (current-draft) year's round, year-discounted.
export function pickAuctionDollars(name, ctx) {
  const parsed = parsePickAsset(name);
  if (!parsed) return 0;
  const {
    slotGrid = {},
    teamsPerRound = 12,
    currentDraftYear = null,
    boardValueByName,
  } = ctx || {};

  // Exact: the pick's own year is in the payload and it's a real slot.
  if (parsed.slot != null) {
    const exact = slotGrid[parsed.year]?.[parsed.round]?.[parsed.slot];
    if (Number.isFinite(exact) && exact > 0) return exact;
  }

  // Otherwise anchor on the active draft year's positional $ grid.
  const anchor =
    currentDraftYear != null && slotGrid[currentDraftYear]
      ? currentDraftYear
      : Number(Object.keys(slotGrid)[0]);
  const roundGrid = slotGrid[anchor]?.[parsed.round] || {};
  const allSlots = Object.keys(roundGrid).map(Number);
  let slots;
  if (parsed.slot != null) {
    slots = [parsed.slot];
  } else if (parsed.tier) {
    const [lo, hi] = tierSlotRange(parsed.tier, teamsPerRound);
    slots = allSlots.filter((s) => s >= lo && s <= hi);
  } else {
    slots = allSlots; // round-only → whole-round average
  }
  const base = avg(slots.map((s) => roundGrid[s]));
  if (base <= 0) return 0;
  return base * yearDiscountFactor(parsed, currentDraftYear, boardValueByName);
}

// Per-team total owned-pick auction stack across ALL league teams.
// Upcoming-draft slots: summed from the owner-attributed draft-capital
// payload (the authority).  Future-year picks: from Sleeper roster
// ownership, valued via the tier/slot-average rule.  `pickRowsByTeam`
// maps team name → array of future-year pick asset names that team owns
// (already excludes the upcoming-draft year to avoid double counting).
export function buildLeagueStacks(draftCapital, pickRowsByTeam, ctx) {
  const stacks = {};
  for (const t of draftCapital?.teamTotals || []) {
    const team = t?.team;
    if (team == null) continue;
    stacks[team] = Number(t.auctionDollars) || 0; // upcoming draft $
  }
  for (const [team, names] of Object.entries(pickRowsByTeam || {})) {
    if (!(team in stacks)) stacks[team] = 0;
    for (const nm of names) {
      stacks[team] += pickAuctionDollars(nm, ctx);
    }
  }
  return stacks;
}

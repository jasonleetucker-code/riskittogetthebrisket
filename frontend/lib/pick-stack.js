// Draft-capital "stack" valuation.  INFORMATIONAL ONLY: the stack effect
// is withdrawn from trade totals, the verdict, flows and balancers (owner
// directive 2026-09-29; __tests__/trade-stack-withdrawn.test.js).  The
// "fold into a verdict" motivation below is the original design intent,
// kept as history; the rebuild prerequisites are issue #1529.
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

// The league draft pool's exchange rate between auction dollars and
// board value: sum of the board values of the draft's own picks divided
// by the dollars those same picks carry.  ONE rate per league board, so
// the picks a particular trade happens to move cannot set it (owner
// decision 2026-09-29: the previous per-trade rate priced every dollar
// of league-wide premium at a $1 sixth-rounder's ~1,300 points per $).
// Each pick resolves to its slot row ("2027 Pick 5.03"), else its tier
// row ("2027 Mid 5th"); a pick with no positive dollars or no board row
// is left out of BOTH sums.  ``null`` when nothing pairs -- the stack
// effect is then withheld, never priced at a guessed rate.
export function poolBoardPerDollar(draftCapital, boardValueByName, teamsPerRound = 12) {
  const picks = draftCapital?.picks;
  if (!Array.isArray(picks) || typeof boardValueByName !== "function") return null;
  const fallbackYear = Number(draftCapital?.season);
  const ord = (r) => `${r}${["th", "st", "nd", "rd"][r] || "th"}`;
  let board = 0;
  let dollars = 0;
  for (const p of picks) {
    const year = Number(p?.season ?? fallbackYear);
    const round = Number(p?.round);
    const slot = Number(p?.pickInRound ?? p?.slot);
    const dollar = Number(p?.dollarValue);
    if (!year || !round || !slot || !(Number.isFinite(dollar) && dollar > 0)) continue;
    let value = Number(boardValueByName(`${year} Pick ${round}.${String(slot).padStart(2, "0")}`));
    if (!(Number.isFinite(value) && value > 0)) {
      const tier = ["early", "mid", "late"].find((t) => {
        const [lo, hi] = tierSlotRange(t, teamsPerRound);
        return slot >= lo && slot <= hi;
      });
      if (tier) {
        const word = tier[0].toUpperCase() + tier.slice(1);
        value = Number(boardValueByName(`${year} ${word} ${ord(round)}`));
      }
    }
    if (!(Number.isFinite(value) && value > 0)) continue;
    board += value;
    dollars += dollar;
  }
  return dollars > 0 && board > 0 ? board / dollars : null;
}

// The draft year the stack anchors on: THIS LEAGUE's upcoming draft.
//
// Wave A (owner directive 2026-10-03): the stack is a league-scoped, team-
// attributed view, so it anchors on the LEAGUE-scoped canonical answer the
// draft-capital payload carries (``upcomingDraftYear``, from
// ``src/identity/pick_lifecycle.py::league_draft_years``) -- never on the
// BOARD's ``pickClassLifecycle.firstActiveClass``, which stays on a class
// until EVERY league sharing the board retires it.  Reading the board's year
// here is what anchored the stack on 2026 while this league's draft capital
// was 2027's.  The contract fields remain fallbacks for payloads that predate
// the stamp.
export function pickStackAnchorYear(contract, draftCapital) {
  const upcoming = Number(draftCapital?.upcomingDraftYear);
  if (Number.isFinite(upcoming) && upcoming > 2000) return upcoming;
  const fromDC = parseInt(String(draftCapital?.season || ""), 10);
  if (Number.isFinite(fromDC) && fromDC > 2000) return fromDC;
  const board = Number(contract?.pickClassLifecycle?.firstActiveClass);
  if (Number.isFinite(board) && board > 2000) return board;
  const fromContract = Number(contract?.currentDraftYear);
  return Number.isFinite(fromContract) && fromContract > 2000 ? fromContract : null;
}

// One stable key per league team, shared by the draft-capital payload's
// ``teamTotals`` rows (``rosterId``) and ``sleeper.teams`` (``roster_id``).
// The two name their teams differently (Sleeper team name vs owner first
// name), so a name join silently split one team into two stacks.  A row
// without a roster id falls back to its name.
export function teamStackKey(team) {
  if (!team) return null;
  const rid = team.rosterId ?? team.roster_id;
  if (rid != null && rid !== "" && Number.isFinite(Number(rid))) return `roster:${Number(rid)}`;
  const name = team.team ?? team.name;
  return name == null ? null : String(name);
}

// assetId -> owning team key, from the canonical ownership fold as published
// on ``sleeper.teams[].pickDetails[].assetId``.  An id two teams both claim is
// ``null`` (unknown) -- never "whichever team was read last".
export function pickOwnerKeyByAssetId(sleeperTeams) {
  const owners = new Map();
  for (const team of sleeperTeams || []) {
    const key = teamStackKey(team);
    for (const d of Array.isArray(team?.pickDetails) ? team.pickDetails : []) {
      const id = d?.assetId ? String(d.assetId) : "";
      if (!id || key == null) continue;
      owners.set(id, owners.has(id) && owners.get(id) !== key ? null : key);
    }
  }
  return owners;
}

// Every REAL pick the draft-capital ``teamTotals`` do not already count, per
// team key, each exactly once.
//   * a season in ``coveredPickYears`` is already in teamTotals;
//   * a pick whose canonical ``assetId`` appears on a draft-capital pick row
//     is already in teamTotals, whatever the year bookkeeping says;
//   * an ``assetId`` seen on a second team is not counted again.
// ``resolveRow(label)`` maps a Sleeper pick label to its board row.
// Returns ``{ byTeam: {key: [boardRowName, ...]}, duplicateIds: [...] }``.
export function ownedPickStackInventory(sleeperTeams, draftCapital, resolveRow) {
  const covered = new Set(
    (Array.isArray(draftCapital?.coveredPickYears) ? draftCapital.coveredPickYears : [])
      .map(Number)
      .filter((y) => Number.isFinite(y)),
  );
  const coveredIds = new Set(
    (Array.isArray(draftCapital?.picks) ? draftCapital.picks : [])
      .map((p) => (p?.assetId ? String(p.assetId) : ""))
      .filter(Boolean),
  );
  const seen = new Set();
  const duplicateIds = [];
  const byTeam = {};
  for (const team of sleeperTeams || []) {
    const key = teamStackKey(team);
    if (key == null) continue;
    const details = Array.isArray(team?.pickDetails) ? team.pickDetails : null;
    const entries = details
      ? details.map((d) => ({
          label: d?.label || d?.baseLabel || "",
          season: Number(d?.season),
          id: d?.assetId ? String(d.assetId) : "",
        }))
      : (Array.isArray(team?.picks) ? team.picks : []).map((label) => ({
          label,
          season: NaN,
          id: "",
        }));
    const out = [];
    for (const e of entries) {
      if (e.id) {
        if (coveredIds.has(e.id)) continue;
        if (seen.has(e.id)) {
          duplicateIds.push(e.id);
          continue;
        }
        seen.add(e.id);
      }
      const row = typeof resolveRow === "function" ? resolveRow(e.label) : null;
      if (!row) continue;
      const year = Number.isFinite(e.season) ? e.season : parsePickAsset(row.name)?.year;
      if (year == null || covered.has(year)) continue;
      out.push(row.name);
    }
    if (out.length) byTeam[key] = out;
  }
  return { byTeam, duplicateIds };
}

// The trade's pick moves between TEAM stacks.  Team-attributed, so only a
// real owned pick (canonical ``assetId``) held by the sending side's team
// moves a stack (Wave A):
//   * a generic pick (no ``assetId``) is hypothetical -- it never debits a
//     team's real inventory;
//   * an owned pick the sending team does not hold is reported in
//     ``notOwned`` (with the actual owner key) and moves nothing;
//   * a repeated copy of the same owned pick counts once.
// ``destinationOf(sideIdx, asset)`` returns the receiving side index (or
// null); ``dollarsOf(asset)`` its auction dollars.
export function stackPickMoves(sides, { sideTeamKeys, ownerKeyByAssetId, destinationOf, dollarsOf }) {
  const moves = [];
  const notOwned = [];
  const hypothetical = [];
  const seen = new Set();
  (sides || []).forEach((s, i) => {
    for (const a of s?.assets || []) {
      if (a?.assetClass !== "pick") continue;
      const id = a.assetId ? String(a.assetId) : "";
      if (!id) {
        hypothetical.push(a.name);
        continue;
      }
      if (seen.has(id)) continue;
      seen.add(id);
      const owner = ownerKeyByAssetId?.get(id) ?? null;
      const sender = sideTeamKeys?.[i] ?? null;
      if (owner == null || sender == null || owner !== sender) {
        notOwned.push({ assetId: id, label: a.assetLabel || a.name, side: i, ownerKey: owner });
        continue;
      }
      const to = destinationOf(i, a);
      if (to == null || to === i) continue;
      moves.push({ from: i, to, dollars: dollarsOf(a) });
    }
  });
  return { moves, notOwned, hypothetical };
}

function avg(nums) {
  const v = nums.filter((n) => Number.isFinite(n));
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : 0;
}

// Year-discount factor for a future class, read off the board so it
// stays in lockstep with the backend's self-rolling discount.  Returns
// 1.0 for the current draft year or when the board can't disambiguate.
//
// The denominator must be the CURRENT class's value on the board's
// scale.  When the active class has slot-specific rows the backend
// suppresses the generic current-year tier row ("2026 Early 1st"), so
// reading that row would give 0 / a stale value and skip or skew the
// discount.  For tiers we therefore average the authoritative
// current-year SLOT rows in that tier's third (same board scale as the
// future generic-tier numerator), falling back to the generic tier row
// only when no slot rows resolve (pre-assignment leagues).
function yearDiscountFactor(parsed, currentDraftYear, boardValueByName, teamsPerRound) {
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

  let current;
  if (tierWord) {
    const [lo, hi] = tierSlotRange(parsed.tier, teamsPerRound || 12);
    const slotVals = [];
    for (let s = lo; s <= hi; s += 1) {
      const v = boardValueByName(
        `${currentDraftYear} Pick ${parsed.round}.${String(s).padStart(2, "0")}`,
      );
      if (Number.isFinite(v) && v > 0) slotVals.push(v);
    }
    current = slotVals.length
      ? avg(slotVals)
      : boardValueByName(`${currentDraftYear} ${suffix}`);
  } else {
    // Non-tier (round-only) already references an authoritative slot row.
    current = boardValueByName(`${currentDraftYear} ${suffix}`);
  }

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
  return (
    base *
    yearDiscountFactor(parsed, currentDraftYear, boardValueByName, teamsPerRound)
  );
}

// Per-team total owned-pick auction stack across ALL league teams, keyed by
// ``teamStackKey``.  Covered seasons: the draft-capital payload's
// ``teamTotals`` (the authority).  Every other real pick: from
// ``ownedPickStackInventory`` (which already excludes covered seasons and
// ids, and duplicates), valued via the tier/slot-average rule.
// `pickRowsByTeam` maps team key -> array of pick board-row names.
export function buildLeagueStacks(draftCapital, pickRowsByTeam, ctx) {
  const stacks = {};
  for (const t of draftCapital?.teamTotals || []) {
    const team = teamStackKey(t);
    if (team == null) continue;
    stacks[team] = (stacks[team] || 0) + (Number(t.auctionDollars) || 0); // covered $
  }
  for (const [team, names] of Object.entries(pickRowsByTeam || {})) {
    if (!(team in stacks)) stacks[team] = 0;
    for (const nm of names) {
      stacks[team] += pickAuctionDollars(nm, ctx);
    }
  }
  return stacks;
}

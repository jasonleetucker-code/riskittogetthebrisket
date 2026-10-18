// Draft Capital year selector — URL state + selection over backend views.
//
// Owner request 2026-10-01: the /league Draft Capital tab gains an
// "All Years | <season>..." selector.  The selector changes WHICH picks are
// shown, never HOW they are valued, and this module values nothing:
//
//   * the season list is the backend's `availableYears` (derived from the
//     pick inventory, so a completed class disappears and a new one appears
//     with no change here — no year is hard-coded);
//   * a season's per-team capital and ranking are the backend's
//     `teamTotalsByYear[season]` (src/api/draft_capital_years.py), which
//     SUMS the same per-pick dollars the all-years total is made of — never
//     re-spread client-side.  Each draft class is its own $1200 pool (owner
//     decision 2026-10-18, "$1,200 per draft class"), on every league;
//   * "All Years" is the backend's `allYearsTeamTotals` — every class the
//     year views cover, each pick once — falling back to `teamTotals` on a
//     payload that predates it.
//
// Owner directive 2026-10-17: every Sleeper draft class the league still owns
// picks in is listed.  Both builders carry the upcoming class in `picks`;
// the others arrive in `additionalClassPicks` (Sleeper ownership + canonical
// values) and are part of every view here except `teamTotals`, which stays
// the upcoming auction's budgets for /draft and /trade.
//
// When the payload predates the per-season views (a deploy-skew window), no
// season is offered and the page stays on All Years rather than re-deriving
// capital client-side.

export const DRAFT_CAPITAL_YEAR_PARAM = "year";
export const ALL_YEARS = "all";

function asSeason(v) {
  const s = typeof v === "string" ? v.trim() : v;
  if (s === "" || s === null || s === undefined) return null;
  if (typeof s === "string" && !/^\d{4}$/.test(s)) return null;
  const n = Number(s);
  return Number.isInteger(n) ? n : null;
}

/** Seasons the payload can show a per-season view for, ascending. */
export function availableDraftCapitalYears(data) {
  const years = data?.availableYears;
  const views = data?.teamTotalsByYear;
  if (!Array.isArray(years) || !views || typeof views !== "object") return [];
  const out = [];
  for (const y of years) {
    const n = asSeason(y);
    if (n !== null && Array.isArray(views[String(n)]) && !out.includes(n)) out.push(n);
  }
  return out.sort((a, b) => a - b);
}

/**
 * `?year=` → a season, or null for All Years.  Anything that is not one of
 * the available seasons — garbage, a retired class, a season the payload
 * does not carry — falls back to All Years rather than an empty page.
 */
export function parseDraftCapitalYear(raw, availableYears) {
  const n = asSeason(raw);
  if (n === null) return null;
  return (availableYears || []).includes(n) ? n : null;
}

/** A season → its `?year=` value; All Years removes the param. */
export function serializeDraftCapitalYear(year) {
  const n = asSeason(year);
  return n === null ? null : String(n);
}

/** Team rows for the selected view; All Years spans every listed class. */
export function draftCapitalTeamRows(data, year) {
  if (year === null || year === undefined) {
    const all = data?.allYearsTeamTotals;
    return Array.isArray(all) ? all : data?.teamTotals || [];
  }
  const rows = data?.teamTotalsByYear?.[String(year)];
  return Array.isArray(rows) ? rows : [];
}

/**
 * Every owned pick on the board: the builder's `picks` plus the classes its
 * `teamTotals` do not cover.  Each pick appears once — the two arrays never
 * share a class.
 */
export function draftCapitalAllPicks(data) {
  const base = Array.isArray(data?.picks) ? data.picks : [];
  const extra = Array.isArray(data?.additionalClassPicks) ? data.additionalClassPicks : [];
  return extra.length ? [...base, ...extra] : base;
}

/** Picks belonging to `year` (All Years → every pick). */
export function draftCapitalPicksForYear(picks, year, boardSeason) {
  const all = Array.isArray(picks) ? picks : [];
  if (year === null || year === undefined) return all;
  return all.filter((p) => Number(p?.season ?? boardSeason) === Number(year));
}

/** League-level summary for a season (All Years → `allYearsSummary`), or null. */
export function draftCapitalYearSummary(data, year) {
  if (year === null || year === undefined) return data?.allYearsSummary || null;
  return data?.yearSummaries?.[String(year)] || null;
}

/**
 * The budget basis the payload's dollars were computed on.  ONE basis exists
 * (owner decision 2026-10-18, src/api/draft_capital_classes.py): each draft
 * class is its own pool and All Years adds the classes.  `perClass: false`
 * only reads a LEGACY payload (no `budgetPolicy`, or the retired shared-pool
 * basis) served across a deploy-skew window; the page then states no
 * multi-class basis at all rather than describing a retired policy.
 */
function finiteOrNull(value) {
  const n = Number(value);
  return value != null && Number.isFinite(n) ? n : null;
}

export function draftCapitalBudgetPolicy(data) {
  const bp = data?.budgetPolicy;
  // An absent budget stays null (rendered as "budget unknown"), never $0.
  const budget = finiteOrNull(bp?.budget ?? data?.totalBudget);
  if (bp?.basis === "per_class_pool") {
    const allYears = finiteOrNull(bp.allYearsBudget);
    return {
      perClass: true,
      budget,
      allYearsBudget: allYears ?? budget,
      // Classes holding priced dollars (a class the board cannot price at
      // all is in `unpricedClasses` and outside `allYearsBudget`).
      pricedClassCount:
        Array.isArray(bp.seasons) && Array.isArray(bp.unpricedClasses)
          ? bp.seasons.length - bp.unpricedClasses.length
          : null,
      decided: bp.status === "owner_confirmed",
      note: bp.note || null,
    };
  }
  return {
    perClass: false,
    budget,
    allYearsBudget: budget,
    pricedClassCount: null,
    decided: false,
    note: null,
  };
}

/**
 * A pick has no value we can show: the builder could not price it.  Never
 * coerced to $0 — MISSING IS NEVER ZERO.
 */
export function isUnpricedPick(p) {
  if (p?.isUnpriced === true) return true;
  const v = p?.adjustedDollarValue ?? p?.dollarValue;
  return typeof v !== "number" || !Number.isFinite(v);
}

/**
 * True when a pick's slot is not a draft position: the class has no draft
 * order yet, so the row is round-only and carries the round's value.
 */
export function isSlotUnknown(p) {
  return p?.slotStatus === "unknown";
}

/** True when a pick's slot is an estimate (e.g. workbook / standings order). */
export function isSlotProjected(p) {
  return p?.slotStatus === "projected";
}

/**
 * True when the board's (or one season's) pick "slots" are not draft
 * positions.  The Sleeper-derived fallback numbers every pick by its
 * ORIGINAL roster (a stand-in), and a future class with no draft order is
 * round-only, so showing "1.05" would claim a slot nobody knows.  Pass the
 * picks on screen to answer for them; without picks it answers for the board.
 */
export function draftCapitalSlotsAreStandIns(data, picks) {
  if (data?.source === "sleeper_derived") return true;
  if (!Array.isArray(picks) || picks.length === 0) return false;
  return picks.every(isSlotUnknown);
}

/** Display label for one pick: "1.05", or round-only when the slot is unknown. */
export function draftCapitalPickLabel(p, { slotsAreStandIns = false, withSeason = false } = {}) {
  const base =
    slotsAreStandIns || isSlotUnknown(p) ? `R${p?.round}` : String(p?.pick ?? "");
  if (!withSeason || p?.season == null) return base;
  return `'${String(p.season).slice(-2)} ${base}`;
}

/** The owner-addendum (2026-10-18) label for a class on the interim curve. */
export const INTERIM_CURVE_LABEL = "provisional estimate — final rookie-auction curve pending";

/**
 * Seasons whose dollars are spread on the INTERIM generic-market curve (not
 * the workbook's rookie-auction curve), ascending.  Read from the payload's
 * per-class `budgetPolicy.classCurveMethods` when present, else from the
 * per-pick `curveMethod` of the picks on screen.
 */
export function draftCapitalInterimSeasons(data, picks) {
  const out = new Set();
  const methods = data?.budgetPolicy?.classCurveMethods;
  const onScreen = new Set(
    (Array.isArray(picks) ? picks : []).map((p) => Number(p?.season)).filter(Number.isFinite),
  );
  if (methods && typeof methods === "object") {
    for (const [season, method] of Object.entries(methods)) {
      const n = Number(season);
      if (method === "interim_generic_market" && (onScreen.size === 0 || onScreen.has(n))) {
        out.add(n);
      }
    }
  } else {
    for (const p of Array.isArray(picks) ? picks : []) {
      if (p?.curveMethod === "interim_generic_market") out.add(Number(p.season));
    }
  }
  return [...out].filter(Number.isFinite).sort((a, b) => a - b);
}

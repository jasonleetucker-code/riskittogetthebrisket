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
//     SUMS the same per-pick dollars the all-years total is made of — the
//     $1200 pool is never re-spread per season;
//   * "All Years" is the existing `teamTotals`, untouched.
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

/** Team rows for the selected view; All Years is the existing `teamTotals`. */
export function draftCapitalTeamRows(data, year) {
  if (year === null || year === undefined) return data?.teamTotals || [];
  const rows = data?.teamTotalsByYear?.[String(year)];
  return Array.isArray(rows) ? rows : [];
}

/** Picks belonging to `year` (All Years → every pick). */
export function draftCapitalPicksForYear(picks, year, boardSeason) {
  const all = Array.isArray(picks) ? picks : [];
  if (year === null || year === undefined) return all;
  return all.filter((p) => Number(p?.season ?? boardSeason) === Number(year));
}

/** League-level summary for a season, or null. */
export function draftCapitalYearSummary(data, year) {
  if (year === null || year === undefined) return null;
  return data?.yearSummaries?.[String(year)] || null;
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
 * True when the board's pick "slots" are not draft positions.  The
 * Sleeper-derived fallback numbers every pick by its ORIGINAL roster
 * (a stand-in — future draft order is unknown) and prices it at the round's
 * generic value, so showing "1.05" would claim a slot nobody knows.
 */
export function draftCapitalSlotsAreStandIns(data) {
  return data?.source === "sleeper_derived";
}

/** Display label for one pick: "1.05", or round-only when slots are stand-ins. */
export function draftCapitalPickLabel(p, { slotsAreStandIns = false, withSeason = false } = {}) {
  const base = slotsAreStandIns ? `R${p?.round}` : String(p?.pick ?? "");
  if (!withSeason || p?.season == null) return base;
  return `'${String(p.season).slice(-2)} ${base}`;
}

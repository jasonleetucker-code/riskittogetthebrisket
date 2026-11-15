/**
 * waiver-compare.js — pure helpers for the unlisted Waiver Wire Comparison
 * page (app/waiver-wire/[slug]).
 *
 * The backend (src/waiver_compare) owns every value: the plain 50/50
 * average of KTC Crowd+Trades and IDP Trade Calculator.  This module only
 * filters, sorts and formats what it is given.  Missing is never zero: a
 * player with no value or no age sinks to the bottom of every value/age
 * sort in BOTH directions rather than being compared as 0.
 */

export const WAIVER_PAGE_SIZE = 50;

export const POSITION_FILTERS = ["ALL", "QB", "RB", "WR", "TE", "DL", "LB", "DB"];

export const SORT_OPTIONS = [
  { value: "value_desc", label: "Value: highest first" },
  { value: "value_asc", label: "Value: lowest first" },
  { value: "age_asc", label: "Age: youngest first" },
  { value: "age_desc", label: "Age: oldest first" },
  { value: "name_asc", label: "Player name" },
];

/** Slider bounds.  The top notch (AGE_ALL) means "All ages". */
export const AGE_MIN = 21;
export const AGE_MAX = 40;
export const AGE_ALL = AGE_MAX + 1;

const isNum = (v) => typeof v === "number" && Number.isFinite(v);

function byName(a, b) {
  return String(a.name || "").localeCompare(String(b.name || ""), undefined, {
    sensitivity: "base",
  });
}

/** Numeric compare with missing values ALWAYS last, whatever the direction. */
function byNumber(field, direction) {
  return (a, b) => {
    const av = a[field];
    const bv = b[field];
    const aHas = isNum(av);
    const bHas = isNum(bv);
    if (aHas !== bHas) return aHas ? -1 : 1;
    if (aHas && av !== bv) return direction === "asc" ? av - bv : bv - av;
    return 0;
  };
}

function chain(...cmps) {
  return (a, b) => {
    for (const cmp of cmps) {
      const r = cmp(a, b);
      if (r !== 0) return r;
    }
    return String(a.id).localeCompare(String(b.id));
  };
}

const COMPARATORS = {
  value_desc: chain(byNumber("value", "desc"), byName),
  value_asc: chain(byNumber("value", "asc"), byName),
  age_asc: chain(byNumber("age", "asc"), byNumber("value", "desc"), byName),
  age_desc: chain(byNumber("age", "desc"), byNumber("value", "desc"), byName),
  name_asc: chain(byName, byNumber("value", "desc")),
};

export function sortPlayers(players, sortKey = "value_desc") {
  const cmp = COMPARATORS[sortKey] || COMPARATORS.value_desc;
  return [...players].sort(cmp);
}

export function matchesPosition(player, position) {
  if (!position || position === "ALL") return true;
  return String(player.pos || "").toUpperCase() === position;
}

/**
 * Does the player pass the waiver age limit?  `maxAge` of AGE_ALL (or
 * nullish) means no limit.  With a limit set, a player whose age is
 * unknown is EXCLUDED (we cannot say they are young enough) — the page
 * reports how many were hidden for that reason.
 */
export function matchesAge(player, maxAge) {
  if (maxAge == null || maxAge >= AGE_ALL) return true;
  if (!isNum(player.age)) return false;
  return player.age <= maxAge;
}

/** Filter + sort the WHOLE list; paging happens after, never before. */
export function selectPlayers(players, { position = "ALL", sort = "value_desc", maxAge = null } = {}) {
  const kept = [];
  let hiddenUnknownAge = 0;
  for (const p of players) {
    if (!matchesPosition(p, position)) continue;
    if (!matchesAge(p, maxAge)) {
      if (!isNum(p.age)) hiddenUnknownAge += 1;
      continue;
    }
    kept.push(p);
  }
  return { players: sortPlayers(kept, sort), hiddenUnknownAge };
}

/** Resolve ids → records, dropping ids the payload does not describe. */
export function recordsFor(ids, playersById) {
  const out = [];
  for (const id of ids || []) {
    const rec = playersById?.[id];
    if (rec) out.push(rec);
  }
  return out;
}

const VALUE_FMT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

/** "2,105.5" / "8,043" — or "N/A" when there is no value (never "0"). */
export function formatValue(v) {
  return isNum(v) ? VALUE_FMT.format(v) : "N/A";
}

export function formatAge(age) {
  return isNum(age) ? String(age) : "—";
}

export function ageLimitLabel(maxAge) {
  return maxAge == null || maxAge >= AGE_ALL ? "All ages" : `${maxAge} and younger`;
}

export function formatTimestamp(iso) {
  if (!iso) return "unknown";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "unknown";
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

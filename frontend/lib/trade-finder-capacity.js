// What a generated trade does to a roster, as words — for every generated
// trade surface: Package Builder at /angle, and on /arbitrage the Package
// Scan cards, Best Offers and the Package Builder view.  ONE display rule for
// all of them (Package Scan's own `rosterCapacityLine` is retired).
//
// Labels only.  Every count, flag and value is the backend's: the one owner is
// src/trade/roster_capacity.py, which attaches `rosterCapacity` to each
// candidate and REPORTS forced releases rather than filtering on them.  Hiding
// that block made a 2-for-1 on a full roster look free, so these surfaces must
// say who has to be released and what that costs.
//
// MISSING IS NEVER ZERO:
//   * no block at all            -> "not checked", never "fits"
//   * `unavailable`              -> "could not be checked", never "fits"
//   * `requiresDrops === null`   -> "may require a release" (unknown), never "fits"
//   * a drop with `value: null`  -> "value unknown", never 0
//   * `forcedDropValue: null`    -> "released value unknown", never 0
//   * NO PRICED DROP             -> "released value unknown", never 0.  The
//     backend sums only priced drops and publishes `forcedDropValue: 0.0`
//     when there are none (roster_capacity.py, `... if priced else 0.0`), so
//     on the real payload a 0 total beside no priced drop is an EMPTY SUM,
//     not a released value of zero.

function fmtValue(v) {
  return Math.round(Number(v)).toLocaleString("en-US");
}

const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const isCount = (v) => Number.isInteger(v) && v >= 0;
const plural = (n, one, many) => (n === 1 ? one : many);
const capitalize = (s) => s.charAt(0).toUpperCase() + s.slice(1);

function dropLines(capacity) {
  const drops = Array.isArray(capacity?.forcedDrops) ? capacity.forcedDrops : [];
  return drops.map((d, i) => {
    const name = String(d?.name || "").trim() || "Unnamed player";
    const position = d?.position ? ` (${d.position})` : "";
    return {
      key: `${d?.playerId || name}-${i}`,
      label: `${name}${position}`,
      // A drop the board cannot price is UNKNOWN — not zero, and not some
      // other number (effectiveCutCost is a different quantity).
      valueText: isNum(d?.value) ? `${fmtValue(d.value)} value` : "value unknown",
      priced: isNum(d?.value),
    };
  });
}

/**
 * The overage the roster ALREADY owed before this trade, as a sentence — or
 * null when it owed none (or the backend did not say).
 *
 * Both numbers are read straight off the backend: `overLimitBefore`, and
 * `overLimitAfter` (`overLimitAfterMax` when taxi occupancy is unknown).
 * Nothing here subtracts them: "how many releases the trade adds" has its own
 * backend definition (`roster_capacity.forced_drop_cost`), and a second one
 * in the browser would be a second owner.  "Already N over before, M over
 * after" says it with the backend's own numbers.
 */
function preexistingOverage(capacity, whose) {
  const before = capacity.overLimitBefore;
  if (!isCount(before) || before === 0) return null;
  const limit = isNum(capacity.rosterLimit) ? ` ${capacity.rosterLimit}-man` : "";
  const releases = `${before} ${plural(before, "release", "releases")}`;
  const partial = capacity.certainty === "partial" || capacity.forcedDropsAreUpperBound === true;
  if (partial) {
    const afterMax = capacity.overLimitAfterMax;
    const after = isCount(afterMax) ? `; after it, up to ${afterMax} over` : "";
    return (
      `${capitalize(whose)} may already be up to ${before} over the${limit} limit before ` +
      `this trade (taxi occupancy unknown) — up to ${releases} owed with or without it${after}.`
    );
  }
  const afterExact = capacity.overLimitAfter;
  const after = isCount(afterExact) ? `; after it, ${afterExact} over` : "";
  return (
    `${capitalize(whose)} is already ${before} over the${limit} limit before this trade — ` +
    `${releases} owed with or without it${after}.`
  );
}

/**
 * Summarise one `rosterCapacity` block.
 *
 * @param {object|null|undefined} capacity the backend's block.
 * @param {{team?: string|null}} [opts] `team` names whose roster this is (a
 *   counterparty's); omitted means the user's own roster.
 * @returns {{
 *   state: "not_checked"|"unavailable"|"unknown_limit"|"maybe"|"fits"|"requires",
 *   tone: "neutral"|"warning",
 *   headline: string,
 *   context: string|null,
 *   drops: Array<{key: string, label: string, valueText: string, priced: boolean}>,
 *   dropsLabel: string|null,
 * }}
 */
export function forcedReleaseSummary(capacity, { team = null } = {}) {
  const whose = team ? `${team}'s roster` : "your roster";
  if (!capacity || typeof capacity !== "object") {
    return {
      state: "not_checked",
      tone: "neutral",
      headline: "Roster capacity not checked for this trade — any forced release is unknown, not zero.",
      context: null,
      drops: [],
      dropsLabel: null,
    };
  }
  if (capacity.unavailable) {
    return {
      state: "unavailable",
      tone: "neutral",
      headline:
        "Roster capacity could not be checked for this trade — any forced release is unknown, not zero.",
      context: null,
      drops: [],
      dropsLabel: null,
    };
  }

  const drops = dropLines(capacity);
  const context = preexistingOverage(capacity, whose);

  if (capacity.requiresDrops === null || capacity.requiresDrops === undefined) {
    if (capacity.rosterLimit == null) {
      return {
        state: "unknown_limit",
        tone: "neutral",
        headline: "Roster limit unknown — this trade may require a release.",
        context: null,
        drops: [],
        dropsLabel: null,
      };
    }
    return {
      state: "maybe",
      tone: "warning",
      headline: "May require a release (taxi occupancy unknown).",
      context,
      // When the backend names the worst case, show it as the worst case.
      drops,
      dropsLabel: drops.length ? "Worst case" : null,
    };
  }

  if (capacity.requiresDrops === false) {
    return {
      state: "fits",
      tone: "neutral",
      headline: `Fits ${whose} — no release needed.`,
      context: null,
      drops: [],
      dropsLabel: null,
    };
  }

  // requiresDrops === true
  const n = drops.length;
  const upper = capacity.forcedDropsAreUpperBound === true;
  // A roster already over the limit owes releases whatever it trades, so the
  // headline does not say this trade FORCES them; `context` says how many
  // were owed before it.
  const verb = context ? "Needs" : "Forces";
  let headline =
    n > 0
      ? `${verb} ${upper ? "at most " : ""}${n} ${plural(n, "release", "releases")}`
      : `${verb} a release`;
  if (isNum(capacity.rosterLimit)) headline += ` to fit the ${capacity.rosterLimit}-man limit`;

  // MISSING IS NEVER ZERO: with no priced drop the backend's total is an
  // empty sum (0.0), not a released value of zero.
  const pricedCount = drops.filter((d) => d.priced).length;
  const unpriced = capacity.unpricedForcedDrops;
  const noPricedDrop = pricedCount === 0 || (isCount(unpriced) && unpriced === n);
  if (noPricedDrop) {
    headline += " — released value unknown";
    if (n === 1) headline += " (the release is not priced)";
    else if (n > 1) headline += " (no release is priced)";
  } else if (isNum(capacity.forcedDropValue)) {
    headline += ` — ${fmtValue(capacity.forcedDropValue)} value released`;
    // An unreported count must not read as "every release is priced".
    if (!isCount(unpriced)) {
      headline += " (whether every release is priced is not reported)";
    } else if (unpriced > 0) {
      headline += ` (plus ${unpriced} with value unknown, not counted)`;
    }
  } else {
    headline += " — released value unknown";
  }
  if (upper) headline += " (taxi occupancy unknown)";
  if (capacity.ladderExhausted === true) headline += " — no fully legal cleanup found";
  if (n === 0) headline += " — who goes is not determined";
  headline += ".";
  return {
    state: "requires",
    tone: "warning",
    headline,
    context,
    drops,
    dropsLabel: n ? (upper ? "Worst case" : "Released") : null,
  };
}

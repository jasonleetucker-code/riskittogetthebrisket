// What a generated trade does to YOUR roster, as words — for the generated
// trade surfaces (Package Builder at /angle, Best Offers, the /arbitrage
// Package Builder view).
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

function fmtValue(v) {
  return Math.round(Number(v)).toLocaleString("en-US");
}

const isNum = (v) => typeof v === "number" && Number.isFinite(v);

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
 * Summarise one `rosterCapacity` block.
 *
 * @returns {{
 *   state: "not_checked"|"unavailable"|"unknown_limit"|"maybe"|"fits"|"requires",
 *   tone: "neutral"|"warning",
 *   headline: string,
 *   drops: Array<{key: string, label: string, valueText: string, priced: boolean}>,
 *   dropsLabel: string|null,
 * }}
 */
export function forcedReleaseSummary(capacity) {
  if (!capacity || typeof capacity !== "object") {
    return {
      state: "not_checked",
      tone: "neutral",
      headline: "Roster capacity not checked for this trade — any forced release is unknown, not zero.",
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
      drops: [],
      dropsLabel: null,
    };
  }

  const drops = dropLines(capacity);

  if (capacity.requiresDrops === null || capacity.requiresDrops === undefined) {
    if (capacity.rosterLimit == null) {
      return {
        state: "unknown_limit",
        tone: "neutral",
        headline: "Roster limit unknown — this trade may require a release.",
        drops: [],
        dropsLabel: null,
      };
    }
    return {
      state: "maybe",
      tone: "warning",
      headline: "May require a release (taxi occupancy unknown).",
      // When the backend names the worst case, show it as the worst case.
      drops,
      dropsLabel: drops.length ? "Worst case" : null,
    };
  }

  if (capacity.requiresDrops === false) {
    return {
      state: "fits",
      tone: "neutral",
      headline: "Fits your roster — no release needed.",
      drops: [],
      dropsLabel: null,
    };
  }

  // requiresDrops === true
  const n = drops.length;
  const upper = capacity.forcedDropsAreUpperBound === true;
  let headline =
    n > 0
      ? `Forces ${upper ? "at most " : ""}${n} release${n === 1 ? "" : "s"}`
      : "Forces a release";
  if (isNum(capacity.rosterLimit)) headline += ` to fit the ${capacity.rosterLimit}-man limit`;
  headline += isNum(capacity.forcedDropValue)
    ? ` — ${fmtValue(capacity.forcedDropValue)} value released`
    : " — released value unknown";
  const unpriced = Number(capacity.unpricedForcedDrops) || 0;
  if (unpriced > 0 && isNum(capacity.forcedDropValue)) {
    headline += ` (plus ${unpriced} with value unknown, not counted)`;
  }
  if (upper) headline += " (taxi occupancy unknown)";
  if (capacity.ladderExhausted === true) headline += " — no fully legal cleanup found";
  if (n === 0) headline += " — who goes is not determined";
  headline += ".";
  return {
    state: "requires",
    tone: "warning",
    headline,
    drops,
    dropsLabel: n ? (upper ? "Worst case" : "Released") : null,
  };
}

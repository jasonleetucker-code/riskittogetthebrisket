// Rookie-source coverage — pure display helpers over the additive
// ``/api/draft-capital`` fields ``rookieSourceCoverage`` (pool block, top
// level) and ``picks[].rookieSourceCoverage`` (per rookie).  Both come from
// the backend (src/draft/rookie_source_coverage.py); nothing is computed here
// beyond joining by name and phrasing.  Missing is never zero: an unknown
// count renders as unknown, never "0 sources".

const STATE_LABEL = {
  voting: "voting",
  held: "held",
  seasonal: "seasonal",
  stale: "stale",
  missing: "vendor-empty / no usable rows",
};

export function normalizeRookieName(name) {
  return String(name || "")
    .trim()
    .toLowerCase();
}

/** {pool, byName: Map(lowercased name -> per-rookie stamp)} or null. */
export function buildRookieCoverageIndex(capitalData) {
  const pool =
    capitalData && typeof capitalData.rookieSourceCoverage === "object"
      ? capitalData.rookieSourceCoverage
      : null;
  const byName = new Map();
  const picks = Array.isArray(capitalData?.picks) ? capitalData.picks : [];
  for (const pk of picks) {
    if (!pk?.rookieName || !pk.rookieSourceCoverage) continue;
    byName.set(normalizeRookieName(pk.rookieName), pk.rookieSourceCoverage);
  }
  if (!pool && byName.size === 0) return null;
  return { pool, byName };
}

export function coverageForName(index, name) {
  return index?.byName?.get(normalizeRookieName(name)) || null;
}

/** The per-row marker: only LOW and UNKNOWN rows get one. */
export function coverageMarker(stamp, lowBelow = 3) {
  if (!stamp) return null;
  if (stamp.state === "low") {
    const n = stamp.votingSourceCount;
    return {
      kind: "low",
      text: n === 1 ? "1 source" : `${n} sources`,
      title: `Priced by ${n} voting source${n === 1 ? "" : "s"} (fewer than ${lowBelow}): thinner evidence than a well-covered rookie.`,
    };
  }
  if (stamp.state === "unknown") {
    return {
      kind: "unknown",
      text: "? sources",
      title: "Per-source coverage is unavailable for this rookie.",
    };
  }
  return null;
}

/** One line, e.g. "4 of 6 rookie sources voting; DLF Rookie SF: vendor-empty / no usable rows". */
export function coverageLine(pool) {
  if (!pool) return null;
  if (pool.state !== "available" || pool.votingCount == null) {
    return "Rookie source coverage unavailable.";
  }
  const parts = [
    `${pool.votingCount} of ${pool.relevantCount} rookie sources voting`,
  ];
  const notVoting = (pool.sources || []).filter((s) => s.state !== "voting");
  for (const s of notVoting) {
    parts.push(`${s.displayName || s.key}: ${STATE_LABEL[s.state] || s.state}`);
  }
  let line = parts.join("; ");
  if (pool.lowCoverageRows > 0) {
    line += `; ${pool.lowCoverageRows} rookie${pool.lowCoverageRows === 1 ? "" : "s"} on fewer than ${pool.lowCoverageBelow} sources`;
  }
  return `${line}.`;
}

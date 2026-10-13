// Shape GET /api/sources/weighting for the Source Health page.
//
// The backend (src/api/source_weighting_explain.py::source_table) reads every
// number from stamps the canonical pipeline already wrote — freshness against
// each source's OWN expected cadence, health, coverage, base and effective
// weight, and the clocks kept apart.  This module only labels and formats.
// It computes no freshness of its own: the status a row shows is the
// backend's `state`, never an age threshold chosen here.  (The fetch-recency
// strip beside it on the page uses fixed 4h/12h bands, which is why that strip
// is labelled "fetch recency" and this table is the freshness verdict.)

export const STATE_STATUS = {
  ON_SCHEDULE: { status: "positive", label: "On schedule" },
  OVERDUE: { status: "warning", label: "Overdue" },
  STALE: { status: "warning", label: "Stale" },
  SEVERELY_STALE: { status: "negative", label: "Severely stale" },
  QUARANTINED: { status: "negative", label: "Quarantined" },
  UNMEASURED: { status: "neutral", label: "Unmeasured" },
};

const STATE_ORDER = [
  "QUARANTINED",
  "SEVERELY_STALE",
  "STALE",
  "OVERDUE",
  "UNMEASURED",
  "ON_SCHEDULE",
];

export function stateStatus(state) {
  return (
    STATE_STATUS[state] || {
      status: "neutral",
      // An unknown label is shown as itself rather than mapped onto a
      // reassuring one.
      label: state ? String(state) : "Unknown",
    }
  );
}

function finite(n) {
  return typeof n === "number" && Number.isFinite(n);
}

/** Hours → "9h" / "3.2d"; null stays an explicit em dash, never 0. */
export function formatHours(hours) {
  if (!finite(hours)) return "—";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))}m`;
  if (hours < 48) return `${Math.round(hours)}h`;
  const days = hours / 24;
  return `${days < 10 ? days.toFixed(1) : Math.round(days)}d`;
}

/** 0..1 factor → "0.93"; null → "—" (unknown is not full). */
export function formatFactor(f) {
  return finite(f) ? f.toFixed(2) : "—";
}

/** Age of an ISO timestamp in hours relative to `now`; null when unknown. */
export function hoursSince(iso, now = Date.now()) {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return null;
  return Math.max(0, (now - t) / 3_600_000);
}

/**
 * Rows for the table.  `labels` maps a source key to a display name (the
 * frontend registry); unknown keys show the key itself.
 */
export function weightingRows(payload, { labels = {}, now = Date.now() } = {}) {
  const rows = Array.isArray(payload?.sources) ? payload.sources : [];
  return rows.map((r, i) => {
    const subset = r.subset ? String(r.subset) : null;
    return {
      id: `${r.source}::${subset ?? "-"}::${i}`,
      source: r.source,
      label: labels[r.source] || r.source,
      subset,
      role: r.role === "benchmark" ? "Benchmark" : r.role === "model_input" ? "Vote" : r.role || "—",
      isBenchmark: r.role === "benchmark",
      state: r.state || null,
      health: r.health || null,
      fetchedHours: hoursSince(r.lastFetchedAt, now),
      contentHours: finite(r.ageHours) ? r.ageHours : null,
      expectedHours: finite(r.expectedCadenceHours) ? r.expectedCadenceHours : null,
      ageOverExpected: finite(r.ageOverExpected) ? r.ageOverExpected : null,
      freshness: finite(r.freshness) ? r.freshness : null,
      coverageFactor: finite(r.coverageFactor) ? r.coverageFactor : null,
      baseWeight: finite(r.baseWeight) ? r.baseWeight : null,
      effectiveWeight: finite(r.effectiveWeight) ? r.effectiveWeight : null,
      votingRows: finite(r.votingRows) ? r.votingRows : null,
      meanVoteShare: finite(r.meanVoteShare) ? r.meanVoteShare : null,
      healthErrors: Array.isArray(r.healthErrors) ? r.healthErrors : [],
      stateRank: (() => {
        const idx = STATE_ORDER.indexOf(r.state);
        return idx === -1 ? STATE_ORDER.indexOf("UNMEASURED") : idx;
      })(),
    };
  });
}

/** Count of rows per backend state, worst first — for the summary line. */
export function stateSummary(rows) {
  const counts = new Map();
  for (const r of rows) {
    const key = r.state || "UNKNOWN";
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return [...counts.entries()]
    .map(([state, count]) => ({ state, count, ...stateStatus(state === "UNKNOWN" ? null : state) }))
    .sort((a, b) => {
      const ia = STATE_ORDER.indexOf(a.state);
      const ib = STATE_ORDER.indexOf(b.state);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
}

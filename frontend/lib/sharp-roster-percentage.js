/**
 * Display helpers for the Sharp Roster Percentage board.
 *
 * PURE MATERIALIZER — same rule as `buildRows` and `lib/bdvm.js`: this
 * file reshapes and formats numbers the backend already computed and
 * never derives one of its own. No percentage is calculated here, no
 * row is re-ranked here, and no missing value is filled in with a
 * default that would read as data.
 *
 * The reason is specific to this feature rather than stylistic. Every
 * number on this board is a claim about a sample, and the backend is
 * the only layer that knows the sample: which rosters were eligible,
 * which were excluded and why, and which rosters could even field the
 * player in question. A frontend that recomputed a percentage from
 * `sharpRosters / eligibleRosters` would produce the same number today
 * and a wrong one the moment the denominator rule changes.
 */

/** Percentage, or an em dash when the backend published nothing. */
export function formatPct(value, { digits = 1 } = {}) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

/** Signed percentage-point delta, for advantage and trend columns. */
export function formatDelta(value, { digits = 1 } = {}) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  const points = value * 100;
  const sign = points > 0 ? "+" : "";
  return `${sign}${points.toFixed(digits)} pp`;
}

export function formatCount(value) {
  return typeof value === "number" && !Number.isNaN(value) ? value.toLocaleString() : "—";
}

export function formatTimestamp(ms) {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms <= 0) return "—";
  try {
    return new Date(ms).toLocaleString();
  } catch {
    return "—";
  }
}

/** `3 of 12 rosters` — the sample behind one cell, always shown. */
export function formatSample(row) {
  if (!row) return "—";
  const held = formatCount(row.sharpRosters);
  const total = formatCount(row.eligibleRosters);
  return `${held} of ${total}`;
}

const BUY_SELL_LABELS = {
  accumulating: "Buying",
  distributing: "Selling",
  mixed: "Mixed",
  thin: "Thin",
  none: "—",
};

/**
 * The Buy/Sell Tracker column, as words.
 *
 * A player can be widely rostered AND actively sold, which is the
 * whole reason the two boards are joined — so this deliberately reads
 * as an observation about recent transactions, never as advice.
 */
export function describeBuySell(buySell) {
  if (!buySell || buySell.signal === "none") return { label: "—", detail: null, tone: "neutral" };
  const { buys = 0, sells = 0, net = 0, signal, window } = buySell;
  const tone =
    signal === "accumulating" ? "positive" : signal === "distributing" ? "negative" : "neutral";
  return {
    label: BUY_SELL_LABELS[signal] || "—",
    detail: `${buys} buy${buys === 1 ? "" : "s"} / ${sells} sell${sells === 1 ? "" : "s"}` +
      ` (net ${net > 0 ? "+" : ""}${net}, ${window})`,
    tone,
  };
}

/**
 * The trend cell for one period.
 *
 * Returns an explicit `unavailable` shape rather than a zero when the
 * roster population moved too much between the endpoints. "No change"
 * and "not comparable" must never render the same.
 */
export function describeTrend(trend, period = "thirtyDay") {
  const item = trend?.[period];
  if (!item) return { available: false, label: "—", reason: null };
  if (!item.available) {
    return {
      available: false,
      label: "n/a",
      reason:
        item.reason === "roster_population_changed"
          ? `Sample changed too much to compare (${formatCount(item.comparableRosters)} rosters in both periods)`
          : "Not comparable",
    };
  }
  return {
    available: true,
    label: formatDelta(item.rosterPctChange),
    added: item.rostersAdded,
    dropped: item.rostersDropped,
    reason: null,
    tone:
      item.rosterPctChange > 0 ? "positive" : item.rosterPctChange < 0 ? "negative" : "neutral",
  };
}

/** The transparency strip, as label/value pairs in display order. */
export function buildTransparencyTiles(payload) {
  const t = payload?.transparency || {};
  return [
    { key: "managers", label: "Sharp managers", value: formatCount(t.uniqueSharpManagers) },
    { key: "rosters", label: "Eligible rosters", value: formatCount(t.eligibleRosters) },
    { key: "sleeper", label: "Sleeper rosters", value: formatCount(t.sleeperRosters) },
    { key: "ffpc", label: "FFPC rosters", value: formatCount(t.ffpcRosters) },
    {
      key: "other",
      label: "Other platforms",
      value: formatCount(t.otherPlatformRosters),
    },
    {
      key: "coverage",
      label: "Cohort represented",
      value: formatPct(t.cohortCoveragePct, { digits: 0 }),
      note:
        typeof t.cohortManagersRepresented === "number" && typeof t.cohortManagers === "number"
          ? `${t.cohortManagersRepresented} of ${t.cohortManagers}`
          : null,
    },
    { key: "refreshed", label: "Last refresh", value: formatTimestamp(t.lastRefreshedMs) },
  ];
}

/**
 * Why the board is empty, in the user's terms.
 *
 * Distinguishes the three real states so "we have not collected this
 * yet" never renders as a failure — the same posture the Sharp Tracker
 * takes with `cohort_building`.
 */
export function classifyEmptyState(payload) {
  if (!payload) return { title: "No data", detail: "The board could not be loaded." };
  if (payload.status === "cohort_building") {
    return {
      title: "Collecting sharp rosters",
      detail:
        "The sharp cohort is known, but its rosters have not been collected yet. " +
        "Run the sharp roster crawl to populate this board.",
    };
  }
  if (payload.status === "no_eligible_rosters") {
    return {
      title: "No eligible rosters",
      detail:
        "Sharp rosters have been collected, but none currently pass the eligibility " +
        "gates. The exclusion breakdown below shows why.",
    };
  }
  return {
    title: "No players match these filters",
    detail: "Widen the filters to see more of the board.",
  };
}

/** Exclusion reasons as sorted, human-readable rows. */
export function buildExclusionRows(payload) {
  const byReason = payload?.exclusions?.byReason || {};
  return Object.entries(byReason)
    .map(([reason, count]) => ({
      reason,
      label: reason.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()),
      count,
    }))
    .sort((a, b) => b.count - a.count || a.reason.localeCompare(b.reason));
}

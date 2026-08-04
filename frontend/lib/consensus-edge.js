/**
 * consensus-edge — display helpers for the Consensus Edge board.
 *
 * Pure materializer, same rule as `buildRows` and `lib/bdvm.js`: this
 * file reshapes and formats numbers the backend already computed and
 * never computes a score itself. The composite formula lives in
 * `src/consensus_edge/score.py` and exists in exactly one place, which
 * is the lesson from the client-side `computeUnifiedRanks` fallback
 * that used to drift from the backend blend.
 */

/** Failure kinds rendered distinctly from a generic error. */
export function classifyEdgeFailure(status, body) {
  if (status >= 200 && status < 300) return null;
  const code = body && typeof body === "object" ? body.error : "";
  const message =
    (body && typeof body === "object" && (body.message || body.detail)) || "";
  if (status === 503 && code === "feature_disabled") {
    return { kind: "disabled", message };
  }
  if (status === 503 && code === "data_not_ready") {
    return { kind: "not_ready", message };
  }
  if (status === 503 && code === "consensus_edge_unavailable") {
    return { kind: "unavailable", message };
  }
  if (status === 401) {
    return { kind: "auth", message: "Sign in to view Consensus Edge." };
  }
  return { kind: "error", message: message || `HTTP ${status}` };
}

/**
 * Tone for a label. `conflicted` and `insufficient` deliberately get
 * their own tone rather than reusing "neutral" — the whole point of
 * those states is that they are NOT a mild reading.
 */
export function labelTone(label) {
  switch (label) {
    case "Strong Buy":
      return "strong-positive";
    case "Buy":
      return "positive";
    case "Sell":
      return "negative";
    case "Strong Sell":
      return "strong-negative";
    case "Conflicted":
      return "conflicted";
    case "Insufficient Evidence":
    case "No Market Price":
    case "Withheld":
      return "unknown";
    default:
      return "neutral";
  }
}

/**
 * Round for display. Scores are shown as integers because the
 * underlying precision is not real — a composite of one validated and
 * two unvalidated components does not support a decimal place.
 */
export function formatScore(score) {
  if (typeof score !== "number" || !Number.isFinite(score)) return "—";
  return `${score > 0 ? "+" : ""}${Math.round(score)}`;
}

export function formatConfidence(confidence) {
  if (typeof confidence !== "number" || !Number.isFinite(confidence)) return "—";
  return `${Math.round(confidence)}`;
}

export function formatPct(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${Math.round(value * 100)}%`;
}

export function formatValue(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return Math.round(value).toLocaleString();
}

/**
 * Components in a stable display order, annotated with whether each has
 * been validated. Surfacing that per component is the honest way to
 * show a composite whose parts have unequal standing.
 */
export function componentRows(row, validation) {
  const components = (row && row.components) || {};
  const order = ["mispricing", "sharpFlow", "opportunity"];
  const labels = {
    mispricing: "Market mispricing",
    sharpFlow: "Sharp flow",
    opportunity: "Opportunity / risk",
  };
  return order.map((key) => {
    const value = components[key];
    const meta = (validation && validation[key]) || {};
    return {
      key,
      label: labels[key],
      value: typeof value === "number" && Number.isFinite(value) ? value : null,
      absent: !(typeof value === "number" && Number.isFinite(value)),
      validated: Boolean(meta.validated),
      note: meta.note || "",
      weight:
        row && row.effectiveWeights ? row.effectiveWeights[key] ?? null : null,
    };
  });
}

/**
 * Position leaders, threshold-gated. Returns one entry per position
 * that HAS a qualifying player and omits the rest — the caller renders
 * "no qualifying buy" rather than reaching further down the board,
 * because promoting a weak player to fill a slot would label him a buy
 * for a display reason.
 */
export function positionLeaders(rows, { direction = "buy" } = {}) {
  const wanted =
    direction === "buy" ? ["Strong Buy", "Buy"] : ["Strong Sell", "Sell"];
  const best = new Map();
  for (const row of rows || []) {
    if (!wanted.includes(row.label)) continue;
    const position = row.position;
    if (!position) continue;
    const current = best.get(position);
    const better =
      !current ||
      (direction === "buy" ? row.score > current.score : row.score < current.score);
    if (better) best.set(position, row);
  }
  return Array.from(best.entries())
    .map(([position, row]) => ({ position, row }))
    .sort((a, b) => a.position.localeCompare(b.position));
}

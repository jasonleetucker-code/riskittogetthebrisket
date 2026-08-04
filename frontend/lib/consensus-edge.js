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

/** Display names for the three components, in stable display order. */
export const COMPONENT_ORDER = ["mispricing", "sharpFlow", "opportunity"];

export const COMPONENT_LABELS = {
  mispricing: "Market mispricing",
  sharpFlow: "Sharp flow",
  opportunity: "Opportunity / risk",
};

export function componentLabel(key) {
  return COMPONENT_LABELS[key] || key;
}

/**
 * Components in a stable display order, annotated with their standing.
 *
 * Four states, not two. The page used to render only "has a value" and
 * "not assessed", which flattened two distinctions that matter:
 *
 * - `zeroWeight` — the component produced a real value that the model
 *   deliberately does not act on. Opportunity is this since its
 *   composite backtest returned a null. Drawn as an ordinary bar it
 *   would look exactly like a contributing signal, and a user comparing
 *   a −0.60 opportunity reading against a score that ignores it has no
 *   way to tell which is the model's answer.
 * - `partial` — scored, but some axes had no evidence. A row carrying
 *   only `boardMomentumRisk` (which is clamped ≤ 0) drew an ordinary
 *   negative bar indistinguishable from a fully-evidenced negative
 *   reading. That is the common case outside production, where the
 *   playerctx snapshot that feeds `snapTrend` does not exist.
 *
 * Still a pure materializer: every field here is read off the payload,
 * none is computed.
 */
export function componentRows(row, validation) {
  const components = (row && row.components) || {};
  const zeroWeighted = new Set((row && row.componentsZeroWeight) || []);
  return COMPONENT_ORDER.map((key) => {
    const value = components[key];
    const meta = (validation && validation[key]) || {};
    const hasValue = typeof value === "number" && Number.isFinite(value);
    // Per-component evidence blocks sit at the row's top level
    // (`row.opportunity`, `row.sharpFlow`, `row.mispricing`), alongside
    // the scalar in `row.components`.
    const evidence = (row && row[key]) || {};
    const absentAxes = Array.isArray(evidence.absentAxes) ? evidence.absentAxes : [];
    const observedAxes = Array.isArray(evidence.observedAxes) ? evidence.observedAxes : [];
    return {
      key,
      label: componentLabel(key),
      value: hasValue ? value : null,
      absent: !hasValue,
      zeroWeight: hasValue && zeroWeighted.has(key),
      partial: hasValue && absentAxes.length > 0,
      absentAxes,
      observedAxes,
      validated: Boolean(meta.validated),
      measured: Boolean(meta.measured),
      outcome: meta.outcome || null,
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
  const best = new Map();
  for (const row of rows || []) {
    // Qualification is the BACKEND's answer, read off the row. This used
    // to be a hardcoded JS copy of the label set, matched by English
    // string against Python constants — rename a label server-side and
    // this panel silently emptied. Same drift the client-side rank
    // fallback caused, same fix: the backend states it, the client
    // reads it.
    if (!row.qualified) continue;
    if (direction === "buy" ? !(row.score > 0) : !(row.score < 0)) continue;
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

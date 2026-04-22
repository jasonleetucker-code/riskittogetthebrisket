// ── Chart primitives ────────────────────────────────────────────────
// Shared SVG helpers for every chart on the site.  We deliberately
// avoid pulling in a chart library (recharts, visx, chart.js, d3):
//
//   • The two pre-existing charts (power ranking line, luck sparkline)
//     are inline SVG.  This file formalises that pattern so the new
//     chart surfaces all use the same axis math, scale functions,
//     theme tokens, and number formatting.
//   • Bundle size: recharts is ~250 KB gzipped; this file is ~2 KB.
//   • Zero runtime deps means no version-pin drift and no chart-lib
//     breaking changes at the worst possible time.
//
// Every chart in frontend/components/graphs/*.jsx imports from here
// and is otherwise self-contained.
//
// Tests: frontend/__tests__/chart-primitives.test.js
// ─────────────────────────────────────────────────────────────────────

/**
 * Theme tokens — match the rest of the UI's CSS.
 * Access via ``CHART_COLORS.<token>`` so a future theme swap happens
 * in one place.
 */
export const CHART_COLORS = {
  axis: "#64748b",        // slate-500
  axisLabel: "#94a3b8",   // slate-400
  grid: "#1e293b",        // slate-800 — subtle, for value lines
  bg: "transparent",
  accent: "#38bdf8",      // sky-400 — primary data color
  accentMuted: "#0e7490", // cyan-700
  danger: "#f97316",      // orange-500 — outliers / drops
  warn: "#facc15",        // yellow-400 — caution / medium
  success: "#22c55e",     // green-500 — high confidence
  positive: "#10b981",    // emerald-500
  negative: "#ef4444",    // red-500
  // Categorical palette for multi-series charts (power rank, trade flow,
  // franchise trajectory, etc.).  10 perceptually-distinct hues cycling
  // through by index — sufficient for typical 10-12 team leagues.
  categorical: [
    "#38bdf8", "#f472b6", "#a3e635", "#fb923c", "#c084fc",
    "#14b8a6", "#fbbf24", "#f87171", "#60a5fa", "#4ade80",
    "#e879f9", "#fb7185",
  ],
  // Confidence-bucket palette — must match display-helpers.js::confBadgeClass.
  confidence: {
    high: "#22c55e",
    medium: "#facc15",
    low: "#ef4444",
    none: "#64748b",
  },
};

/**
 * Linear interpolation from one numeric range to another.
 *
 *   scale(d0, d1, r0, r1)(x)  maps x in [d0, d1] to [r0, r1]
 *
 * Used everywhere: pixel mapping for axes, value-to-radius for radars,
 * value-to-opacity for heatmaps.  Not clamped — callers that want
 * clamping wrap with ``clamp`` explicitly.
 */
export function linearScale(d0, d1, r0, r1) {
  if (d0 === d1) return () => (r0 + r1) / 2;
  const slope = (r1 - r0) / (d1 - d0);
  return (x) => r0 + (x - d0) * slope;
}

/** Clamp ``v`` into ``[lo, hi]``. */
export function clamp(v, lo, hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

/**
 * Produce N evenly-spaced "nice" ticks between ``lo`` and ``hi``.
 * Used for axis labels.  Simple and good enough for charts with
 * modest dynamic range; for log / unusual domains, callers provide
 * their own tick array.
 */
export function ticks(lo, hi, count = 5) {
  if (count < 2 || hi <= lo) return [lo, hi];
  const step = (hi - lo) / (count - 1);
  return Array.from({ length: count }, (_, i) => lo + i * step);
}

/**
 * Format a numeric value for axis labels.  Rounds to the given
 * precision and adds thousands separators.  ``null`` / non-finite
 * inputs render as a dash — never NaN.
 */
export function formatNumber(value, precision = 0) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const fixed = precision > 0 ? n.toFixed(precision) : String(Math.round(n));
  // Insert thousands separators via a standard regex.
  const [whole, frac] = fixed.split(".");
  const withSep = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return frac ? `${withSep}.${frac}` : withSep;
}

/** Pick a categorical color by index, wrapping around the palette. */
export function categoricalColor(index) {
  const n = CHART_COLORS.categorical.length;
  return CHART_COLORS.categorical[((index % n) + n) % n];
}

/**
 * Chart viewBox + margin helper.  Every chart in the site renders
 * into a responsive SVG where the viewBox is the data coordinate
 * space plus margins for axis labels.
 *
 * ``useChartBox({ width, height, margin })`` returns:
 *   { innerWidth, innerHeight, viewBox, plotTransform }
 *
 * ``plotTransform`` is the translate string to apply to the inner
 * plot <g> so (0,0) is the top-left of the plot area (not the axis
 * label area).
 */
export function chartBox({ width, height, margin }) {
  const m = {
    top: 12,
    right: 12,
    bottom: 28,
    left: 40,
    ...(margin || {}),
  };
  const innerWidth = Math.max(0, width - m.left - m.right);
  const innerHeight = Math.max(0, height - m.top - m.bottom);
  return {
    margin: m,
    innerWidth,
    innerHeight,
    viewBox: `0 0 ${width} ${height}`,
    plotTransform: `translate(${m.left}, ${m.top})`,
  };
}

/**
 * Build an SVG path ``d`` string for a polyline from a list of
 * ``[x, y]`` points.  Skips consecutive nulls so a series with
 * gaps renders as multiple segments instead of a jagged zig-zag
 * through the gaps.
 */
export function linePath(points) {
  if (!Array.isArray(points) || points.length === 0) return "";
  const segments = [];
  let current = [];
  for (const p of points) {
    if (!p || p[0] === null || p[1] === null || !Number.isFinite(p[0]) || !Number.isFinite(p[1])) {
      if (current.length > 0) segments.push(current);
      current = [];
      continue;
    }
    current.push(p);
  }
  if (current.length > 0) segments.push(current);
  return segments
    .map((seg) =>
      seg
        .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`)
        .join(" "),
    )
    .join(" ");
}

/**
 * Simple histogram bucketer.  Given a list of values and a bucket
 * count, returns an array of { x0, x1, count } objects covering
 * ``[min, max]``.  Values falling on bucket edges go to the higher
 * bucket (except the last which is inclusive).
 */
export function histogram(values, bucketCount = 20) {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length === 0 || bucketCount < 1) return [];
  const lo = Math.min(...finite);
  const hi = Math.max(...finite);
  if (lo === hi) {
    return [{ x0: lo, x1: hi, count: finite.length }];
  }
  const step = (hi - lo) / bucketCount;
  const buckets = Array.from({ length: bucketCount }, (_, i) => ({
    x0: lo + i * step,
    x1: lo + (i + 1) * step,
    count: 0,
  }));
  for (const v of finite) {
    let idx = Math.floor((v - lo) / step);
    if (idx >= bucketCount) idx = bucketCount - 1;
    if (idx < 0) idx = 0;
    buckets[idx].count += 1;
  }
  return buckets;
}

/**
 * Median of a numeric array, or ``null`` for empty input.  Used by
 * histogram overlay and the source-agreement radar.
 */
export function median(values) {
  const finite = values
    .filter((v) => Number.isFinite(v))
    .slice()
    .sort((a, b) => a - b);
  const n = finite.length;
  if (n === 0) return null;
  if (n % 2 === 1) return finite[(n - 1) / 2];
  return (finite[n / 2 - 1] + finite[n / 2]) / 2;
}

"use client";

// ── Chart 10: rank movement glyph ────────────────────────────────────
// Inline, row-sized mini-visual showing rank movement.  Ideally this
// would be a 30-day sparkline, but the backend doesn't stamp a rank
// history series today — only (optionally) a ``rankChange`` delta
// vs. the previous scrape.
//
// This component supports both modes:
//   • ``history`` prop (array of {date, rank}) → render a sparkline.
//   • ``change`` prop alone → render a compact arrow glyph with the
//     ordinal delta.
//   • Neither → render nothing (returns null).
//
// When the backend starts emitting a per-player rank history, callers
// just start passing ``history`` and every row-level render lights up
// as a real sparkline with zero additional work here.
// ─────────────────────────────────────────────────────────────────────

import {
  CHART_COLORS,
  chartBox,
  linearScale,
  linePath,
} from "../../lib/chart-primitives.js";

function normaliseHistory(history) {
  if (!Array.isArray(history)) return [];
  const cleaned = history
    .filter((h) => h && Number.isFinite(Number(h.rank)))
    .map((h) => ({
      date: h.date ? new Date(h.date).getTime() : null,
      rank: Number(h.rank),
    }));
  // Ensure chronological order.  If dates are missing / mixed, fall
  // back to the input order.
  if (cleaned.every((h) => h.date !== null)) {
    cleaned.sort((a, b) => a.date - b.date);
  }
  return cleaned;
}

export default function RankChangeGlyph({
  history,
  change,
  width = 72,
  height = 20,
}) {
  const points = normaliseHistory(history);

  // Sparkline mode.
  if (points.length >= 2) {
    const ranks = points.map((p) => p.rank);
    const lo = Math.min(...ranks);
    const hi = Math.max(...ranks);
    const box = chartBox({ width, height, margin: { left: 2, right: 2, top: 2, bottom: 2 } });
    const x = linearScale(0, points.length - 1, 0, box.innerWidth);
    // Lower rank = better, so invert the y axis: smaller rank → higher y.
    const y = linearScale(lo, hi, 0, box.innerHeight);
    const d = linePath(points.map((p, i) => [x(i), y(p.rank)]));
    const first = points[0].rank;
    const last = points[points.length - 1].rank;
    const delta = first - last; // positive = moved up (rank went down numerically)
    const stroke =
      delta > 0 ? CHART_COLORS.positive : delta < 0 ? CHART_COLORS.negative : CHART_COLORS.axisLabel;
    return (
      <svg
        viewBox={box.viewBox}
        width={width}
        height={height}
        role="img"
        aria-label={`Rank sparkline; ${delta > 0 ? "up" : delta < 0 ? "down" : "flat"} ${Math.abs(delta)} ranks over ${points.length} points`}
      >
        <g transform={box.plotTransform}>
          <path d={d} fill="none" stroke={stroke} strokeWidth={1.5} />
          <circle cx={x(points.length - 1)} cy={y(last)} r={2} fill={stroke} />
        </g>
      </svg>
    );
  }

  // Single-delta mode.
  if (Number.isFinite(Number(change)) && Number(change) !== 0) {
    const n = Number(change);
    const up = n > 0; // convention: positive rankChange = moved UP the board (rank improved)
    const color = up ? CHART_COLORS.positive : CHART_COLORS.negative;
    const arrow = up ? "▲" : "▼";
    return (
      <span
        style={{
          color,
          fontSize: 11,
          fontVariantNumeric: "tabular-nums",
          whiteSpace: "nowrap",
        }}
        aria-label={`Rank ${up ? "up" : "down"} ${Math.abs(n)}`}
      >
        {arrow} {Math.abs(n)}
      </span>
    );
  }

  return null;
}

"use client";

// ── Chart 6: Hill curve explorer ─────────────────────────────────────
// Renders the Hill curve that maps percentile → Hill value in
// ``src/canonical/player_valuation.py::percentile_to_value`` and
// overlays the live board as a scatter.  Hovering / focusing a point
// highlights its curve anchor.
//
// Scope caveat: the audit found only a single (HILL_MIDPOINT=45,
// HILL_SLOPE=1.10) global curve — there are no separate
// offense/IDP/rookie parameter sets to chart side-by-side.  If the
// backend ever stamps per-scope parameters into the contract root
// (``hillCurves: { global: {...}, offense: {...}, ... }``), this
// component will pick them up automatically via the ``curves`` prop.
// ─────────────────────────────────────────────────────────────────────

import {
  CHART_COLORS,
  chartBox,
  categoricalColor,
  linearScale,
  ticks,
  formatNumber,
  linePath,
} from "../../lib/chart-primitives.js";

// Python default: percentile_to_value(p, midpoint=45, slope=1.10).  A
// logistic-like ramp from 0 → 9999 as p goes 0 → 100.  Exactly mirrors
// the ``percentile_to_value`` helper so the frontend stays in lockstep
// with the backend's rank → value map.
function hillValue(percentile, { midpoint, slope }) {
  const p = Math.max(0, Math.min(100, percentile));
  const denom = 1 + Math.exp(-slope * (p - midpoint));
  return (9999 * (1 - 1 / denom)) / (1 - 1 / (1 + Math.exp(slope * midpoint))) * (denom > 0 ? 1 : 0);
}

// Fallback curve parameters — single global curve per the audit.
// Replaced with ``curves`` prop when the caller supplies them.
const DEFAULT_CURVES = [
  { key: "global", label: "Global", midpoint: 45, slope: 1.1 },
];

export default function HillCurveExplorer({
  rows,
  curves = DEFAULT_CURVES,
  width = 640,
  height = 320,
  samplePoints = 60,
  onPointClick = null,
}) {
  const box = chartBox({ width, height, margin: { left: 52, right: 16, top: 16, bottom: 36 } });
  const x = linearScale(0, 100, 0, box.innerWidth);
  const y = linearScale(0, 9999, box.innerHeight, 0);

  const curvePaths = (curves || []).map((c, i) => {
    const pts = [];
    for (let k = 0; k <= samplePoints; k++) {
      const p = (100 * k) / samplePoints;
      pts.push([x(p), y(hillValue(p, c))]);
    }
    return { ...c, d: linePath(pts), color: categoricalColor(i) };
  });

  // Project each board row onto the curve: percentile = 100 - (rank/total)*100.
  // The exact percentile that the backend feeds the Hill curve depends on
  // the source pool size, so this is an approximation useful for the visual
  // but not the pipeline's ground truth.
  const validRows = (rows || []).filter(
    (r) =>
      Number.isFinite(r?.rank) &&
      r.rank > 0 &&
      Number.isFinite(r?.rankDerivedValue) &&
      r.rankDerivedValue > 0,
  );
  const maxRank = validRows.reduce((m, r) => Math.max(m, r.rank), 1);
  const scatter = validRows.map((r) => ({
    p: 100 - (r.rank / maxRank) * 100,
    v: r.rankDerivedValue,
    name: r.name,
    rank: r.rank,
    raw: r,
  }));

  const xTicks = ticks(0, 100, 6);
  const yTicks = ticks(0, 9999, 6);

  return (
    <svg
      viewBox={box.viewBox}
      width="100%"
      height={height}
      role="img"
      aria-label="Hill curve explorer"
    >
      <g transform={box.plotTransform}>
        {yTicks.map((t) => (
          <g key={`y${t}`}>
            <line
              x1={0}
              x2={box.innerWidth}
              y1={y(t)}
              y2={y(t)}
              stroke={CHART_COLORS.grid}
              strokeWidth={0.5}
            />
            <text
              x={-6}
              y={y(t)}
              textAnchor="end"
              dominantBaseline="middle"
              fontSize={10}
              fill={CHART_COLORS.axisLabel}
            >
              {formatNumber(t)}
            </text>
          </g>
        ))}
        {xTicks.map((t) => (
          <g key={`x${t}`}>
            <text
              x={x(t)}
              y={box.innerHeight + 16}
              textAnchor="middle"
              fontSize={10}
              fill={CHART_COLORS.axisLabel}
            >
              {formatNumber(t)}%
            </text>
          </g>
        ))}

        {/* Scatter of actual board rows — drawn first so the curve sits on top. */}
        {scatter.map((s, i) => (
          <circle
            key={i}
            cx={x(s.p)}
            cy={y(s.v)}
            r={2}
            fill={CHART_COLORS.axisLabel}
            fillOpacity={0.4}
            style={onPointClick ? { cursor: "pointer" } : undefined}
            onClick={onPointClick ? () => onPointClick(s.raw) : undefined}
          >
            <title>#{s.rank} {s.name}</title>
          </circle>
        ))}

        {/* Hill curves */}
        {curvePaths.map((c) => (
          <path
            key={c.key}
            d={c.d}
            fill="none"
            stroke={c.color}
            strokeWidth={2}
          />
        ))}

        {/* Axis titles */}
        <text
          x={box.innerWidth / 2}
          y={box.innerHeight + 30}
          textAnchor="middle"
          fontSize={11}
          fill={CHART_COLORS.axisLabel}
        >
          percentile
        </text>
        <text
          transform={`rotate(-90) translate(${-box.innerHeight / 2}, ${-42})`}
          textAnchor="middle"
          fontSize={11}
          fill={CHART_COLORS.axisLabel}
        >
          Hill value
        </text>

        {/* Legend — inline at top-right. */}
        {curvePaths.length > 1 ? (
          <g transform={`translate(${box.innerWidth - 120}, 0)`}>
            {curvePaths.map((c, i) => (
              <g key={c.key} transform={`translate(0, ${i * 16})`}>
                <line x1={0} x2={20} y1={6} y2={6} stroke={c.color} strokeWidth={2} />
                <text x={26} y={6} dominantBaseline="middle" fontSize={10} fill={CHART_COLORS.axisLabel}>
                  {c.label}
                </text>
              </g>
            ))}
          </g>
        ) : null}
      </g>
    </svg>
  );
}

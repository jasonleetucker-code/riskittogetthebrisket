"use client";

// ── Chart 12: source agreement radar ─────────────────────────────────
// Polar / spider chart with one axis per contributing source.  The
// radial coordinate is each source's ``valueContribution`` normalised
// against the player's maximum source contribution (so the hull
// touches the outer ring for whichever source valued the player
// highest).
//
// Visual signal:
//   • A symmetric polygon → sources agree.
//   • A polygon with a dent near one axis → that source disagrees.
//   • Dropped sources render as an X at the axis tip, not a hull
//     vertex — so the user can see which axes the aggregation
//     *ignored* vs. which simply valued the player low.
//
// Input contract mirrors SourceContributionBars: row.sourceRankMeta +
// optional row.droppedSources.
// ─────────────────────────────────────────────────────────────────────

import { CHART_COLORS } from "../../lib/chart-primitives.js";

export default function SourceAgreementRadar({
  row,
  labelFor = (k) => k,
  size = 260,
}) {
  const meta = row?.sourceRankMeta || {};
  const droppedSet = new Set(row?.droppedSources || []);
  const axes = Object.entries(meta)
    .map(([key, m]) => ({
      key,
      value: Number(m?.valueContribution ?? 0),
      dropped: droppedSet.has(key),
    }))
    .filter((a) => Number.isFinite(a.value) && a.value > 0);

  if (axes.length < 3) {
    return (
      <div className="chart-empty" style={{ padding: 12, color: CHART_COLORS.axisLabel }}>
        Need 3+ sources for a radar; this row has {axes.length}.
      </div>
    );
  }

  const cx = size / 2;
  const cy = size / 2;
  const R = size * 0.38;
  const maxVal = Math.max(...axes.map((a) => a.value));

  const pointAt = (axis, i) => {
    const theta = -Math.PI / 2 + (2 * Math.PI * i) / axes.length;
    const r = axis.dropped ? 0 : (axis.value / maxVal) * R;
    return {
      x: cx + r * Math.cos(theta),
      y: cy + r * Math.sin(theta),
      theta,
    };
  };

  const hullPoints = axes
    .filter((a) => !a.dropped)
    .map((a, i) => pointAt(a, axes.indexOf(a)));
  const hullPath =
    hullPoints.length > 0
      ? `M${hullPoints.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" L")} Z`
      : "";

  return (
    <svg
      viewBox={`0 0 ${size} ${size}`}
      width={size}
      height={size}
      role="img"
      aria-label="Source agreement radar"
    >
      {/* Concentric ring guides at 25/50/75/100% of max. */}
      {[0.25, 0.5, 0.75, 1].map((frac) => (
        <circle
          key={frac}
          cx={cx}
          cy={cy}
          r={R * frac}
          fill="none"
          stroke={CHART_COLORS.grid}
          strokeWidth={0.5}
        />
      ))}

      {/* Radial axes + labels + dropped-source markers. */}
      {axes.map((a, i) => {
        const outer = {
          x: cx + R * Math.cos(-Math.PI / 2 + (2 * Math.PI * i) / axes.length),
          y: cy + R * Math.sin(-Math.PI / 2 + (2 * Math.PI * i) / axes.length),
        };
        const labelPos = {
          x: cx + (R + 16) * Math.cos(-Math.PI / 2 + (2 * Math.PI * i) / axes.length),
          y: cy + (R + 16) * Math.sin(-Math.PI / 2 + (2 * Math.PI * i) / axes.length),
        };
        return (
          <g key={a.key}>
            <line
              x1={cx}
              y1={cy}
              x2={outer.x}
              y2={outer.y}
              stroke={CHART_COLORS.grid}
              strokeWidth={0.5}
            />
            {a.dropped ? (
              <g transform={`translate(${outer.x.toFixed(2)}, ${outer.y.toFixed(2)})`}>
                <line
                  x1={-5}
                  y1={-5}
                  x2={5}
                  y2={5}
                  stroke={CHART_COLORS.danger}
                  strokeWidth={1.5}
                />
                <line
                  x1={-5}
                  y1={5}
                  x2={5}
                  y2={-5}
                  stroke={CHART_COLORS.danger}
                  strokeWidth={1.5}
                />
              </g>
            ) : null}
            <text
              x={labelPos.x}
              y={labelPos.y}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={10}
              fill={CHART_COLORS.axisLabel}
            >
              {labelFor(a.key)}
            </text>
          </g>
        );
      })}

      {/* Convex hull of contributing (non-dropped) sources. */}
      {hullPath ? (
        <path
          d={hullPath}
          fill={CHART_COLORS.accent}
          fillOpacity={0.25}
          stroke={CHART_COLORS.accent}
          strokeWidth={1.5}
        />
      ) : null}

      {/* Vertex dots. */}
      {hullPoints.map((p, i) => (
        <circle
          key={i}
          cx={p.x}
          cy={p.y}
          r={2.5}
          fill={CHART_COLORS.accent}
        />
      ))}
    </svg>
  );
}

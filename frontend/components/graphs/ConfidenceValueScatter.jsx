"use client";

// ── Chart 9: confidence vs value scatter ─────────────────────────────
// Scatter of top-N ranked rows.
//   x = rankDerivedValue (0-9999 Hill scale)
//   y = sourceRankPercentileSpread (0-1, higher = more disagreement)
//   color = confidenceBucket (high/medium/low)
//
// Interesting quadrants:
//   • high value + low spread (top-left):  safe consensus studs
//   • high value + high spread (top-right): contested assets — edge
//     opportunity; either sell high or buy low depending on your
//     read of which market is right.
//   • low value + low spread (bottom-left): fringe consensus depth
//   • low value + high spread (bottom-right): the market can't even
//     agree that these are depth — volatile picks.
// ─────────────────────────────────────────────────────────────────────

import {
  CHART_COLORS,
  chartBox,
  linearScale,
  ticks,
  formatNumber,
} from "../../lib/chart-primitives.js";

export default function ConfidenceValueScatter({
  rows,
  topN = 200,
  width = 720,
  height = 360,
  onPointClick = null,
}) {
  const points = (rows || [])
    .filter(
      (r) =>
        Number.isFinite(r?.rank) &&
        r.rank <= topN &&
        Number.isFinite(r?.rankDerivedValue) &&
        r.rankDerivedValue > 0 &&
        Number.isFinite(r?.sourceRankPercentileSpread),
    )
    .map((r) => ({
      x: r.rankDerivedValue,
      y: r.sourceRankPercentileSpread,
      bucket: r.confidenceBucket || "none",
      name: r.name,
      rank: r.rank,
      raw: r,
    }));

  if (points.length === 0) {
    return (
      <div className="chart-empty" style={{ padding: 12, color: CHART_COLORS.axisLabel }}>
        No rows with both value and percentile-spread stamps.
      </div>
    );
  }

  const xMax = Math.max(...points.map((p) => p.x));
  const yMax = Math.max(0.25, Math.max(...points.map((p) => p.y)));

  const box = chartBox({
    width,
    height,
    margin: { left: 52, right: 16, top: 16, bottom: 36 },
  });
  const x = linearScale(0, xMax, 0, box.innerWidth);
  const y = linearScale(0, yMax, box.innerHeight, 0);

  const xTicks = ticks(0, xMax, 6);
  const yTicks = ticks(0, yMax, 5);

  return (
    <svg
      viewBox={box.viewBox}
      width="100%"
      height={height}
      role="img"
      aria-label="Confidence versus value scatter plot"
    >
      <g transform={box.plotTransform}>
        {/* Gridlines + axis labels. */}
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
              {formatNumber(t * 100, 0)}%
            </text>
          </g>
        ))}
        {xTicks.map((t) => (
          <g key={`x${t}`}>
            <line
              x1={x(t)}
              x2={x(t)}
              y1={0}
              y2={box.innerHeight}
              stroke={CHART_COLORS.grid}
              strokeWidth={0.5}
            />
            <text
              x={x(t)}
              y={box.innerHeight + 16}
              textAnchor="middle"
              fontSize={10}
              fill={CHART_COLORS.axisLabel}
            >
              {formatNumber(t)}
            </text>
          </g>
        ))}

        {/* Axis titles */}
        <text
          x={box.innerWidth / 2}
          y={box.innerHeight + 30}
          textAnchor="middle"
          fontSize={11}
          fill={CHART_COLORS.axisLabel}
        >
          rankDerivedValue
        </text>
        <text
          transform={`rotate(-90) translate(${-box.innerHeight / 2}, ${-42})`}
          textAnchor="middle"
          fontSize={11}
          fill={CHART_COLORS.axisLabel}
        >
          source spread (%)
        </text>

        {/* Points.  The visible dot is r=3.5 for the desktop density
            this chart was designed for.  Stacked on top is an invisible
            r=10 tap-target circle so finger taps near a dot still hit
            it — on a phone an r=3.5 (7px) circle is essentially
            impossible to land on accurately. */}
        {points.map((p, i) => (
          <g
            key={i}
            style={onPointClick ? { cursor: "pointer" } : undefined}
            onClick={onPointClick ? () => onPointClick(p.raw) : undefined}
          >
            {onPointClick && (
              <circle
                cx={x(p.x)}
                cy={y(p.y)}
                r={10}
                fill="transparent"
                pointerEvents="all"
              />
            )}
            <circle
              cx={x(p.x)}
              cy={y(p.y)}
              r={3.5}
              fill={CHART_COLORS.confidence[p.bucket] || CHART_COLORS.confidence.none}
              fillOpacity={0.8}
              stroke={CHART_COLORS.bg}
              strokeWidth={0.5}
              pointerEvents="none"
            >
              <title>
                #{p.rank} {p.name} — value {formatNumber(p.x)}, spread {formatNumber(p.y * 100, 1)}%, {p.bucket}
              </title>
            </circle>
          </g>
        ))}
      </g>
    </svg>
  );
}

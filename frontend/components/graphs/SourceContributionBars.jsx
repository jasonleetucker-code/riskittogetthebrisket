"use client";

// ── Chart 7: per-source contribution bars ────────────────────────────
// Renders one horizontal bar per source for an expanded rankings row,
// height proportional to each source's ``valueContribution`` (the
// per-source Hill value that enters the aggregation).
//
// Drop markers: sources listed in ``row.droppedSources`` render with a
// strike-through overlay + muted fill so the Hampel filter (see
// src/api/data_contract.py::_hampel_filter_per_player) is visible at
// the row level — you can see *which* sources were rejected without
// pivoting to the audit panel.
//
// Input contract:
//   row.sourceRankMeta: { [sourceKey]: { valueContribution: number } }
//   row.droppedSources: string[]  (optional — pre-Hampel rows stamp ``[]``)
//   labelFor(sourceKey): string   (optional — short column label)
//
// No external deps; everything is inline SVG.
// ─────────────────────────────────────────────────────────────────────

import {
  CHART_COLORS,
  chartBox,
  formatNumber,
  linearScale,
} from "../../lib/chart-primitives.js";

export default function SourceContributionBars({
  row,
  labelFor = (k) => k,
  width = 360,
  height = 180,
}) {
  const meta = row?.sourceRankMeta || {};
  const droppedSet = new Set(row?.droppedSources || []);
  const entries = Object.entries(meta)
    .map(([key, m]) => ({
      key,
      value: Number(m?.valueContribution ?? 0),
      dropped: droppedSet.has(key),
    }))
    .filter((e) => Number.isFinite(e.value) && e.value > 0)
    .sort((a, b) => b.value - a.value);

  if (entries.length === 0) {
    return (
      <div className="chart-empty" style={{ padding: 12, color: CHART_COLORS.axisLabel }}>
        No per-source contributions for this row.
      </div>
    );
  }

  const maxVal = Math.max(...entries.map((e) => e.value));
  const box = chartBox({ width, height, margin: { left: 80, right: 48, top: 8, bottom: 8 } });
  const bandHeight = box.innerHeight / entries.length;
  const barHeight = Math.max(6, bandHeight * 0.7);
  const x = linearScale(0, maxVal, 0, box.innerWidth);

  return (
    <svg
      viewBox={box.viewBox}
      width="100%"
      height={height}
      role="img"
      aria-label="Per-source value contribution bar chart"
    >
      <g transform={box.plotTransform}>
        {entries.map((e, i) => {
          const y = i * bandHeight + (bandHeight - barHeight) / 2;
          const w = x(e.value);
          const fill = e.dropped ? CHART_COLORS.danger : CHART_COLORS.accent;
          const opacity = e.dropped ? 0.35 : 0.9;
          return (
            <g key={e.key}>
              <text
                x={-8}
                y={y + barHeight / 2}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={11}
                fill={CHART_COLORS.axisLabel}
              >
                {labelFor(e.key)}
              </text>
              <rect
                x={0}
                y={y}
                width={w}
                height={barHeight}
                fill={fill}
                fillOpacity={opacity}
                rx={2}
              />
              {e.dropped ? (
                <line
                  x1={0}
                  x2={w}
                  y1={y + barHeight / 2}
                  y2={y + barHeight / 2}
                  stroke={CHART_COLORS.danger}
                  strokeWidth={1.5}
                />
              ) : null}
              <text
                x={w + 6}
                y={y + barHeight / 2}
                dominantBaseline="middle"
                fontSize={11}
                fill={CHART_COLORS.axisLabel}
              >
                {formatNumber(e.value)}
                {e.dropped ? " (dropped)" : ""}
              </text>
            </g>
          );
        })}
      </g>
    </svg>
  );
}

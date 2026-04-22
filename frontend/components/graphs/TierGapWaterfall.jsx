"use client";

// ── Chart 8: tier-gap waterfall ──────────────────────────────────────
// Plots the top-N rows as a descending value curve with the
// row-to-row gap (`rankDerivedValue[i] - rankDerivedValue[i+1]`)
// overlaid as a coloured bar.  Big gaps → tier boundaries; flat
// runs → within-tier depth.
//
// The gap-based tier detector in src/canonical/player_valuation.py
// (``detect_tiers``) classifies these same gaps as cliffs when they
// exceed a rolling-median threshold.  This chart just makes the
// underlying pattern visible — no tier logic duplicated here.
//
// Input: rows = [{ rank, rankDerivedValue, tierId? }]
// ─────────────────────────────────────────────────────────────────────

import {
  CHART_COLORS,
  chartBox,
  linearScale,
  linePath,
  ticks,
  formatNumber,
} from "../../lib/chart-primitives.js";

export default function TierGapWaterfall({
  rows,
  topN = 120,
  width = 720,
  height = 260,
}) {
  const series = (rows || [])
    .filter(
      (r) =>
        Number.isFinite(r?.rank) &&
        Number.isFinite(r?.rankDerivedValue) &&
        r.rankDerivedValue > 0,
    )
    .slice()
    .sort((a, b) => a.rank - b.rank)
    .slice(0, topN);

  if (series.length < 2) {
    return (
      <div className="chart-empty" style={{ padding: 12, color: CHART_COLORS.axisLabel }}>
        Not enough ranked rows to render a tier waterfall.
      </div>
    );
  }

  const gaps = [];
  for (let i = 0; i < series.length - 1; i++) {
    gaps.push(series[i].rankDerivedValue - series[i + 1].rankDerivedValue);
  }
  const maxValue = series[0].rankDerivedValue;
  const minValue = series[series.length - 1].rankDerivedValue;
  const maxGap = Math.max(...gaps, 1);

  const box = chartBox({ width, height, margin: { left: 56, right: 12, top: 8, bottom: 28 } });
  const x = linearScale(1, series.length, 0, box.innerWidth);
  const y = linearScale(minValue, maxValue, box.innerHeight, 0);
  const gapScale = linearScale(0, maxGap, 0, box.innerHeight * 0.35);

  // Data path.
  const linePoints = series.map((r, i) => [x(i + 1), y(r.rankDerivedValue)]);
  const d = linePath(linePoints);

  const yTicks = ticks(minValue, maxValue, 5);
  const xTicks = ticks(1, series.length, Math.min(6, series.length));

  return (
    <svg
      viewBox={box.viewBox}
      width="100%"
      height={height}
      role="img"
      aria-label="Tier-gap waterfall chart"
    >
      <g transform={box.plotTransform}>
        {/* Y gridlines */}
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

        {/* Gap bars — height proportional to per-row gap.  A bar
            at x=i+0.5 straddles rows i and i+1 so the bar spans
            the transition it represents. */}
        {gaps.map((g, i) => {
          const bx = x(i + 1 + 0.5) - 3;
          const h = gapScale(g);
          const by = box.innerHeight - h;
          const pct = g / maxGap;
          const fill =
            pct >= 0.6
              ? CHART_COLORS.danger
              : pct >= 0.3
              ? CHART_COLORS.warn
              : CHART_COLORS.accentMuted;
          return (
            <rect
              key={i}
              x={bx}
              y={by}
              width={6}
              height={h}
              fill={fill}
              fillOpacity={0.7}
              rx={1}
            >
              <title>Gap at rank {i + 1}→{i + 2}: {formatNumber(g)}</title>
            </rect>
          );
        })}

        {/* Value curve */}
        <path d={d} fill="none" stroke={CHART_COLORS.accent} strokeWidth={1.5} />

        {/* X ticks */}
        {xTicks.map((t) => (
          <g key={`x${t}`}>
            <text
              x={x(t)}
              y={box.innerHeight + 18}
              textAnchor="middle"
              fontSize={10}
              fill={CHART_COLORS.axisLabel}
            >
              #{Math.round(t)}
            </text>
          </g>
        ))}
      </g>
    </svg>
  );
}

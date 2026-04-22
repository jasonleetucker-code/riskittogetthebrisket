"use client";

// ── Chart 11: trade value delta histogram ────────────────────────────
// Live visualisation of a trade proposal.  Renders two stacked bars:
//   • Left (side A total value)
//   • Right (side B total value)
// plus a delta arrow pointing toward whichever side is being
// shortchanged.  Updates on every prop change, so the trade page can
// pass in-flight totals as the user drags pieces around.
//
// Input contract:
//   sides = [
//     { label: string, total: number, players: [{name, value}] }
//   ]
// ─────────────────────────────────────────────────────────────────────

import {
  CHART_COLORS,
  chartBox,
  linearScale,
  formatNumber,
} from "../../lib/chart-primitives.js";

export default function TradeDeltaHistogram({
  sides,
  width = 420,
  height = 200,
  balanceThreshold = 500,
}) {
  const pair = Array.isArray(sides) ? sides.slice(0, 2) : [];
  if (pair.length < 2) {
    return (
      <div className="chart-empty" style={{ padding: 12, color: CHART_COLORS.axisLabel }}>
        Add players to both sides to see the value comparison.
      </div>
    );
  }
  const [a, b] = pair;
  const aTotal = Math.max(0, Number(a?.total) || 0);
  const bTotal = Math.max(0, Number(b?.total) || 0);
  const maxTotal = Math.max(aTotal, bTotal, 1);
  const delta = aTotal - bTotal;
  const absDelta = Math.abs(delta);
  const balanced = absDelta <= balanceThreshold;

  const box = chartBox({
    width,
    height,
    margin: { left: 32, right: 32, top: 32, bottom: 48 },
  });
  const barWidth = box.innerWidth * 0.28;
  const gap = box.innerWidth * 0.14;
  const xA = box.innerWidth / 2 - barWidth - gap / 2;
  const xB = box.innerWidth / 2 + gap / 2;
  const y = linearScale(0, maxTotal, box.innerHeight, 0);

  const aColor = delta >= 0 ? CHART_COLORS.accent : CHART_COLORS.accentMuted;
  const bColor = delta > 0 ? CHART_COLORS.accentMuted : CHART_COLORS.accent;

  return (
    <svg
      viewBox={box.viewBox}
      width="100%"
      height={height}
      role="img"
      aria-label={`Trade value comparison: ${a.label || "Side A"} ${formatNumber(aTotal)} vs ${b.label || "Side B"} ${formatNumber(bTotal)}`}
    >
      <g transform={box.plotTransform}>
        {/* Side A bar */}
        <rect
          x={xA}
          y={y(aTotal)}
          width={barWidth}
          height={box.innerHeight - y(aTotal)}
          fill={aColor}
          fillOpacity={0.85}
          rx={2}
        />
        <text
          x={xA + barWidth / 2}
          y={y(aTotal) - 6}
          textAnchor="middle"
          fontSize={12}
          fill={CHART_COLORS.axisLabel}
        >
          {formatNumber(aTotal)}
        </text>
        <text
          x={xA + barWidth / 2}
          y={box.innerHeight + 16}
          textAnchor="middle"
          fontSize={11}
          fill={CHART_COLORS.axisLabel}
        >
          {a.label || "Side A"}
        </text>

        {/* Side B bar */}
        <rect
          x={xB}
          y={y(bTotal)}
          width={barWidth}
          height={box.innerHeight - y(bTotal)}
          fill={bColor}
          fillOpacity={0.85}
          rx={2}
        />
        <text
          x={xB + barWidth / 2}
          y={y(bTotal) - 6}
          textAnchor="middle"
          fontSize={12}
          fill={CHART_COLORS.axisLabel}
        >
          {formatNumber(bTotal)}
        </text>
        <text
          x={xB + barWidth / 2}
          y={box.innerHeight + 16}
          textAnchor="middle"
          fontSize={11}
          fill={CHART_COLORS.axisLabel}
        >
          {b.label || "Side B"}
        </text>

        {/* Balance banner */}
        <text
          x={box.innerWidth / 2}
          y={-12}
          textAnchor="middle"
          fontSize={12}
          fontWeight={600}
          fill={balanced ? CHART_COLORS.success : CHART_COLORS.warn}
        >
          {balanced
            ? `Balanced (Δ ${formatNumber(absDelta)})`
            : `${delta > 0 ? a.label || "Side A" : b.label || "Side B"} +${formatNumber(absDelta)}`}
        </text>

        {/* Bottom tick line */}
        <line
          x1={0}
          x2={box.innerWidth}
          y1={box.innerHeight}
          y2={box.innerHeight}
          stroke={CHART_COLORS.axis}
          strokeWidth={0.75}
        />
      </g>
    </svg>
  );
}

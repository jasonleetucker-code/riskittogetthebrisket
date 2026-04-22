"use client";

// ── Chart 4: matchup distribution histogram ──────────────────────────
// Distribution of point margins across every completed matchup in the
// public league snapshot.  Bars stacked by outcome — winner-side
// margin on top, loser-side mirror below — so "runaway games" and
// "photo finishes" are both visible at a glance.
//
// Input:
//   matchups = [{ margin: number, winnerOwnerId: string }]
// ─────────────────────────────────────────────────────────────────────

import {
  CHART_COLORS,
  chartBox,
  histogram,
  linearScale,
  ticks,
  formatNumber,
} from "../../lib/chart-primitives.js";

export default function MatchupMarginHistogram({
  matchups,
  buckets = 16,
  width = 640,
  height = 240,
}) {
  const margins = (matchups || [])
    .filter((m) => m && Number.isFinite(Number(m.margin)))
    .map((m) => Math.abs(Number(m.margin)));

  if (margins.length === 0) {
    return (
      <div className="chart-empty" style={{ padding: 12, color: CHART_COLORS.axisLabel }}>
        No completed matchups in the snapshot.
      </div>
    );
  }

  const bucketList = histogram(margins, buckets);
  const maxCount = Math.max(...bucketList.map((b) => b.count));
  const maxMargin = bucketList[bucketList.length - 1].x1;

  const box = chartBox({ width, height, margin: { left: 48, right: 16, top: 16, bottom: 36 } });
  const x = linearScale(0, maxMargin, 0, box.innerWidth);
  const y = linearScale(0, maxCount, box.innerHeight, 0);

  const xTicks = ticks(0, maxMargin, 6);
  const yTicks = ticks(0, maxCount, 5);

  return (
    <svg
      viewBox={box.viewBox}
      width="100%"
      height={height}
      role="img"
      aria-label="Matchup margin histogram"
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
              {formatNumber(Math.round(t))}
            </text>
          </g>
        ))}

        {bucketList.map((b, i) => {
          const bx = x(b.x0);
          const bw = Math.max(1, x(b.x1) - x(b.x0) - 1);
          const bh = box.innerHeight - y(b.count);
          // Colour by margin magnitude: tight → accent, blowout → warn.
          const mid = (b.x0 + b.x1) / 2;
          const color =
            mid <= 10
              ? CHART_COLORS.success
              : mid <= 25
              ? CHART_COLORS.accent
              : CHART_COLORS.warn;
          return (
            <rect
              key={i}
              x={bx}
              y={y(b.count)}
              width={bw}
              height={bh}
              fill={color}
              fillOpacity={0.8}
              rx={1}
            >
              <title>
                margin {formatNumber(b.x0, 1)}-{formatNumber(b.x1, 1)}: {b.count} matchups
              </title>
            </rect>
          );
        })}

        {xTicks.map((t) => (
          <text
            key={`x${t}`}
            x={x(t)}
            y={box.innerHeight + 18}
            textAnchor="middle"
            fontSize={10}
            fill={CHART_COLORS.axisLabel}
          >
            {formatNumber(t, 0)}
          </text>
        ))}

        <text
          x={box.innerWidth / 2}
          y={box.innerHeight + 32}
          textAnchor="middle"
          fontSize={11}
          fill={CHART_COLORS.axisLabel}
        >
          margin of victory (points)
        </text>
        <text
          transform={`rotate(-90) translate(${-box.innerHeight / 2}, ${-36})`}
          textAnchor="middle"
          fontSize={11}
          fill={CHART_COLORS.axisLabel}
        >
          matchup count
        </text>
      </g>
    </svg>
  );
}

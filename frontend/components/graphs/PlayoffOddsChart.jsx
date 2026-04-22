"use client";

// ── Chart: playoff-odds Monte Carlo ──────────────────────────────────
// Horizontal bar chart showing each franchise's probability of making
// the playoffs, per the Monte Carlo simulator in
// ``src/public_league/playoff_odds.py``.
//
// The backend does the sampling (it has the raw matchup data); this
// component is pure rendering.  Displayed probabilities come directly
// from ``playoffProbability`` in the simulator's output.
//
// Schedule-certainty badge: the simulator annotates its output with
// ``scheduleCertainty ∈ {posted, partial, inferred, final}``.  When
// the remaining schedule is inferred via round-robin fallback the
// chart shows a small caution label explaining the assumption.
//
// Input:
//   data = {
//     season, numSims, playoffSpots, weeksPlayed, weeksRemaining,
//     scheduleCertainty,
//     owners: [{ ownerId, displayName, currentWins, currentPointsFor,
//                playoffProbability }]
//   }
// ─────────────────────────────────────────────────────────────────────

import {
  CHART_COLORS,
  chartBox,
  linearScale,
  formatNumber,
} from "../../lib/chart-primitives.js";

function certaintyLabel(kind) {
  if (kind === "posted") return { text: "Exact schedule", color: CHART_COLORS.success };
  if (kind === "partial") return { text: "Partial schedule (round-robin for un-posted weeks)", color: CHART_COLORS.warn };
  if (kind === "inferred") return { text: "Inferred round-robin schedule", color: CHART_COLORS.warn };
  if (kind === "final") return { text: "Season complete", color: CHART_COLORS.axisLabel };
  return { text: "Unknown schedule source", color: CHART_COLORS.axisLabel };
}

export default function PlayoffOddsChart({
  data,
  width = 640,
  height = 320,
}) {
  const owners = Array.isArray(data?.owners) ? data.owners : [];
  if (owners.length === 0) {
    return (
      <div className="chart-empty" style={{ padding: 12, color: CHART_COLORS.axisLabel }}>
        No playoff-odds data — season may not have started yet.
      </div>
    );
  }

  const sorted = owners
    .slice()
    .sort(
      (a, b) => (b.playoffProbability ?? 0) - (a.playoffProbability ?? 0),
    );

  const box = chartBox({
    width,
    height,
    margin: { left: 140, right: 60, top: 28, bottom: 32 },
  });
  const rowGap = 4;
  const rowHeight = Math.max(
    14,
    (box.innerHeight - rowGap * (sorted.length - 1)) / Math.max(1, sorted.length),
  );
  const x = linearScale(0, 1, 0, box.innerWidth);
  const certainty = certaintyLabel(data?.scheduleCertainty || "");

  return (
    <svg
      viewBox={box.viewBox}
      width="100%"
      height={height}
      role="img"
      aria-label="Monte Carlo playoff probabilities"
    >
      <g transform={box.plotTransform}>
        {/* Header — sims + certainty badge */}
        <text
          x={0}
          y={-14}
          fontSize={11}
          fill={CHART_COLORS.axisLabel}
        >
          {formatNumber(data?.numSims || 0)} sims · top {data?.playoffSpots ?? "?"} make playoffs · week {data?.weeksPlayed ?? "?"} of {((data?.weeksPlayed ?? 0) + (data?.weeksRemaining ?? 0))} · {certainty.text}
        </text>

        {/* 25 / 50 / 75 / 100% reference lines */}
        {[0.25, 0.5, 0.75, 1].map((v) => (
          <g key={v}>
            <line
              x1={x(v)}
              x2={x(v)}
              y1={0}
              y2={box.innerHeight}
              stroke={CHART_COLORS.grid}
              strokeWidth={0.5}
            />
            <text
              x={x(v)}
              y={box.innerHeight + 16}
              textAnchor="middle"
              fontSize={10}
              fill={CHART_COLORS.axisLabel}
            >
              {Math.round(v * 100)}%
            </text>
          </g>
        ))}

        {/* Owner bars */}
        {sorted.map((o, i) => {
          const y = i * (rowHeight + rowGap);
          const p = Math.max(0, Math.min(1, Number(o.playoffProbability) || 0));
          const fill =
            p >= 0.75
              ? CHART_COLORS.success
              : p >= 0.4
              ? CHART_COLORS.accent
              : p >= 0.15
              ? CHART_COLORS.warn
              : CHART_COLORS.negative;
          return (
            <g key={o.ownerId || i}>
              <text
                x={-8}
                y={y + rowHeight / 2}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={11}
                fill={CHART_COLORS.axisLabel}
              >
                {o.displayName || o.ownerId || "?"}
              </text>
              <rect
                x={0}
                y={y}
                width={Math.max(0.5, x(p))}
                height={rowHeight}
                fill={fill}
                fillOpacity={0.85}
                rx={2}
              >
                <title>
                  {o.displayName || o.ownerId}: {formatNumber(p * 100, 1)}% ·
                  current record {o.currentWins ?? "?"} · PF {formatNumber(o.currentPointsFor, 1)}
                </title>
              </rect>
              <text
                x={x(p) + 6}
                y={y + rowHeight / 2}
                dominantBaseline="middle"
                fontSize={11}
                fill={CHART_COLORS.axisLabel}
              >
                {formatNumber(p * 100, 0)}%
              </text>
            </g>
          );
        })}
      </g>
    </svg>
  );
}

export { certaintyLabel };

"use client";

// ── Chart 5: franchise trajectory (PF proxy) ─────────────────────────
// Season-by-season trajectory of a franchise using ``pointsFor`` as a
// proxy for "how strong the roster was."  No weekly roster-value
// snapshots exist in the backend, so a KTC-style value trajectory
// isn't available yet — the best public signal we have is scoring
// production, which is the output of the roster's actual weekly
// usage.
//
// Vertical markers annotate seasons in which the franchise was a
// trade participant, so owners can visually correlate "made a trade
// → team got better/worse."
//
// Input:
//   seasons = [{ season, pointsFor, wins, madePlayoffs, finalPlace }]
//   tradedSeasons = Set<number>   (optional — years this owner traded)
// ─────────────────────────────────────────────────────────────────────

import {
  CHART_COLORS,
  chartBox,
  linearScale,
  ticks,
  formatNumber,
  linePath,
} from "../../lib/chart-primitives.js";

export default function FranchiseTrajectory({
  seasons,
  tradedSeasons = new Set(),
  width = 720,
  height = 280,
}) {
  const series = (seasons || [])
    .filter(
      (s) =>
        Number.isFinite(Number(s?.season)) &&
        Number.isFinite(Number(s?.pointsFor)),
    )
    .slice()
    .sort((a, b) => Number(a.season) - Number(b.season));

  if (series.length === 0) {
    return (
      <div className="chart-empty" style={{ padding: 12, color: CHART_COLORS.axisLabel }}>
        No completed seasons for this franchise.
      </div>
    );
  }

  const minYear = Number(series[0].season);
  const maxYear = Number(series[series.length - 1].season);
  const pfMin = Math.min(...series.map((s) => Number(s.pointsFor)));
  const pfMax = Math.max(...series.map((s) => Number(s.pointsFor)));
  const pfRange = pfMax - pfMin || 1;

  const box = chartBox({ width, height, margin: { left: 56, right: 16, top: 16, bottom: 40 } });
  const x =
    minYear === maxYear
      ? () => box.innerWidth / 2
      : linearScale(minYear, maxYear, 0, box.innerWidth);
  const y = linearScale(pfMin - pfRange * 0.05, pfMax + pfRange * 0.05, box.innerHeight, 0);

  const points = series.map((s) => [x(Number(s.season)), y(Number(s.pointsFor))]);
  const d = linePath(points);

  const yTicks = ticks(pfMin, pfMax, 5);
  const xTicks = Array.from(
    new Set(series.map((s) => Number(s.season))),
  ).sort((a, b) => a - b);

  return (
    <svg
      viewBox={box.viewBox}
      width="100%"
      height={height}
      role="img"
      aria-label="Franchise scoring trajectory by season"
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

        {/* Trade-year vertical markers behind the line. */}
        {xTicks
          .filter((yr) => tradedSeasons && tradedSeasons.has(yr))
          .map((yr) => (
            <line
              key={`t${yr}`}
              x1={x(yr)}
              x2={x(yr)}
              y1={0}
              y2={box.innerHeight}
              stroke={CHART_COLORS.warn}
              strokeDasharray="3 3"
              strokeWidth={1}
            >
              <title>Trade(s) in {yr}</title>
            </line>
          ))}

        <path d={d} fill="none" stroke={CHART_COLORS.accent} strokeWidth={2} />

        {series.map((s, i) => {
          const made = s.madePlayoffs;
          return (
            <circle
              key={i}
              cx={x(Number(s.season))}
              cy={y(Number(s.pointsFor))}
              r={4}
              fill={made ? CHART_COLORS.success : CHART_COLORS.accent}
              stroke={CHART_COLORS.bg}
              strokeWidth={1}
            >
              <title>
                {s.season}: {formatNumber(s.pointsFor, 1)} PF, {s.wins ?? "?"} wins
                {made ? " — playoffs" : ""}
                {Number.isFinite(Number(s.finalPlace)) ? ` — finished #${s.finalPlace}` : ""}
              </title>
            </circle>
          );
        })}

        {xTicks.map((yr) => (
          <text
            key={`x${yr}`}
            x={x(yr)}
            y={box.innerHeight + 18}
            textAnchor="middle"
            fontSize={10}
            fill={CHART_COLORS.axisLabel}
          >
            {yr}
          </text>
        ))}

        <text
          x={box.innerWidth / 2}
          y={box.innerHeight + 34}
          textAnchor="middle"
          fontSize={11}
          fill={CHART_COLORS.axisLabel}
        >
          season
        </text>
        <text
          transform={`rotate(-90) translate(${-box.innerHeight / 2}, ${-44})`}
          textAnchor="middle"
          fontSize={11}
          fill={CHART_COLORS.axisLabel}
        >
          points for
        </text>
      </g>
    </svg>
  );
}

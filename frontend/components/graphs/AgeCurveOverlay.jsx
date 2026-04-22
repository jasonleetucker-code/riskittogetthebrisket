"use client";

// ── Chart 13: age curve overlay ──────────────────────────────────────
// Position-specific age → value curves with roster dots overlaid.
//
// No precomputed age curve exists in the backend, so this component
// fits one client-side from the live board: group rows by position
// family, then for each integer age compute the median
// rankDerivedValue of matched rows.  That's a reasonable first-order
// "typical value at this age" signal — it's the actual distribution
// you're navigating, not a hypothetical aging model.
//
// Rosters dots render over the curve as small circles so an owner
// can see whether their roster skews old/young relative to the
// position's value peak.
//
// Input:
//   boardRows = [{ pos, age, rankDerivedValue }]     (whole board for curve)
//   rosterRows = [{ pos, age, rankDerivedValue, name }]  (current roster)
//   positions = array of pos to render (default: QB/RB/WR/TE)
// ─────────────────────────────────────────────────────────────────────

import {
  CHART_COLORS,
  chartBox,
  categoricalColor,
  linearScale,
  ticks,
  median,
  formatNumber,
  linePath,
} from "../../lib/chart-primitives.js";

const DEFAULT_POSITIONS = ["QB", "RB", "WR", "TE"];

function ageCurveFor(rows, pos, ageLo, ageHi) {
  const cohort = rows.filter(
    (r) =>
      r &&
      String(r.pos).toUpperCase() === pos &&
      Number.isFinite(Number(r.age)) &&
      Number.isFinite(Number(r.rankDerivedValue)) &&
      r.rankDerivedValue > 0,
  );
  if (cohort.length === 0) return [];
  const byAge = new Map();
  for (const r of cohort) {
    const a = Math.round(Number(r.age));
    if (a < ageLo || a > ageHi) continue;
    if (!byAge.has(a)) byAge.set(a, []);
    byAge.get(a).push(Number(r.rankDerivedValue));
  }
  const points = [];
  for (let a = ageLo; a <= ageHi; a++) {
    const bucket = byAge.get(a);
    if (!bucket || bucket.length === 0) {
      points.push({ age: a, median: null });
      continue;
    }
    points.push({ age: a, median: median(bucket) });
  }
  return points;
}

export default function AgeCurveOverlay({
  boardRows = [],
  rosterRows = [],
  positions = DEFAULT_POSITIONS,
  ageLo = 20,
  ageHi = 36,
  width = 720,
  height = 340,
}) {
  const curvesByPos = positions.map((pos, i) => ({
    pos,
    color: categoricalColor(i),
    curve: ageCurveFor(boardRows, pos, ageLo, ageHi),
    roster: (rosterRows || []).filter(
      (r) =>
        r &&
        String(r.pos).toUpperCase() === pos &&
        Number.isFinite(Number(r.age)) &&
        Number.isFinite(Number(r.rankDerivedValue)) &&
        r.rankDerivedValue > 0,
    ),
  }));

  const allValues = [];
  for (const c of curvesByPos) {
    for (const p of c.curve) if (p.median != null) allValues.push(p.median);
    for (const r of c.roster) allValues.push(r.rankDerivedValue);
  }
  if (allValues.length === 0) {
    return (
      <div className="chart-empty" style={{ padding: 12, color: CHART_COLORS.axisLabel }}>
        Not enough age / value data to fit an age curve.
      </div>
    );
  }
  const maxVal = Math.max(...allValues);

  const box = chartBox({ width, height, margin: { left: 52, right: 16, top: 20, bottom: 40 } });
  const x = linearScale(ageLo, ageHi, 0, box.innerWidth);
  const y = linearScale(0, maxVal, box.innerHeight, 0);

  const xTicks = ticks(ageLo, ageHi, Math.min(8, ageHi - ageLo + 1));
  const yTicks = ticks(0, maxVal, 5);

  return (
    <svg
      viewBox={box.viewBox}
      width="100%"
      height={height}
      role="img"
      aria-label="Age-value curves by position with roster overlay"
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
          <text
            key={`x${t}`}
            x={x(t)}
            y={box.innerHeight + 16}
            textAnchor="middle"
            fontSize={10}
            fill={CHART_COLORS.axisLabel}
          >
            {Math.round(t)}
          </text>
        ))}

        {curvesByPos.map((c) => {
          const pts = c.curve
            .filter((p) => p.median != null)
            .map((p) => [x(p.age), y(p.median)]);
          const d = linePath(pts);
          return (
            <g key={c.pos}>
              <path d={d} fill="none" stroke={c.color} strokeWidth={1.75} />
              {c.roster.map((r, i) => (
                <circle
                  key={i}
                  cx={x(Math.min(ageHi, Math.max(ageLo, Number(r.age))))}
                  cy={y(Number(r.rankDerivedValue))}
                  r={3.5}
                  fill={c.color}
                  fillOpacity={0.9}
                  stroke={CHART_COLORS.bg}
                  strokeWidth={0.5}
                >
                  <title>
                    {r.name || r.pos} — age {r.age}, value {formatNumber(r.rankDerivedValue)}
                  </title>
                </circle>
              ))}
            </g>
          );
        })}

        {/* Legend */}
        <g transform={`translate(${box.innerWidth - 60}, 0)`}>
          {curvesByPos.map((c, i) => (
            <g key={c.pos} transform={`translate(0, ${i * 14})`}>
              <line x1={0} x2={16} y1={6} y2={6} stroke={c.color} strokeWidth={2} />
              <text x={22} y={6} dominantBaseline="middle" fontSize={10} fill={CHART_COLORS.axisLabel}>
                {c.pos}
              </text>
            </g>
          ))}
        </g>

        {/* Axis titles */}
        <text
          x={box.innerWidth / 2}
          y={box.innerHeight + 32}
          textAnchor="middle"
          fontSize={11}
          fill={CHART_COLORS.axisLabel}
        >
          age
        </text>
        <text
          transform={`rotate(-90) translate(${-box.innerHeight / 2}, ${-42})`}
          textAnchor="middle"
          fontSize={11}
          fill={CHART_COLORS.axisLabel}
        >
          median rankDerivedValue
        </text>
      </g>
    </svg>
  );
}

// Re-export the curve helper so tests can pin the aggregation without
// mounting a React tree.
export { ageCurveFor };

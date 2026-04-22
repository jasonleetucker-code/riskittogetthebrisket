"use client";

// ── Chart 5: franchise trajectory (weekly + seasonal) ────────────────
// Scoring trajectory of a single franchise.  Two modes, picked
// automatically by which data the caller provides:
//
//   * Weekly mode (preferred when ``weeklyScoring`` is non-empty).
//     One dot per scored matchup week, drawn as a continuous line
//     across seasons.  Season boundaries render as vertical grid
//     lines.  Playoff weeks are marked in a different hue so the
//     regular-season-vs-playoff arc is visible.
//   * Seasonal mode (fallback).  One dot per season, y = season
//     pointsFor — the pre-weekly-data behaviour.
//
// Why weekly?  The real "how strong was this roster week to week"
// signal is the per-week points-for the roster put up, not the
// season aggregate.  The backend exposes it via
// ``src/public_league/franchise.py::_weekly_scoring_by_owner`` —
// see ``weeklyScoring`` on the franchise detail payload.
//
// No KTC-style roster-value line exists because the backend doesn't
// archive historical rosters; the only honest weekly signal is
// scoring, which is always present.
//
// Trade markers: callers can pass ``tradedSeasons`` (a ``Set<number>``
// of years the owner made a trade in) to annotate the x-axis.
//
// Input:
//   weeklyScoring = [{ season, week, pointsFor, isPlayoff }] (preferred)
//   seasons       = [{ season, pointsFor, wins, madePlayoffs, finalPlace }]
//                   (fallback)
// ─────────────────────────────────────────────────────────────────────

import {
  CHART_COLORS,
  chartBox,
  linearScale,
  ticks,
  formatNumber,
  linePath,
} from "../../lib/chart-primitives.js";

function encodeWeekKey(season, week) {
  // Stable chronological key independent of pixel coordinates — used
  // as map key + sort key so seasons printed as strings still ordinal-
  // sort correctly.
  return Number(season) * 100 + Number(week);
}

function renderWeekly({ weekly, seasons, tradedSeasons, width, height }) {
  const series = (weekly || [])
    .filter(
      (r) =>
        r &&
        Number.isFinite(Number(r.season)) &&
        Number.isFinite(Number(r.week)) &&
        Number.isFinite(Number(r.pointsFor)),
    )
    .map((r) => ({
      season: Number(r.season),
      week: Number(r.week),
      pointsFor: Number(r.pointsFor),
      isPlayoff: !!r.isPlayoff,
      t: encodeWeekKey(r.season, r.week),
    }))
    .sort((a, b) => a.t - b.t);

  if (series.length < 2) return null;

  const tMin = series[0].t;
  const tMax = series[series.length - 1].t;
  const pfMin = Math.min(...series.map((r) => r.pointsFor));
  const pfMax = Math.max(...series.map((r) => r.pointsFor));
  const pfRange = pfMax - pfMin || 1;

  const box = chartBox({ width, height, margin: { left: 56, right: 16, top: 16, bottom: 40 } });
  const x = linearScale(tMin, tMax, 0, box.innerWidth);
  const y = linearScale(pfMin - pfRange * 0.05, pfMax + pfRange * 0.05, box.innerHeight, 0);

  const pts = series.map((r) => [x(r.t), y(r.pointsFor)]);
  const d = linePath(pts);

  // Find season boundaries (the week where ``season`` changes) so we
  // can draw vertical grid markers between seasons.
  const seasonBoundaries = [];
  for (let i = 1; i < series.length; i++) {
    if (series[i].season !== series[i - 1].season) {
      // Midpoint between last week of prior season and first of next.
      const midT = (series[i - 1].t + series[i].t) / 2;
      seasonBoundaries.push({ t: midT, season: series[i].season });
    }
  }

  // X tick labels: one per unique season, placed at the centre of
  // that season's weeks.
  const bySeason = new Map();
  for (const r of series) {
    if (!bySeason.has(r.season)) bySeason.set(r.season, []);
    bySeason.get(r.season).push(r.t);
  }
  const seasonTicks = Array.from(bySeason.entries()).map(([season, ts]) => {
    const lo = Math.min(...ts);
    const hi = Math.max(...ts);
    return { season, t: (lo + hi) / 2 };
  });

  const yTicks = ticks(pfMin, pfMax, 5);
  const seasonPfMap = new Map(
    (seasons || [])
      .filter((s) => Number.isFinite(Number(s?.season)))
      .map((s) => [Number(s.season), s]),
  );

  return (
    <svg
      viewBox={box.viewBox}
      width="100%"
      height={height}
      role="img"
      aria-label="Franchise weekly scoring trajectory"
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

        {seasonBoundaries.map((b, i) => (
          <line
            key={`sb${i}`}
            x1={x(b.t)}
            x2={x(b.t)}
            y1={0}
            y2={box.innerHeight}
            stroke={CHART_COLORS.axis}
            strokeWidth={0.75}
            strokeDasharray="2 4"
          />
        ))}

        {/* Trade-year markers, if the caller supplied them. */}
        {tradedSeasons && typeof tradedSeasons.has === "function"
          ? seasonTicks
              .filter((s) => tradedSeasons.has(s.season))
              .map((s) => (
                <line
                  key={`tr${s.season}`}
                  x1={x(s.t)}
                  x2={x(s.t)}
                  y1={0}
                  y2={box.innerHeight}
                  stroke={CHART_COLORS.warn}
                  strokeDasharray="3 3"
                  strokeWidth={1}
                  opacity={0.5}
                >
                  <title>Trade(s) in {s.season}</title>
                </line>
              ))
          : null}

        <path d={d} fill="none" stroke={CHART_COLORS.accent} strokeWidth={1.5} />

        {series.map((r, i) => {
          const meta = seasonPfMap.get(r.season);
          const hue = r.isPlayoff ? CHART_COLORS.warn : CHART_COLORS.accent;
          return (
            <circle
              key={i}
              cx={x(r.t)}
              cy={y(r.pointsFor)}
              r={r.isPlayoff ? 3.5 : 2.75}
              fill={hue}
              fillOpacity={r.isPlayoff ? 1 : 0.85}
              stroke={CHART_COLORS.bg}
              strokeWidth={0.5}
            >
              <title>
                {r.season} Wk {r.week}{r.isPlayoff ? " (playoffs)" : ""}: {formatNumber(r.pointsFor, 1)} PF
                {meta
                  ? ` — season total ${formatNumber(meta.pointsFor, 1)} PF`
                  : ""}
              </title>
            </circle>
          );
        })}

        {seasonTicks.map((s) => (
          <text
            key={`x${s.season}`}
            x={x(s.t)}
            y={box.innerHeight + 18}
            textAnchor="middle"
            fontSize={10}
            fill={CHART_COLORS.axisLabel}
          >
            {s.season}
          </text>
        ))}

        <text
          x={box.innerWidth / 2}
          y={box.innerHeight + 34}
          textAnchor="middle"
          fontSize={11}
          fill={CHART_COLORS.axisLabel}
        >
          season · week
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

function renderSeasonal({ seasons, tradedSeasons, width, height }) {
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
  const xTicks = Array.from(new Set(series.map((s) => Number(s.season)))).sort((a, b) => a - b);

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

        {xTicks
          .filter((yr) => tradedSeasons && typeof tradedSeasons.has === "function" && tradedSeasons.has(yr))
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

export default function FranchiseTrajectory({
  seasons,
  weeklyScoring,
  tradedSeasons = new Set(),
  width = 720,
  height = 280,
}) {
  const weeklyRendered = renderWeekly({
    weekly: weeklyScoring,
    seasons,
    tradedSeasons,
    width,
    height,
  });
  if (weeklyRendered) return weeklyRendered;
  return renderSeasonal({ seasons, tradedSeasons, width, height });
}

// Exported for tests so the key encoding stays pinned.
export { encodeWeekKey };

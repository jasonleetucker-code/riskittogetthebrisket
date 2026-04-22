"use client";

// ── Chart 6: Hill curve explorer ─────────────────────────────────────
// Renders the four scope-level master Hill curves that map percentile
// → value (see ``src/canonical/player_valuation.py`` constants
// ``HILL_GLOBAL_PERCENTILE_*``, ``HILL_PERCENTILE_*``,
// ``IDP_HILL_PERCENTILE_*``, ``HILL_ROOKIE_PERCENTILE_*``) with the
// live board overlaid as a scatter.
//
// The backend stamps the curves into the contract root as
// ``hillCurves: { global: {midpoint, slope, ...}, offense: {...},
// idp: {...}, rookie: {...} }``; rankings/page.jsx forwards that to
// the ``curves`` prop here.  Each curve's ``midpoint``/``slope`` are
// already rank-form (``midpoint = c * (referenceN − 1)``), so the
// rank-based ``hillValue`` below renders them directly.  See
// ``_build_hill_curves_block`` in ``src/api/data_contract.py``.
//
// Scatter points are coloured by position group so per-scope
// behaviour (where rookies cluster, where IDPs cluster, where picks
// sit relative to starters) is visible alongside the curves.
// ─────────────────────────────────────────────────────────────────────

import {
  CHART_COLORS,
  chartBox,
  categoricalColor,
  linearScale,
  ticks,
  formatNumber,
  linePath,
} from "../../lib/chart-primitives.js";

// Rank-form Hill evaluator; matches the Python ``percentile_to_value``
// after the rank→percentile conversion ``p = (r-1)/(N-1)`` and the
// equivalence ``midpoint_rank = c * (N-1)``, ``slope = s``.  The
// backend stamps curves in rank form so this renders directly.
function hillValue(rank, { midpoint, slope }) {
  const r = Math.max(1, rank);
  const exponent = Math.pow((r - 1) / midpoint, slope);
  return Math.max(1, Math.min(9999, Math.round(1 + 9998 / (1 + exponent))));
}

// Fallback only — used when the contract hasn't stamped ``hillCurves``
// (e.g. a stale cached payload).  The live path receives the full
// four-scope object from the ``/api/data`` root.
const DEFAULT_CURVES = [
  { key: "global", label: "Global", midpoint: 45, slope: 1.1 },
];

// Normalize incoming curves: accept either the backend's dict shape
// ``{global: {...}, offense: {...}, ...}`` or an already-flat array
// ``[{key, label, midpoint, slope}, ...]``.  Entries missing a numeric
// ``midpoint`` or ``slope`` are dropped rather than silently rendered
// as NaN paths.
function normalizeCurves(curves) {
  if (Array.isArray(curves)) return curves.filter(isRenderableCurve);
  if (curves && typeof curves === "object") {
    const order = ["global", "offense", "idp", "rookie"];
    const seen = new Set();
    const flat = [];
    for (const key of order) {
      if (curves[key]) {
        flat.push({ key, ...curves[key] });
        seen.add(key);
      }
    }
    for (const key of Object.keys(curves)) {
      if (!seen.has(key) && curves[key]) flat.push({ key, ...curves[key] });
    }
    return flat.filter(isRenderableCurve);
  }
  return [];
}

function isRenderableCurve(c) {
  return (
    c &&
    Number.isFinite(Number(c.midpoint)) &&
    Number(c.midpoint) > 0 &&
    Number.isFinite(Number(c.slope)) &&
    Number(c.slope) > 0
  );
}

// Colour palette per position group.  Keys match the ``assetClass`` /
// coarse position taxonomy the frontend already uses so the Hill
// chart legend matches the badge colours elsewhere on the board.
const GROUP_COLORS = {
  QB: CHART_COLORS.categorical[0],
  RB: CHART_COLORS.categorical[2],
  WR: CHART_COLORS.categorical[1],
  TE: CHART_COLORS.categorical[3],
  DL: CHART_COLORS.categorical[4],
  LB: CHART_COLORS.categorical[5],
  DB: CHART_COLORS.categorical[6],
  PICK: CHART_COLORS.categorical[7],
  OTHER: CHART_COLORS.axisLabel,
};

function groupFor(pos) {
  const p = String(pos || "").toUpperCase();
  if (p === "QB" || p === "RB" || p === "WR" || p === "TE") return p;
  if (p === "DL" || p === "DE" || p === "DT" || p === "EDGE") return "DL";
  if (p === "LB" || p === "ILB" || p === "OLB") return "LB";
  if (p === "DB" || p === "CB" || p === "S" || p === "FS" || p === "SS") return "DB";
  if (p === "PICK") return "PICK";
  return "OTHER";
}

export default function HillCurveExplorer({
  rows,
  curves = DEFAULT_CURVES,
  width = 640,
  height = 340,
  samplePoints = 200,
  onPointClick = null,
}) {
  const box = chartBox({ width, height, margin: { left: 52, right: 100, top: 16, bottom: 40 } });

  // Determine the x-domain (rank) from the live board so the curve
  // sample and scatter share a scale.
  const ranked = (rows || []).filter(
    (r) =>
      Number.isFinite(Number(r?.rank)) &&
      r.rank > 0 &&
      Number.isFinite(Number(r?.rankDerivedValue)) &&
      r.rankDerivedValue > 0,
  );
  const maxRank = ranked.reduce((m, r) => Math.max(m, r.rank), 300);
  const xMax = Math.max(maxRank, 300);

  const x = linearScale(1, xMax, 0, box.innerWidth);
  const y = linearScale(0, 9999, box.innerHeight, 0);

  const renderableCurves = (() => {
    const normalized = normalizeCurves(curves);
    return normalized.length > 0 ? normalized : DEFAULT_CURVES;
  })();
  const curvePaths = renderableCurves.map((c, i) => {
    const pts = [];
    for (let k = 0; k <= samplePoints; k++) {
      const r = 1 + (xMax - 1) * (k / samplePoints);
      pts.push([x(r), y(hillValue(r, c))]);
    }
    return { ...c, d: linePath(pts), color: i === 0 ? CHART_COLORS.accent : categoricalColor(i) };
  });

  // Group the scatter by position.  Unknown / excluded groups fall
  // into OTHER which renders in the muted axis colour.
  const groupedScatter = {};
  for (const r of ranked) {
    const g = groupFor(r.pos);
    if (!groupedScatter[g]) groupedScatter[g] = [];
    groupedScatter[g].push({
      x: x(r.rank),
      y: y(r.rankDerivedValue),
      rank: r.rank,
      name: r.name,
      raw: r,
    });
  }
  const groupKeys = Object.keys(groupedScatter).sort();

  const xTicks = ticks(1, xMax, 6);
  const yTicks = ticks(0, 9999, 6);

  return (
    <svg
      viewBox={box.viewBox}
      width="100%"
      height={height}
      role="img"
      aria-label="Hill curve explorer with per-position scatter overlay"
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
          <g key={`x${t}`}>
            <text
              x={x(t)}
              y={box.innerHeight + 16}
              textAnchor="middle"
              fontSize={10}
              fill={CHART_COLORS.axisLabel}
            >
              {formatNumber(Math.round(t))}
            </text>
          </g>
        ))}

        {/* Scatter first, so the curves sit visually on top of dots. */}
        {groupKeys.map((g) => {
          const color = GROUP_COLORS[g] || CHART_COLORS.axisLabel;
          return (
            <g key={g}>
              {groupedScatter[g].map((s, i) => (
                <circle
                  key={i}
                  cx={s.x}
                  cy={s.y}
                  r={2.25}
                  fill={color}
                  fillOpacity={0.55}
                  style={onPointClick ? { cursor: "pointer" } : undefined}
                  onClick={onPointClick ? () => onPointClick(s.raw) : undefined}
                >
                  <title>#{s.rank} {s.name} ({g})</title>
                </circle>
              ))}
            </g>
          );
        })}

        {/* Hill curves */}
        {curvePaths.map((c) => (
          <path
            key={c.key}
            d={c.d}
            fill="none"
            stroke={c.color}
            strokeWidth={2}
            strokeDasharray={curvePaths.length > 1 ? undefined : "6 3"}
          />
        ))}

        <text
          x={box.innerWidth / 2}
          y={box.innerHeight + 30}
          textAnchor="middle"
          fontSize={11}
          fill={CHART_COLORS.axisLabel}
        >
          rank
        </text>
        <text
          transform={`rotate(-90) translate(${-box.innerHeight / 2}, ${-42})`}
          textAnchor="middle"
          fontSize={11}
          fill={CHART_COLORS.axisLabel}
        >
          Hill value
        </text>

        {/* Legend — curves + position groups.  Always shown because
            the group split is the actual payload of this chart. */}
        <g transform={`translate(${box.innerWidth + 10}, 0)`}>
          {curvePaths.map((c, i) => (
            <g key={`curve-${c.key}`} transform={`translate(0, ${i * 14})`}>
              <line x1={0} x2={18} y1={6} y2={6} stroke={c.color} strokeWidth={2} />
              <text
                x={24}
                y={6}
                dominantBaseline="middle"
                fontSize={10}
                fill={CHART_COLORS.axisLabel}
              >
                {c.label}
              </text>
            </g>
          ))}
          {groupKeys.map((g, i) => (
            <g key={`grp-${g}`} transform={`translate(0, ${curvePaths.length * 14 + 6 + i * 14})`}>
              <circle cx={9} cy={6} r={3.25} fill={GROUP_COLORS[g] || CHART_COLORS.axisLabel} fillOpacity={0.85} />
              <text
                x={24}
                y={6}
                dominantBaseline="middle"
                fontSize={10}
                fill={CHART_COLORS.axisLabel}
              >
                {g} ({groupedScatter[g].length})
              </text>
            </g>
          ))}
        </g>
      </g>
    </svg>
  );
}

// Exported so callers (tests, wiring) can stay in lockstep with the
// component's grouping rules.
export { groupFor, hillValue, normalizeCurves };

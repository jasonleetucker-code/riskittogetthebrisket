"use client";

import { useState } from "react";
import {
  CHART_COLORS,
  categoricalColor,
  chartBox,
  formatNumber,
  linearScale,
  linePath,
} from "@/lib/chart-primitives";
import { Panel } from "@/components/ds";

/**
 * YearByYear — collapsible per-season detail.  For each available
 * season, shows a per-position comparison table plus a flex line.
 *
 * Also renders a per-season trend chart at the top so the user can
 * see whether any single season looks like an outlier in the
 * combined-view share differences.
 */
const POSITIONS = ["QB", "RB", "WR", "TE"];

// Improved-method blended-score weights — must mirror the backend
// constants in src/league_comparison/metrics.py.  Used to derive
// per-season positional shares client-side from the per-season
// PositionMetrics dicts (the API doesn't pre-compute per-season
// shares to keep payload size down).
const W = {
  median: 0.35, average: 0.25, p75: 0.20, p25: 0.10, replAdj: 0.10,
};

function improvedBlended(m) {
  if (!m) return 0;
  return (
    W.median * (m.median || 0)
    + W.average * (m.average || 0)
    + W.p75 * (m.p75 || 0)
    + W.p25 * (m.p25 || 0)
    + W.replAdj * (m.replacementAdj || 0)
  );
}

function positionShares(scoresByPos) {
  const total = Object.values(scoresByPos).reduce(
    (a, v) => a + Math.max(0, v || 0), 0,
  );
  if (total <= 0) return Object.fromEntries(Object.keys(scoresByPos).map((k) => [k, 0]));
  return Object.fromEntries(
    Object.entries(scoresByPos).map(([k, v]) => [k, (Math.max(0, v) / total) * 100]),
  );
}

export default function YearByYear({ data }) {
  const bySeason = data?.bySeason || {};
  const seasons = Object.keys(bySeason).sort().reverse(); // newest first
  const [openSeason, setOpenSeason] = useState(seasons[0] || null);

  if (seasons.length === 0) {
    return (
      <Panel>
        <p className="muted">No per-season data available.</p>
      </Panel>
    );
  }

  return (
    <Panel>
      <h2 className="section-title">Year-by-Year Detail</h2>
      <p className="muted text-sm" style={{ marginTop: 6 }}>
        Each season is computed independently and then equally averaged for the
        combined view.  Click a season to expand its detailed breakdown.
      </p>
      <ShareTrendChart bySeason={bySeason} />
      <div style={{ marginTop: "var(--space-sm)", display: "flex", flexDirection: "column", gap: 8 }}>
        {seasons.map((season) => (
          <SeasonRow
            key={season}
            season={season}
            block={bySeason[season]}
            open={openSeason === season}
            onToggle={() => setOpenSeason(openSeason === season ? null : season)}
          />
        ))}
      </div>
    </Panel>
  );
}

// ── Trend chart: positional share diff (my − baseline) per season ──
//
// Useful as a sanity check on the combined view: if a single season
// dragged the average sharply, you see it here as a spike or a
// crossing zero line.  X-axis is seasons (oldest → newest), one line
// per offense position, y-axis is share difference in pp.  A
// horizontal zero line marks "perfectly aligned with baseline".
function ShareTrendChart({ bySeason }) {
  const seasons = Object.keys(bySeason).sort();
  if (seasons.length < 2) {
    // Single season → trend is not meaningful; just skip.
    return null;
  }

  const series = POSITIONS.map((pos) => ({
    pos,
    points: seasons.map((season) => {
      const block = bySeason[season] || {};
      const myPos = block.my?.positions || {};
      const basePos = block.baseline?.positions || {};
      const myScores = Object.fromEntries(POSITIONS.map((p) => [p, improvedBlended(myPos[p])]));
      const baseScores = Object.fromEntries(POSITIONS.map((p) => [p, improvedBlended(basePos[p])]));
      const myShares = positionShares(myScores);
      const baseShares = positionShares(baseScores);
      return (myShares[pos] || 0) - (baseShares[pos] || 0);
    }),
  }));

  const allDiffs = series.flatMap((s) => s.points);
  const maxAbs = Math.max(1, ...allDiffs.map((v) => Math.abs(v)));
  const yLo = -maxAbs;
  const yHi = maxAbs;

  const width = 640;
  const height = 220;
  const { innerWidth, innerHeight, viewBox, plotTransform, margin } = chartBox({
    width, height, margin: { top: 16, right: 16, bottom: 30, left: 44 },
  });

  const xScale = linearScale(0, Math.max(1, seasons.length - 1), 0, innerWidth);
  const yScale = linearScale(yLo, yHi, innerHeight, 0);

  return (
    <div style={{ marginTop: "var(--space-sm)" }}>
      <div className="muted text-xs" style={{ textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>
        Share difference (my − baseline) by season — improved method
      </div>
      <div style={{ background: "rgba(0,0,0,0.15)", borderRadius: 6, padding: 8 }}>
        <svg
          viewBox={viewBox}
          role="img"
          aria-label="Per-season positional share difference trend"
          style={{ width: "100%", height: "auto" }}
        >
          <g transform={plotTransform}>
            {/* Zero line */}
            <line
              x1={0} x2={innerWidth}
              y1={yScale(0)} y2={yScale(0)}
              stroke={CHART_COLORS.axis}
              strokeDasharray="4 3"
            />
            {/* Y-axis ticks */}
            {[yLo, yLo / 2, 0, yHi / 2, yHi].map((v, i) => (
              <g key={i}>
                <line
                  x1={0} x2={innerWidth}
                  y1={yScale(v)} y2={yScale(v)}
                  stroke={CHART_COLORS.grid}
                  strokeOpacity={0.4}
                />
                <text
                  x={-6} y={yScale(v) + 3}
                  textAnchor="end" fontSize={10}
                  fill={CHART_COLORS.axisLabel}
                >
                  {(v >= 0 ? "+" : "") + formatNumber(v, 1)}
                </text>
              </g>
            ))}
            {/* X-axis season labels */}
            {seasons.map((season, i) => (
              <text
                key={season}
                x={xScale(i)} y={innerHeight + 16}
                textAnchor="middle" fontSize={11}
                fill={CHART_COLORS.axisLabel}
              >
                {season}
              </text>
            ))}
            {/* Series lines + markers */}
            {series.map((s, idx) => {
              const color = categoricalColor(idx);
              const pts = s.points.map((v, i) => [xScale(i), yScale(v)]);
              return (
                <g key={s.pos}>
                  <path
                    d={linePath(pts)}
                    fill="none"
                    stroke={color}
                    strokeWidth={2}
                  />
                  {pts.map(([cx, cy], i) => (
                    <circle key={i} cx={cx} cy={cy} r={3.5} fill={color}>
                      <title>{`${s.pos} ${seasons[i]}: ${(s.points[i] >= 0 ? "+" : "") + formatNumber(s.points[i], 2)} pp`}</title>
                    </circle>
                  ))}
                </g>
              );
            })}
          </g>
          {/* Legend (bottom-right of chart area) */}
          <g transform={`translate(${margin.left}, ${height - 4})`}>
            {series.map((s, idx) => (
              <g key={s.pos} transform={`translate(${idx * 56}, -18)`}>
                <rect x={0} y={-7} width={10} height={3} fill={categoricalColor(idx)} />
                <text x={14} y={-4} fontSize={10} fill={CHART_COLORS.axisLabel}>{s.pos}</text>
              </g>
            ))}
          </g>
        </svg>
      </div>
    </div>
  );
}

function SeasonRow({ season, block, open, onToggle }) {
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 6, overflow: "hidden" }}>
      <button
        type="button"
        onClick={onToggle}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 14px",
          background: "rgba(255,255,255,0.04)",
          border: "none",
          color: "var(--text)",
          cursor: "pointer",
          fontSize: "1rem",
          fontWeight: 700,
        }}
      >
        <span>Season {season}</span>
        <span className="muted">{open ? "▼" : "▸"}</span>
      </button>
      {open && (
        <div style={{ padding: "var(--space-sm)" }}>
          <SeasonTables block={block} />
        </div>
      )}
    </div>
  );
}

function SeasonTables({ block }) {
  if (!block) return <p className="muted">No data for this season.</p>;
  const my = block.my || {};
  const base = block.baseline || {};
  return (
    <div style={{ display: "grid", gap: "var(--space-md)", gridTemplateColumns: "1fr 1fr" }}>
      <SeasonSide title="My League" data={my} accent="cyan" />
      <SeasonSide title="Standard Baseline" data={base} accent="gold" />
    </div>
  );
}

function SeasonSide({ title, data, accent }) {
  const color = accent === "gold" ? "var(--gold, #FFC704)" : "var(--cyan)";
  const positions = data.positions || {};
  const flex = data.flex || {};
  const top = (data.topPlayers || []).slice(0, 8);
  return (
    <div>
      <div style={{ fontWeight: 700, color, marginBottom: 6 }}>{title}</div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Pos</th>
              <th style={{ textAlign: "right" }}>Avg</th>
              <th style={{ textAlign: "right" }}>Med</th>
              <th style={{ textAlign: "right" }}>P25</th>
              <th style={{ textAlign: "right" }}>P75</th>
              <th style={{ textAlign: "right" }}>Repl</th>
              <th style={{ textAlign: "right" }}>n</th>
            </tr>
          </thead>
          <tbody>
            {POSITIONS.map((pos) => {
              const m = positions[pos];
              if (!m) return null;
              return (
                <tr key={pos}>
                  <td style={{ fontWeight: 600 }}>{pos}</td>
                  <td style={mono()}>{fmt(m.average)}</td>
                  <td style={mono()}>{fmt(m.median)}</td>
                  <td style={mono()}>{fmt(m.p25)}</td>
                  <td style={mono()}>{fmt(m.p75)}</td>
                  <td style={mono()}>{fmt(m.replacementLevel)}</td>
                  <td style={mono()}>{m.sampleSize}</td>
                </tr>
              );
            })}
            <tr>
              <td style={{ fontWeight: 600 }}>FLEX</td>
              <td style={mono()}>{fmt(flex.average)}</td>
              <td style={mono()}>{fmt(flex.median)}</td>
              <td style={mono()}>{fmt(flex.p25)}</td>
              <td style={mono()}>{fmt(flex.p75)}</td>
              <td style={mono()}>{fmt(flex.replacementLevel)}</td>
              <td style={mono()}>{flex.sampleSize || 0}</td>
            </tr>
          </tbody>
        </table>
      </div>
      {top.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div className="muted text-xs" style={{ textTransform: "uppercase", letterSpacing: 0.5 }}>
            Top players — blended score (volume + pace)
          </div>
          <ol className="text-xs" style={{ marginTop: 4, paddingLeft: 20, lineHeight: 1.7 }}>
            {top.map((p) => (
              <li key={p.playerId}>
                <strong>{p.name}</strong>{" "}
                <span className="muted">({p.position})</span>{" "}
                <span style={{ fontFamily: "var(--mono)" }}>{fmt(p.blendedScore)}</span>
                <span className="muted" style={{ marginLeft: 6 }}>
                  · {fmt(p.totalPoints)} pts in {p.gamesPlayed} g{" "}
                  ({fmt(p.pointsPerGame)} ppg)
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function fmt(v) { return v == null ? "—" : Number(v).toFixed(1); }
function mono() { return { textAlign: "right", fontFamily: "var(--mono)" }; }

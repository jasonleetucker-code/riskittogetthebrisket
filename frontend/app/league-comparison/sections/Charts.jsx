"use client";

import {
  CHART_COLORS,
  chartBox,
  formatNumber,
  linearScale,
} from "@/lib/chart-primitives";
import { Panel } from "@/components/ds";

/**
 * ComparisonCharts — pure-SVG charts for the summary tab.
 *
 * Three charts:
 *   1. Grouped bar — standard vs my for QB/RB/WR/TE blended scores.
 *   2. Stacked bar — positional share % per league.
 *   3. Diff bar    — signed share differences by position.
 */
const POSITIONS = ["QB", "RB", "WR", "TE"];

export default function ComparisonCharts({ data, method }) {
  const positions = data?.positions || {};

  const scoreSeries = POSITIONS.map((pos) => {
    const c = positions[pos];
    if (!c) return { pos, mine: 0, base: 0 };
    return {
      pos,
      mine: method === "legacy" ? c.my?.legacyScore || 0 : c.my?.improvedScore || 0,
      base: method === "legacy" ? c.baseline?.legacyScore || 0 : c.baseline?.improvedScore || 0,
    };
  });

  const shareSeries = POSITIONS.map((pos) => {
    const c = positions[pos];
    if (!c) return { pos, mine: 0, base: 0 };
    return {
      pos,
      mine: method === "legacy" ? c.my?.shareLegacy || 0 : c.my?.shareImproved || 0,
      base: method === "legacy" ? c.baseline?.shareLegacy || 0 : c.baseline?.shareImproved || 0,
    };
  });

  const diffSeries = POSITIONS.map((pos) => {
    const c = positions[pos];
    if (!c) return { pos, diff: 0 };
    return {
      pos,
      diff: method === "legacy" ? c.diffPpLegacy || 0 : c.diffPpImproved || 0,
    };
  });

  return (
    <Panel>
      <h2 className="section-title">Charts</h2>
      <div style={{ display: "grid", gap: "var(--space-md)", gridTemplateColumns: "1fr 1fr", marginTop: "var(--space-sm)" }}>
        <ChartPanel title="Blended Score by Position">
          <GroupedBarChart
            rows={scoreSeries}
            mineLabel="My League"
            baseLabel="Standard"
            valueFmt={(v) => formatNumber(v, 0)}
          />
        </ChartPanel>
        <ChartPanel title="Positional Share (%)">
          <GroupedBarChart
            rows={shareSeries}
            mineLabel="My League"
            baseLabel="Standard"
            valueFmt={(v) => `${formatNumber(v, 1)}%`}
          />
        </ChartPanel>
        <ChartPanel title="Share Difference (pp)" wide>
          <DiffBarChart rows={diffSeries} />
        </ChartPanel>
      </div>
    </Panel>
  );
}

function ChartPanel({ title, children, wide }) {
  return (
    <div style={{ gridColumn: wide ? "1 / -1" : "auto" }}>
      <div className="muted text-xs" style={{ textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>
        {title}
      </div>
      <div style={{ background: "rgba(0,0,0,0.15)", borderRadius: 6, padding: 8 }}>
        {children}
      </div>
    </div>
  );
}

// ── Grouped bar chart ──────────────────────────────────────────────
function GroupedBarChart({ rows, mineLabel = "Mine", baseLabel = "Base", valueFmt }) {
  const width = 480;
  const height = 220;
  const { margin, innerWidth, innerHeight, viewBox, plotTransform } = chartBox({
    width, height, margin: { top: 16, right: 16, bottom: 36, left: 44 },
  });

  const maxVal = Math.max(
    ...rows.flatMap((r) => [r.mine, r.base]),
    1,
  );
  const yScale = linearScale(0, maxVal, innerHeight, 0);
  const groupW = innerWidth / Math.max(rows.length, 1);
  const barW = (groupW - 12) / 2;

  return (
    <svg viewBox={viewBox} role="img" aria-label="Grouped bar chart" style={{ width: "100%", height: "auto" }}>
      <g transform={plotTransform}>
        {/* Y-axis */}
        <line x1={0} x2={0} y1={0} y2={innerHeight} stroke={CHART_COLORS.axis} />
        <line x1={0} x2={innerWidth} y1={innerHeight} y2={innerHeight} stroke={CHART_COLORS.axis} />
        {[0, 0.25, 0.5, 0.75, 1].map((t, i) => {
          const v = maxVal * t;
          const y = yScale(v);
          return (
            <g key={i}>
              <line x1={0} x2={innerWidth} y1={y} y2={y} stroke={CHART_COLORS.grid} strokeOpacity={0.5} />
              <text x={-6} y={y + 3} textAnchor="end" fontSize={10} fill={CHART_COLORS.axisLabel}>
                {valueFmt ? valueFmt(v) : formatNumber(v, 0)}
              </text>
            </g>
          );
        })}
        {rows.map((r, i) => {
          const cx = i * groupW + 6;
          return (
            <g key={r.pos}>
              <rect
                x={cx}
                y={yScale(r.base)}
                width={barW}
                height={Math.max(0, innerHeight - yScale(r.base))}
                fill={CHART_COLORS.accentMuted}
              >
                <title>{`${baseLabel} ${r.pos}: ${valueFmt ? valueFmt(r.base) : formatNumber(r.base, 1)}`}</title>
              </rect>
              <rect
                x={cx + barW + 4}
                y={yScale(r.mine)}
                width={barW}
                height={Math.max(0, innerHeight - yScale(r.mine))}
                fill={CHART_COLORS.accent}
              >
                <title>{`${mineLabel} ${r.pos}: ${valueFmt ? valueFmt(r.mine) : formatNumber(r.mine, 1)}`}</title>
              </rect>
              <text
                x={cx + barW + 2}
                y={innerHeight + 14}
                textAnchor="middle"
                fontSize={11}
                fill={CHART_COLORS.axisLabel}
                fontWeight={600}
              >
                {r.pos}
              </text>
            </g>
          );
        })}
      </g>
      {/* Legend */}
      <g transform={`translate(${margin.left}, ${height - 8})`}>
        <rect x={0} y={-8} width={10} height={10} fill={CHART_COLORS.accentMuted} />
        <text x={14} y={1} fontSize={10} fill={CHART_COLORS.axisLabel}>{baseLabel}</text>
        <rect x={70} y={-8} width={10} height={10} fill={CHART_COLORS.accent} />
        <text x={84} y={1} fontSize={10} fill={CHART_COLORS.axisLabel}>{mineLabel}</text>
      </g>
    </svg>
  );
}

// ── Signed difference bar chart ─────────────────────────────────────
function DiffBarChart({ rows }) {
  const width = 720;
  const height = 200;
  const { innerWidth, innerHeight, viewBox, plotTransform } = chartBox({
    width, height, margin: { top: 12, right: 20, bottom: 36, left: 50 },
  });

  const maxAbs = Math.max(1, ...rows.map((r) => Math.abs(r.diff || 0)));
  const xMid = innerHeight / 2;
  const yScale = linearScale(-maxAbs, maxAbs, innerHeight, 0);
  const barW = innerWidth / Math.max(rows.length, 1) - 16;

  return (
    <svg viewBox={viewBox} role="img" aria-label="Difference bar chart" style={{ width: "100%", height: "auto" }}>
      <g transform={plotTransform}>
        <line x1={0} x2={innerWidth} y1={xMid} y2={xMid} stroke={CHART_COLORS.axis} />
        {rows.map((r, i) => {
          const cx = i * (innerWidth / rows.length) + 8;
          const y0 = yScale(0);
          const y1 = yScale(r.diff);
          const top = Math.min(y0, y1);
          const h = Math.max(1, Math.abs(y1 - y0));
          const color = Math.abs(r.diff) <= 0.5 ? CHART_COLORS.success
                      : Math.abs(r.diff) <= 1.5 ? CHART_COLORS.accent
                      : Math.abs(r.diff) <= 3   ? CHART_COLORS.warn
                      :                            CHART_COLORS.danger;
          return (
            <g key={r.pos}>
              <rect x={cx} y={top} width={barW} height={h} fill={color}>
                <title>{`${r.pos}: ${r.diff >= 0 ? "+" : ""}${formatNumber(r.diff, 2)} pp`}</title>
              </rect>
              <text
                x={cx + barW / 2}
                y={innerHeight + 14}
                textAnchor="middle"
                fontSize={11}
                fill={CHART_COLORS.axisLabel}
                fontWeight={600}
              >
                {r.pos}
              </text>
              <text
                x={cx + barW / 2}
                y={r.diff >= 0 ? top - 3 : top + h + 11}
                textAnchor="middle"
                fontSize={10}
                fill={color}
              >
                {(r.diff >= 0 ? "+" : "") + formatNumber(r.diff, 2)}
              </text>
            </g>
          );
        })}
        {/* y-axis ticks */}
        {[-maxAbs, -maxAbs / 2, 0, maxAbs / 2, maxAbs].map((v, i) => (
          <text
            key={i}
            x={-8}
            y={yScale(v) + 3}
            textAnchor="end"
            fontSize={10}
            fill={CHART_COLORS.axisLabel}
          >
            {(v >= 0 ? "+" : "") + formatNumber(v, 1)}
          </text>
        ))}
      </g>
    </svg>
  );
}

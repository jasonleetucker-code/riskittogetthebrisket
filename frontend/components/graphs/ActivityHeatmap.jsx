"use client";

// ── Chart 2: activity heatmap ────────────────────────────────────────
// GitHub-contributions-style calendar grid: columns = weeks, rows =
// days of the week, cell color opacity = trade count for that day.
//
// Caveat: the activity feed is pagination-limited to 200 trades, so
// leagues with very high trade volume over long periods may see the
// earliest days empty.  The component just renders whatever it's
// given; upstream decides the window.
//
// Input:
//   events = [{ createdAt: unix-seconds-or-ms | ISO-date-string }]
// ─────────────────────────────────────────────────────────────────────

import { CHART_COLORS, chartBox, linearScale } from "../../lib/chart-primitives.js";

function toDayKey(d) {
  // Normalise to UTC YYYY-MM-DD so two events on the same calendar
  // day always share a bucket regardless of timezone ambiguity in
  // the source data.
  const yyyy = d.getUTCFullYear();
  const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(d.getUTCDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function toDate(createdAt) {
  if (typeof createdAt === "number") {
    // Seconds vs ms: values < 1e12 are seconds; multiply.
    return new Date(createdAt < 1e12 ? createdAt * 1000 : createdAt);
  }
  if (typeof createdAt === "string") {
    const d = new Date(createdAt);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  return null;
}

function bucketByDay(events) {
  const counts = new Map();
  for (const e of events || []) {
    const d = toDate(e?.createdAt);
    if (!d) continue;
    const k = toDayKey(d);
    counts.set(k, (counts.get(k) || 0) + 1);
  }
  return counts;
}

export default function ActivityHeatmap({
  events,
  weeks = 26, // show ~6 months by default
  cellSize = 12,
  cellGap = 2,
  endDate = null,
}) {
  const counts = bucketByDay(events);

  // Determine the heatmap window.  End defaults to "today" or the
  // latest event date if no end date was supplied.
  const end = endDate ? new Date(endDate) : new Date();
  // Snap end to Saturday so each column represents a full Sunday-to-Saturday week.
  const endDow = end.getUTCDay(); // 0=Sun..6=Sat
  const snapEnd = new Date(end);
  snapEnd.setUTCDate(snapEnd.getUTCDate() + (6 - endDow));
  const totalDays = weeks * 7;
  const start = new Date(snapEnd);
  start.setUTCDate(start.getUTCDate() - (totalDays - 1));

  const cells = [];
  const d = new Date(start);
  for (let i = 0; i < totalDays; i++) {
    const col = Math.floor(i / 7);
    const row = d.getUTCDay();
    const key = toDayKey(d);
    cells.push({
      col,
      row,
      date: new Date(d),
      count: counts.get(key) || 0,
    });
    d.setUTCDate(d.getUTCDate() + 1);
  }

  const maxCount = Math.max(1, ...cells.map((c) => c.count));
  const opacityScale = linearScale(0, maxCount, 0, 1);

  const cols = weeks;
  const width = cols * (cellSize + cellGap) + 40;
  const height = 7 * (cellSize + cellGap) + 36;
  const box = chartBox({
    width,
    height,
    margin: { left: 28, right: 12, top: 18, bottom: 16 },
  });

  const dayLabels = ["S", "M", "T", "W", "T", "F", "S"];

  if (cells.every((c) => c.count === 0)) {
    return (
      <div className="chart-empty" style={{ padding: 12, color: CHART_COLORS.axisLabel }}>
        No activity in this window.
      </div>
    );
  }

  return (
    <svg
      viewBox={box.viewBox}
      width="100%"
      height={height}
      role="img"
      aria-label="Trade activity heatmap"
    >
      <g transform={box.plotTransform}>
        {dayLabels.map((l, i) => (
          <text
            key={i}
            x={-6}
            y={i * (cellSize + cellGap) + cellSize / 2}
            textAnchor="end"
            dominantBaseline="middle"
            fontSize={9}
            fill={CHART_COLORS.axisLabel}
          >
            {l}
          </text>
        ))}

        {cells.map((c, i) => {
          const x = c.col * (cellSize + cellGap);
          const y = c.row * (cellSize + cellGap);
          const fill =
            c.count === 0 ? CHART_COLORS.grid : CHART_COLORS.accent;
          const opacity = c.count === 0 ? 0.4 : 0.2 + 0.8 * opacityScale(c.count);
          return (
            <rect
              key={i}
              x={x}
              y={y}
              width={cellSize}
              height={cellSize}
              fill={fill}
              fillOpacity={opacity}
              rx={2}
            >
              <title>
                {c.date.toISOString().slice(0, 10)}: {c.count} {c.count === 1 ? "event" : "events"}
              </title>
            </rect>
          );
        })}

        {/* Legend — low → high opacity indicator */}
        <g transform={`translate(0, ${7 * (cellSize + cellGap) + 6})`}>
          <text x={0} y={8} fontSize={9} fill={CHART_COLORS.axisLabel}>
            less
          </text>
          {[0.2, 0.4, 0.6, 0.8, 1.0].map((op, i) => (
            <rect
              key={i}
              x={28 + i * (cellSize + 2)}
              y={0}
              width={cellSize}
              height={cellSize}
              fill={CHART_COLORS.accent}
              fillOpacity={op}
              rx={2}
            />
          ))}
          <text x={28 + 5 * (cellSize + 2) + 4} y={8} fontSize={9} fill={CHART_COLORS.axisLabel}>
            more
          </text>
        </g>
      </g>
    </svg>
  );
}

export { bucketByDay, toDayKey };

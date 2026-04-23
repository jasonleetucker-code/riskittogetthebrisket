"use client";

import { useMemo } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useRankHistory } from "@/components/useRankHistory";
import {
  computeTeamValueSeries,
  valueFromRank,
} from "@/lib/value-history";

/**
 * TeamValueChart — team-level aggregate value over time.
 *
 * Sums Hill-curve values across the current roster at each historical
 * date for which every roster player has coverage.  That "full
 * coverage only" rule means the chart doesn't drift when a player is
 * added mid-window — the series either covers the full window or
 * starts later, never mid-player.
 *
 * Renders as a lightweight SVG area chart.  No external chart lib —
 * this is the only team-level chart we need and it's <80 lines of
 * SVG; adding a dependency would be overkill.
 *
 * Props:
 *   - width, height    chart dimensions
 *   - showSummary      render the value + delta summary above the line
 */
export default function TeamValueChart({
  width = 320,
  height = 80,
  showSummary = true,
}) {
  const { rawData } = useApp();
  const { selectedTeam } = useTeam();
  const { history, loading } = useRankHistory({ days: 30 });

  const series = useMemo(() => {
    const rosterNames = selectedTeam?.players || [];
    if (!rosterNames.length || !history) return [];
    return computeTeamValueSeries({
      rosterNames,
      history,
      valueFromRank,
    });
  }, [selectedTeam, history]);

  const { path, area, summary, firstValue, lastValue, minValue, maxValue } = useMemo(() => {
    if (series.length < 2) {
      return {
        path: null,
        area: null,
        summary: null,
        firstValue: null,
        lastValue: null,
        minValue: null,
        maxValue: null,
      };
    }

    const values = series.map((p) => p.value);
    const minV = Math.min(...values);
    const maxV = Math.max(...values);
    const span = maxV - minV || 1;

    const tFirst = series[0].t;
    const tLast = series[series.length - 1].t;
    const tSpan = tLast - tFirst || 1;

    const padX = 2;
    const padY = 4;
    const usableW = width - padX * 2;
    const usableH = height - padY * 2;

    const toX = (t) => padX + ((t - tFirst) / tSpan) * usableW;
    const toY = (v) => padY + (1 - (v - minV) / span) * usableH;

    const lineParts = series.map((p, i) => `${i === 0 ? "M" : "L"}${toX(p.t).toFixed(1)},${toY(p.value).toFixed(1)}`);
    const pathStr = lineParts.join(" ");
    const areaStr = `${pathStr} L${toX(tLast).toFixed(1)},${(height - padY).toFixed(1)} L${toX(tFirst).toFixed(1)},${(height - padY).toFixed(1)} Z`;

    const first = series[0].value;
    const last = series[series.length - 1].value;
    const delta = last - first;

    return {
      path: pathStr,
      area: areaStr,
      firstValue: first,
      lastValue: last,
      minValue: minV,
      maxValue: maxV,
      summary: { first, last, delta },
    };
  }, [series, width, height]);

  const emptyReason = (() => {
    if (!selectedTeam) return "Pick a team to see the value series.";
    if (loading) return "Loading…";
    if (series.length < 2) return "Insufficient history for a trend.";
    return null;
  })();

  return (
    <div className="team-value-chart" role="group" aria-label="Team value over time">
      {showSummary && summary && (
        <div className="team-value-chart-summary">
          <span className="team-value-chart-current">
            {summary.last.toLocaleString()}
          </span>
          <span
            className={`team-value-chart-delta team-value-chart-delta--${summary.delta >= 0 ? "up" : "down"}`}
          >
            {summary.delta >= 0 ? "▲" : "▼"} {Math.abs(summary.delta).toLocaleString()}
          </span>
          <span className="team-value-chart-window">30d</span>
        </div>
      )}
      {emptyReason ? (
        <div className="team-value-chart-empty" role="status">{emptyReason}</div>
      ) : (
        <svg
          className="team-value-chart-svg"
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          aria-hidden="true"
          focusable="false"
          preserveAspectRatio="none"
        >
          {area && (
            <path
              d={area}
              fill={summary?.delta >= 0 ? "rgba(52, 211, 153, 0.12)" : "rgba(248, 113, 113, 0.12)"}
              stroke="none"
            />
          )}
          {path && (
            <path
              d={path}
              fill="none"
              stroke={summary?.delta >= 0 ? "var(--green)" : "var(--red)"}
              strokeWidth={1.5}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}
        </svg>
      )}
    </div>
  );
}

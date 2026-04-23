"use client";

import { useMemo } from "react";
import { buildSparklinePath, normalizePoints } from "@/lib/value-history";

/**
 * Sparkline — pure SVG rank-over-time glyph.
 *
 * Rank series are inverted (lower rank = higher pixel) so the line
 * visually rises when a player is rising.  Decorative by default:
 * no axes, no labels, AT-hidden.  Callers pass raw points or an
 * already-normalized series; the component memoizes the path build.
 *
 * Colors:
 *   tone="auto"  → derives from first/last rank trend (cyan up, red down, muted flat)
 *   tone="cyan"  → forced gold/cyan
 *   tone="muted" → muted purple
 */
export default function Sparkline({
  points,
  width = 64,
  height = 20,
  tone = "auto",
  strokeWidth = 1.25,
}) {
  const { path, trend, normalized } = useMemo(() => {
    const norm = normalizePoints(points);
    return {
      path: buildSparklinePath(norm, { width, height }),
      trend: computeTrendTone(norm),
      normalized: norm,
    };
  }, [points, width, height]);

  if (!path) {
    return (
      <span
        className="sparkline sparkline--empty"
        style={{ width, height }}
        aria-hidden="true"
      />
    );
  }

  const effectiveTone = tone === "auto" ? trend : tone;
  const stroke =
    effectiveTone === "up"
      ? "var(--green)"
      : effectiveTone === "down"
        ? "var(--red)"
        : effectiveTone === "cyan"
          ? "var(--cyan)"
          : "var(--muted)";

  return (
    <svg
      className={`sparkline sparkline--${effectiveTone}`}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
      focusable="false"
    >
      <path
        d={path}
        fill="none"
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {normalized.length > 0 && (
        <circle
          cx={Number.parseFloat(lastX(path))}
          cy={Number.parseFloat(lastY(path))}
          r={1.6}
          fill={stroke}
        />
      )}
    </svg>
  );
}

function lastX(path) {
  const tokens = path.split(/\s+/).filter(Boolean);
  const last = tokens[tokens.length - 1] || "";
  const coords = last.replace(/^[ML]/, "").split(",");
  return coords[0] || "0";
}

function lastY(path) {
  const tokens = path.split(/\s+/).filter(Boolean);
  const last = tokens[tokens.length - 1] || "";
  const coords = last.replace(/^[ML]/, "").split(",");
  return coords[1] || "0";
}

function computeTrendTone(points) {
  if (!points || points.length < 2) return "muted";
  const first = points[0].rank;
  const last = points[points.length - 1].rank;
  // Lower rank = better.  If last < first, player rose.
  if (last < first - 0.5) return "up";
  if (last > first + 0.5) return "down";
  return "muted";
}

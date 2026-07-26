/**
 * Sparkline + Meter — the design system's small chart primitives.
 * Larger charts continue to compose lib/chart-primitives.js scales; these
 * cover the two shapes the terminal repeats everywhere: an inline trend
 * and a proportional bar.
 *
 * Method (dataviz skill): 2px line weight, no grid/axes at this size,
 * endpoint dot as the only marker, color follows the ENTITY via the
 * validated --chart-* slots (fixed order, never cycled), direction is
 * never encoded by color alone (pair with <Movement>), and every SVG
 * carries role="img" + aria-label (label prop is required).
 *
 * <Sparkline>
 *   values   number[] (required)
 *   label    string   (required) — accessible description
 *   width    px (default 96)   height px (default 24)
 *   series   1-6 — chart slot (default 1); or `stroke` to override
 *   baseline optional number — draws a dashed reference line (e.g. 0)
 *
 * <Meter> — proportional bar with value text (never a lone bar):
 *   value, max (required), label (required), format?, series?
 */
import React from "react";

export function Sparkline({
  values,
  label,
  width = 96,
  height = 24,
  series = 1,
  stroke,
  baseline,
  className = "",
}) {
  if (!Array.isArray(values) || values.length < 2) return null;
  const pad = 2.5;
  const min = Math.min(...values, baseline ?? Infinity);
  const max = Math.max(...values, baseline ?? -Infinity);
  const span = max - min || 1;
  const x = (i) => pad + (i / (values.length - 1)) * (width - pad * 2);
  const y = (v) => pad + (1 - (v - min) / span) * (height - pad * 2);
  const d = values
    .map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)
    .join("");
  const color = stroke || `var(--chart-${Math.min(6, Math.max(1, series))})`;
  const lastX = x(values.length - 1);
  const lastY = y(values[values.length - 1]);

  return (
    <svg
      className={`ds-sparkline ${className}`.trim()}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={label}
    >
      {baseline != null ? (
        <line
          x1={pad}
          x2={width - pad}
          y1={y(baseline)}
          y2={y(baseline)}
          stroke="var(--chart-axis)"
          strokeWidth="1"
          strokeDasharray="2 3"
        />
      ) : null}
      <path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={lastX} cy={lastY} r="2.5" fill={color} />
    </svg>
  );
}

export function Meter({ value, max, label, format, series = 1, className = "" }) {
  const safeMax = max || 1;
  const pct = Math.max(0, Math.min(1, value / safeMax)) * 100;
  const text = format ? format(value) : value.toLocaleString("en-US");
  return (
    <div
      className={`ds-meter ${className}`.trim()}
      role="img"
      aria-label={`${label}: ${text}`}
    >
      <span className="ds-meter__track">
        <span
          className="ds-meter__fill"
          style={{
            width: `${pct}%`,
            background: `var(--chart-${Math.min(6, Math.max(1, series))})`,
          }}
        />
      </span>
      <span className="ds-meter__value" aria-hidden="true">
        {text}
      </span>
    </div>
  );
}

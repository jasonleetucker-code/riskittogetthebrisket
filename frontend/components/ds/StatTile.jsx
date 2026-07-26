/**
 * StatTile — the ONE KPI/stat primitive (the audit found 3 competing
 * implementations). Label + value + optional movement/meta, value always
 * in the data face with tabular figures.
 *
 * Usage:
 *   <StatTile label="Roster value" value="48,210"
 *             movement={<Movement delta={340} confidence={0.8} />} />
 *   <StatTile size="lg" label="League rank" value="#2" meta="of 12" bare />
 *
 * Props:
 *   label    string (required) — uppercase micro-label
 *   value    ReactNode (required) — preformatted display value
 *   movement ReactNode — a <Movement> (or any signal) beside the meta
 *   meta     ReactNode — quiet context ("of 12", "vs last week")
 *   size     "md" | "lg"
 *   bare     boolean — no box; for use INSIDE a Panel row
 *
 * Rows of tiles belong in a CSS grid owned by the page/panel — StatTile
 * never sets its own margins.
 */
import React from "react";

export function StatTile({
  label,
  value,
  movement,
  meta,
  size = "md",
  bare = false,
  className = "",
  ...rest
}) {
  const classes = [
    "ds-stat",
    size === "lg" ? "ds-stat--lg" : "",
    bare ? "ds-stat--bare" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={classes} {...rest}>
      <span className="ds-stat__label">{label}</span>
      <span className="ds-stat__value">{value}</span>
      {movement || meta ? (
        <span className="ds-stat__meta">
          {movement}
          {meta ? <span>{meta}</span> : null}
        </span>
      ) : null}
    </div>
  );
}

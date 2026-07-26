/**
 * Skeleton — loading placeholders. Extends the well-built (but unused —
 * one importer app-wide) components/ui/Skeleton with token-based styling
 * and table/stat variants, so every async surface can drop its
 * "Loading..." string (the audit counted 152 of them).
 *
 * API superset of the legacy component, so migration is a re-import:
 *   <Skeleton width={120} height={16} />
 *   <SkeletonText lines={3} />
 *   <SkeletonRow columns={5} />
 *   <SkeletonTable rows={8} columns={6} />   // pair with Panel flush
 *   <SkeletonStat />                          // matches StatTile geometry
 *
 * Rules: skeletons are px-sized to the content they replace (no CLS),
 * aria-hidden (the SURFACE announces loading via its own live region,
 * not the bones), and reduced-motion drops the shimmer (ds.css).
 */
import React from "react";

export function Skeleton({ width = "100%", height = 16, className = "", style }) {
  return (
    <span
      className={`ds-skeleton ${className}`.trim()}
      aria-hidden="true"
      style={{ width, height, ...style }}
    />
  );
}

export function SkeletonText({ lines = 3, gap = 8 }) {
  return (
    <div
      aria-hidden="true"
      style={{ display: "flex", flexDirection: "column", gap }}
    >
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} width={i === lines - 1 ? "70%" : "95%"} height={13} />
      ))}
    </div>
  );
}

export function SkeletonRow({ columns = 4, height = 32, gap = 12 }) {
  return (
    <div
      aria-hidden="true"
      style={{ display: "flex", gap, alignItems: "center", height }}
    >
      {Array.from({ length: columns }).map((_, i) => (
        <Skeleton
          key={i}
          width={i === 0 ? "24%" : `${Math.round(76 / Math.max(1, columns - 1))}%`}
          height={Math.round(height * 0.55)}
        />
      ))}
    </div>
  );
}

export function SkeletonTable({ rows = 6, columns = 5 }) {
  return (
    <div aria-hidden="true" style={{ padding: "var(--space-3)" }}>
      <SkeletonRow columns={columns} height={28} />
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonRow key={i} columns={columns} height={34} />
      ))}
    </div>
  );
}

export function SkeletonStat() {
  return (
    <div
      aria-hidden="true"
      className="ds-stat"
      style={{ gap: "var(--space-2)" }}
    >
      <Skeleton width="40%" height={10} />
      <Skeleton width="65%" height={22} />
    </div>
  );
}

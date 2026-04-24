/**
 * Skeleton screen primitive — replaces spinners for perceived
 * loading speed.
 *
 * CSS animation uses `prefers-reduced-motion` to skip the shimmer
 * for users who opt out.
 *
 * Variants:
 *   - <Skeleton width="..." height="..." />  (base)
 *   - <SkeletonRow columns={4} />             (rankings-style row)
 *   - <SkeletonCard lines={3} />              (card body stub)
 *
 * Sized in CSS px so there's no layout shift when real content
 * replaces the skeleton.
 */
"use client";

import React from "react";


const BASE_STYLE = {
  display: "inline-block",
  background: "linear-gradient(90deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.04) 100%)",
  backgroundSize: "200% 100%",
  borderRadius: "var(--radius-sm, 4px)",
  animation: "skeleton-shimmer 1.5s ease-in-out infinite",
};


export function Skeleton({ width = "100%", height = 16, className, style }) {
  return (
    <span
      className={className}
      aria-hidden="true"
      style={{ ...BASE_STYLE, width, height, ...style }}
    />
  );
}


export function SkeletonRow({ columns = 4, height = 32, gap = 12 }) {
  const cols = Array.from({ length: columns });
  return (
    <div
      style={{
        display: "flex", gap, alignItems: "center",
        height, marginBottom: 8,
      }}
      aria-hidden="true"
    >
      {cols.map((_, i) => (
        <Skeleton
          key={i}
          width={i === 0 ? "24%" : `${Math.round(76 / (columns - 1))}%`}
          height={height * 0.6}
        />
      ))}
    </div>
  );
}


export function SkeletonCard({ lines = 3, titleHeight = 20 }) {
  return (
    <div
      aria-hidden="true"
      style={{
        padding: "var(--space-md, 16px)",
        border: "1px solid rgba(255,255,255,0.06)",
        borderRadius: "var(--radius-md, 8px)",
      }}
    >
      <Skeleton width="55%" height={titleHeight} />
      <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
        {Array.from({ length: lines }).map((_, i) => (
          <Skeleton
            key={i}
            width={i === lines - 1 ? "70%" : "95%"}
            height={14}
          />
        ))}
      </div>
    </div>
  );
}

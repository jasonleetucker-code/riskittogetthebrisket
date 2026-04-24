/**
 * TierDivider — visible horizontal break between positional tiers
 * on rankings tables.
 *
 * Consumers walk their sorted rows, track the previous row's
 * (position, tierId), and inject a <TierDivider> when the pair
 * changes to `(samePos, prevTierId+1)`.  When backend hasn't
 * stamped tierId, the caller never renders this — safe.
 */
"use client";

import React from "react";


export default function TierDivider({ position, tierId }) {
  return (
    <div
      role="separator"
      aria-label={`${position} Tier ${tierId}`}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--space-sm, 8px)",
        padding: "6px 12px",
        fontSize: "0.7rem",
        fontWeight: 600,
        color: "var(--muted)",
        textTransform: "uppercase",
        letterSpacing: "0.05em",
        borderTop: "1px dashed rgba(255,255,255,0.08)",
        background: "rgba(255,255,255,0.02)",
      }}
    >
      <span>{position} Tier {tierId}</span>
      <span style={{ flex: 1, height: 1, background: "rgba(255,255,255,0.05)" }} />
    </div>
  );
}


/**
 * Helper: given an array of rows in final sort order, returns an
 * array of "segments" where segments break on (position, tierId)
 * change.  Rankings page walks this to decide where to inject
 * dividers.
 */
export function segmentRowsByTier(rows) {
  if (!Array.isArray(rows)) return [];
  const out = [];
  let currentSegment = null;
  for (const row of rows) {
    const pos = String(row?.pos || row?.position || "");
    const tierId = row?.tierId;
    if (tierId == null || !pos) {
      // No tier stamp — flush current + accumulate as "untiered"
      if (currentSegment) out.push(currentSegment);
      currentSegment = { position: pos, tierId: null, rows: [row] };
      continue;
    }
    if (
      !currentSegment ||
      currentSegment.position !== pos ||
      currentSegment.tierId !== tierId
    ) {
      if (currentSegment) out.push(currentSegment);
      currentSegment = { position: pos, tierId, rows: [row] };
    } else {
      currentSegment.rows.push(row);
    }
  }
  if (currentSegment) out.push(currentSegment);
  return out;
}

/**
 * ValueBandBadge — renders a player's source-consensus value range
 * (p10–p90) as an inline badge.  When the backend hasn't stamped
 * a `valueBand` (flag off), renders nothing — safe to drop into
 * any row.
 *
 * Label hint "source_consensus_range" is also surfaced in the
 * aria-label so screen readers don't read the range as a
 * prediction interval.
 */
"use client";

import React from "react";


export default function ValueBandBadge({ player, showMethod = false, compact = false }) {
  const band = player?.valueBand;
  if (!band || typeof band !== "object") return null;
  const { p10, p50, p90, method } = band;
  if (typeof p50 !== "number") return null;
  const spread = Math.round((p90 || 0) - (p10 || 0));
  if (spread <= 0) return null;

  const pctRange = p50 > 0 ? Math.round((spread / p50) * 100) : 0;

  if (compact) {
    return (
      <span
        className="text-xs muted"
        aria-label={`Source consensus range: ${Math.round(p10)} to ${Math.round(p90)}`}
        title={`p10 ${Math.round(p10)} · p50 ${Math.round(p50)} · p90 ${Math.round(p90)} (source consensus range — NOT a forecast)`}
        style={{ marginLeft: 6 }}
      >
        ±{pctRange}%
      </span>
    );
  }

  return (
    <span
      className="badge badge-muted"
      aria-label={`Source consensus range: ${Math.round(p10)} to ${Math.round(p90)}`}
      title={"Source consensus range — NOT a prediction interval. " +
             "Shows how much the 6+ ranking sources agree."}
      style={{
        fontSize: "0.7rem",
        padding: "2px 6px",
        display: "inline-flex",
        alignItems: "baseline",
        gap: 3,
      }}
    >
      <span style={{ color: "var(--muted)" }}>consensus</span>
      <strong>{Math.round(p10)}–{Math.round(p90)}</strong>
      {showMethod && method && (
        <span style={{ color: "var(--subtext)", fontSize: "0.65rem" }}>
          ({method})
        </span>
      )}
    </span>
  );
}

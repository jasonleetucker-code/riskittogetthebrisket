"use client";

import { useMemo } from "react";
import { useTeam } from "@/components/useTeam";
import { useTerminal } from "@/components/useTerminal";

/**
 * StaleBanner — informational banner shown above the terminal grid
 * when the /api/terminal endpoint is serving a cached on-disk
 * contract because the live scrape hasn't primed ``latest_contract_data``
 * yet (e.g. cold start between process restart and first scrape).
 *
 * Payload shape (from ``server.py::get_terminal``):
 *   - ``stale: true``
 *   - ``staleAs: "YYYY-MM-DD"`` — the date stamp on the cached file
 *
 * When stale is false (the common case), renders null — no layout
 * shift, no visual clutter.  When stale is true, the banner shows
 * the data date and approximate age so users know not to read a
 * numerical drift against the current scrape as meaningful.
 */
export default function StaleBanner() {
  const { selectedTeam } = useTeam();
  const { stale, staleAs, loading, error } = useTerminal({
    ownerId: String(selectedTeam?.ownerId || ""),
    teamName: selectedTeam?.name || "",
    windowDays: 30,
  });

  const ageLabel = useMemo(() => {
    if (!staleAs) return null;
    const t = Date.parse(staleAs);
    if (!Number.isFinite(t)) return null;
    const hours = Math.max(0, (Date.now() - t) / (1000 * 60 * 60));
    if (hours < 1) return "less than an hour ago";
    if (hours < 24) return `${Math.round(hours)} hour${Math.round(hours) === 1 ? "" : "s"} ago`;
    const days = Math.floor(hours / 24);
    return `${days} day${days === 1 ? "" : "s"} ago`;
  }, [staleAs]);

  if (loading) return null;
  // Show a different banner when the endpoint errored altogether —
  // gives a single surface for "something is off" instead of
  // splitting between stale-state and error-state UIs.
  if (error) {
    return (
      <div
        className="stale-banner stale-banner--error"
        role="status"
        aria-live="polite"
      >
        <span className="stale-banner-tag">Offline</span>
        <span className="stale-banner-text">
          Terminal data unavailable — retrying in the background.
        </span>
      </div>
    );
  }
  if (!stale) return null;

  return (
    <div className="stale-banner" role="status" aria-live="polite">
      <span className="stale-banner-tag">Cached</span>
      <span className="stale-banner-text">
        Data from {staleAs}
        {ageLabel ? <> · {ageLabel}</> : null} — live scrape still
        warming up.
      </span>
    </div>
  );
}

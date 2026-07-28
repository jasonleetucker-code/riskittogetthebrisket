"use client";

import { useMemo } from "react";
import { useTeam } from "@/components/useTeam";
import { useTerminal } from "@/components/useTerminal";
import { Banner } from "@/components/ds";

/**
 * StaleBanner — the dashboard's "something is off" surface (R3).
 *
 * Two states, one component, both on the ds Banner (which owns the
 * role=status / role=alert live-region wiring):
 *
 *   • error — the /api/terminal endpoint failed outright.
 *   • stale — the endpoint is serving a cached on-disk contract
 *     because the live scrape hasn't primed ``latest_contract_data``
 *     yet (cold start between process restart and first scrape).
 *     Payload: ``stale: true`` + ``staleAs: "YYYY-MM-DD"``.
 *
 * The common case renders null: no layout shift, no clutter. When
 * stale, the banner names the data date and its age so nobody reads
 * numerical drift against the current scrape as meaningful.
 */
export default function StaleBanner() {
  const { selectedTeam, loading: teamLoading } = useTeam();
  const { stale, staleAs, loading, error } = useTerminal({
    // Hold the fetch until team identity resolves from the contract
    // (prevents the discarded ownerId:"" duplicate call).
    skip: teamLoading,
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
    if (hours < 24) {
      const h = Math.round(hours);
      return `${h} hour${h === 1 ? "" : "s"} ago`;
    }
    const days = Math.floor(hours / 24);
    return `${days} day${days === 1 ? "" : "s"} ago`;
  }, [staleAs]);

  if (loading) return null;

  if (error) {
    return (
      <Banner tone="warning" title="Terminal data unavailable">
        The dashboard endpoint isn&apos;t responding — retrying in the background.
      </Banner>
    );
  }

  if (!stale) return null;

  return (
    <Banner tone="info" title="Showing cached data">
      Data from {staleAs}
      {ageLabel ? ` · ${ageLabel}` : ""} — the live scrape is still warming up.
    </Banner>
  );
}

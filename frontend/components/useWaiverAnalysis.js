"use client";

import { useMemo } from "react";
import { useApp } from "@/components/AppShell";
import { useLeague } from "@/components/useLeague";
import { useTeam } from "@/components/useTeam";
import { computeWaiverAnalysis } from "@/lib/waiver-logic";

/**
 * useWaiverAnalysis — wraps the pure ``computeWaiverAnalysis`` helper
 * with the app's data plumbing (rows + sleeper teams + selected
 * league/team).  Returns a stable, memoized analysis object so the
 * page re-renders only when the underlying inputs (or filters) shift.
 *
 * Design notes:
 *
 *   • We pull ``rows`` from ``useApp`` (the AppShell context) rather
 *     than calling ``useDynastyData`` again — AppShell hydrates that
 *     hook once for every page and exposes the result through
 *     context, so reusing it avoids a redundant fetch.
 *
 *   • ``leagueMismatch`` short-circuits with ``analysis: null`` so the
 *     page can render the "data not ready" banner without crashing
 *     on a missing ``selectedTeam``.
 *
 *   • Memoization keys: ``rows`` reference (changes only on
 *     useDynastyData refetch), ``rawData?.sleeper?.teams`` reference,
 *     ``selectedTeam?.players`` reference, plus the four scalar
 *     toggles.  Avoids the O(N²) recompute on every keystroke.
 */
export function useWaiverAnalysis({
  includeRookies = false,
  filters = {},
} = {}) {
  const { rows, rawData, loading, error } = useApp();
  const { selectedLeague } = useLeague();
  const { selectedTeam, leagueMismatch, availableTeams } = useTeam();

  const sleeperTeams = rawData?.sleeper?.teams;
  const myRosterNames = selectedTeam?.players;
  const idpEnabled = Boolean(selectedLeague?.idpEnabled);

  // Stabilize the filters object so a new object literal every render
  // doesn't cascade into an unnecessary recompute.  The page passes
  // primitive scalars; we destructure them here.
  const position = filters?.position || "ALL";
  const minGain = Number(filters?.minGain) || 0;
  const upgradeStrength = filters?.upgradeStrength || "all";

  const stableFilters = useMemo(
    () => ({ position, minGain, upgradeStrength }),
    [position, minGain, upgradeStrength],
  );

  const analysis = useMemo(() => {
    if (leagueMismatch) return null;
    if (!selectedTeam) return null;
    if (!Array.isArray(rows) || rows.length === 0) return null;
    return computeWaiverAnalysis({
      rows,
      myRosterNames,
      sleeperTeams,
      includeRookies,
      idpEnabled,
      filters: stableFilters,
    });
  }, [
    rows,
    myRosterNames,
    sleeperTeams,
    includeRookies,
    idpEnabled,
    stableFilters,
    leagueMismatch,
    selectedTeam,
  ]);

  return {
    analysis,
    loading,
    error,
    leagueMismatch,
    hasTeam: Boolean(selectedTeam),
    teamCount: availableTeams?.length || 0,
    selectedLeagueName: selectedLeague?.displayName || "",
  };
}

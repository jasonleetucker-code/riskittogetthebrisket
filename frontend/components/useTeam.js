"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import { useApp } from "@/components/AppShell";
import { useSettings } from "@/components/useSettings";

// Default team to auto-select on first load when no persisted choice
// exists and this team is present in the league's Sleeper roster set.
// Matched case-insensitively against ``sleeper.teams[].name``.
export const DEFAULT_TEAM_NAME = "Rossini Panini";

function normalize(s) {
  return String(s || "").trim().toLowerCase();
}

/**
 * useTeam — single source of truth for "which Sleeper team is the
 * signed-in user operating as?"
 *
 * Composes:
 *   - sleeper.teams[] from the live canonical contract (via AppShell's
 *     useApp context, so private/public gating is respected)
 *   - settings.selectedTeam from useSettings (localStorage-backed,
 *     synced across tabs via useSyncExternalStore)
 *
 * Reactivity: any consumer re-renders when either the underlying
 * contract changes OR the persisted selection changes.  Switching
 * teams writes to settings which notifies every useSettings subscriber
 * in the app.
 *
 * First-load behavior: if nothing is persisted and the league contains
 * a team whose name matches DEFAULT_TEAM_NAME, auto-select it and
 * persist.  If a persisted selection does not resolve to any current
 * league team, we do NOT silently overwrite it — ``needsSelection``
 * flips true and the UI can prompt the user.
 */
export function useTeam() {
  const { rawData, privateDataEnabled, loading: dataLoading } = useApp();
  const { settings, update } = useSettings();
  const selectedName = settings?.selectedTeam || "";
  const autoAssignedRef = useRef(false);

  const availableTeams = useMemo(() => {
    if (!privateDataEnabled) return [];
    const teams = rawData?.sleeper?.teams;
    return Array.isArray(teams) ? teams : [];
  }, [rawData, privateDataEnabled]);

  const selectedTeam = useMemo(() => {
    if (!selectedName || availableTeams.length === 0) return null;
    const needle = normalize(selectedName);
    return availableTeams.find((t) => normalize(t?.name) === needle) || null;
  }, [availableTeams, selectedName]);

  // Auto-assign default team when (a) nothing is persisted yet and
  // (b) the default exists in this league.  Skipped if the user has
  // any persisted name (even if currently unresolvable) so a transient
  // rename / data glitch doesn't clobber their choice.
  useEffect(() => {
    if (autoAssignedRef.current) return;
    if (dataLoading) return;
    if (!privateDataEnabled) return;
    if (selectedName) return;
    if (availableTeams.length === 0) return;

    const match = availableTeams.find(
      (t) => normalize(t?.name) === normalize(DEFAULT_TEAM_NAME),
    );
    if (match?.name) {
      autoAssignedRef.current = true;
      update("selectedTeam", match.name);
    }
  }, [availableTeams, selectedName, privateDataEnabled, dataLoading, update]);

  const setSelectedTeam = useCallback(
    (name) => update("selectedTeam", name || ""),
    [update],
  );

  const clearSelectedTeam = useCallback(() => update("selectedTeam", ""), [update]);

  const needsSelection =
    privateDataEnabled && !dataLoading && availableTeams.length > 0 && !selectedTeam;

  return {
    availableTeams,
    selectedTeam,
    selectedName,
    setSelectedTeam,
    clearSelectedTeam,
    needsSelection,
    loading: dataLoading,
    privateDataEnabled,
  };
}

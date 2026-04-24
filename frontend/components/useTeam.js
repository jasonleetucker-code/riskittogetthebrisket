"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import { useApp } from "@/components/AppShell";
import { useSettings } from "@/components/useSettings";
import { useLeague } from "@/components/useLeague";

// Fallback team name for the ORIGINAL league only (back-compat for
// Jason's pre-multi-league state).  New leagues don't have a
// hardcoded default — they rely on the registry's ``defaultTeamMap``
// which ``/api/leagues`` exposes per user via ``userDefaultTeam``.
export const DEFAULT_TEAM_NAME = "Rossini Panini";

function normalize(s) {
  return String(s || "").trim().toLowerCase();
}

/**
 * useTeam — single source of truth for "which Sleeper team is the
 * signed-in user operating as on the ACTIVE league?"
 *
 * Multi-league design
 * ───────────────────
 * Before multi-league, ``settings.selectedTeam`` was a single string
 * and ``availableTeams`` came from ``rawData.sleeper.teams``.  That
 * broke once a user could own a team in multiple leagues: picking
 * "my team" in League A would silently clobber "my team" in League
 * B (or worse, auto-match a same-named team across leagues).
 *
 * New shape:
 *   * ``useLeague`` decides which league is active.
 *   * ``settings.selectedTeamsByLeague[leagueKey]`` stores the team
 *     per league.  ``useTeam`` reads from that slot and writes to
 *     that slot.
 *   * For the REGISTRY DEFAULT league, the legacy
 *     ``settings.selectedTeam`` is mirrored (on write) + consulted
 *     (on read) as a fallback so pre-migration users don't flip
 *     empty on first load.
 *   * Auto-select honors the league's ``userDefaultTeam`` from
 *     ``/api/leagues`` (per-user slice of the registry's
 *     ``defaultTeamMap``).  When the server doesn't name a default,
 *     the historical ``DEFAULT_TEAM_NAME`` hardcoded fallback runs
 *     only for the registry default league — new leagues require
 *     an explicit user choice.
 *
 * ``availableTeams`` is sourced from ``rawData.sleeper.teams``.
 * That block is currently stamped with one league's teams at a time
 * (the scrape is single-league until Phase 2).  When the
 * ``meta.leagueKey`` on the contract doesn't match the active
 * league, ``availableTeams`` returns ``[]`` — the UI should show a
 * "data not ready" state for that league, not another league's
 * teams dressed up with a wrong name.
 */
export function useTeam() {
  const { rawData, privateDataEnabled, loading: dataLoading } = useApp();
  const { settings, update } = useSettings();
  const { selectedLeague, selectedLeagueKey, defaultLeagueKey } = useLeague();
  const autoAssignedRef = useRef(new Set());

  // ── Sleeper-data-for-this-league guard ─────────────────────────
  // The contract's ``meta.sleeperDataReady`` tells us whether the
  // ``sleeper`` block in the response is real for the requested
  // league.  When the user switches to a league whose rosters
  // haven't been scraped yet, the server returns shared rankings
  // with ``sleeper: null`` and ``sleeperDataReady: false``.  We
  // surface that as ``leagueMismatch: true`` so team-dependent UI
  // (pickers, rosters, terminal) renders the data-not-ready state
  // rather than the wrong league's teams.
  //
  // Back-compat: older contracts (pre-scoringProfile refactor) lack
  // the flag.  Treat an absent flag as "ready" and fall back to
  // the old leagueKey-mismatch check so pre-multi-league clients
  // still work.
  const contractLeagueKey = useMemo(
    () => rawData?.meta?.leagueKey || rawData?.leagueKey || "",
    [rawData],
  );
  const sleeperDataReady = useMemo(() => {
    const flag = rawData?.meta?.sleeperDataReady;
    if (flag === false) return false;
    if (flag === true) return true;
    // Legacy path: if the flag is absent, infer from leagueKey match.
    if (contractLeagueKey && selectedLeagueKey) {
      return contractLeagueKey === selectedLeagueKey;
    }
    return true;
  }, [rawData, contractLeagueKey, selectedLeagueKey]);

  const leagueMismatch = !sleeperDataReady && Boolean(selectedLeagueKey);

  const availableTeams = useMemo(() => {
    if (!privateDataEnabled) return [];
    if (leagueMismatch) return [];
    const teams = rawData?.sleeper?.teams;
    return Array.isArray(teams) ? teams : [];
  }, [rawData, privateDataEnabled, leagueMismatch]);

  // ── Resolve the stored selection for the active league ─────────
  const storedEntry = useMemo(() => {
    const byLeague = settings?.selectedTeamsByLeague || {};
    const fromMap = selectedLeagueKey ? byLeague[selectedLeagueKey] : null;
    if (fromMap && (fromMap.teamName || fromMap.ownerId)) return fromMap;
    // Legacy fallback: only the default league reads ``selectedTeam``
    // — non-default leagues have nothing to fall back to.
    if (selectedLeagueKey && selectedLeagueKey === defaultLeagueKey) {
      const legacyName = settings?.selectedTeam || "";
      if (legacyName) return { ownerId: "", teamName: legacyName };
    }
    return null;
  }, [settings, selectedLeagueKey, defaultLeagueKey]);

  const storedName = storedEntry?.teamName || "";
  const storedOwnerId = storedEntry?.ownerId || "";

  const touchedMap = settings?.selectedTeamTouchedByLeague || {};
  const selectionTouched = Boolean(
    (selectedLeagueKey && touchedMap[selectedLeagueKey] === true) ||
    // Pre-migration users might only have the legacy touched flag set.
    // For the default league, treat the legacy flag as the touched
    // signal; for other leagues it's meaningless.
    (selectedLeagueKey === defaultLeagueKey &&
      (settings?.selectedTeamTouched === true || !!storedName)),
  );

  const selectedTeam = useMemo(() => {
    if (!storedName && !storedOwnerId) return null;
    if (availableTeams.length === 0) return null;
    // Prefer owner-ID match so a Sleeper team rename doesn't orphan
    // the selection; fall back to case-insensitive name match.
    if (storedOwnerId) {
      const byOwner = availableTeams.find(
        (t) => String(t?.ownerId || "") === storedOwnerId,
      );
      if (byOwner) return byOwner;
    }
    if (storedName) {
      const needle = normalize(storedName);
      return availableTeams.find((t) => normalize(t?.name) === needle) || null;
    }
    return null;
  }, [availableTeams, storedName, storedOwnerId]);

  // ── Writers ─────────────────────────────────────────────────────
  // Accept a team dict OR a name string.  The dict form carries
  // ownerId + rosterId + managerName so future multi-device syncs
  // can rename-tolerance via ownerId.  Callers that only have a
  // name (TeamSwitcher, /rosters dropdown) pass a string.
  const setSelectedTeam = useCallback(
    (teamOrName) => {
      if (!selectedLeagueKey) return;
      let entry;
      if (!teamOrName) {
        entry = { ownerId: "", teamName: "" };
      } else if (typeof teamOrName === "string") {
        // Look up the full team in availableTeams so we can stash
        // ownerId + rosterId + managerName alongside the name.
        const match = availableTeams.find(
          (t) => normalize(t?.name) === normalize(teamOrName),
        );
        entry = {
          ownerId: match?.ownerId || "",
          teamName: match?.name || String(teamOrName).trim(),
          rosterId: match?.roster_id ? String(match.roster_id) : undefined,
          managerName: match?.manager || undefined,
        };
      } else {
        entry = {
          ownerId: String(teamOrName.ownerId || "").trim(),
          teamName: String(teamOrName.teamName || teamOrName.name || "").trim(),
          rosterId: teamOrName.rosterId || (teamOrName.roster_id && String(teamOrName.roster_id)) || undefined,
          managerName: teamOrName.managerName || teamOrName.manager || undefined,
        };
      }
      // Drop undefined fields so localStorage doesn't grow a cruft
      // suffix over time.
      for (const k of Object.keys(entry)) {
        if (entry[k] === undefined) delete entry[k];
      }

      const nextByLeague = {
        ...(settings?.selectedTeamsByLeague || {}),
        [selectedLeagueKey]: entry,
      };
      const nextTouched = {
        ...(settings?.selectedTeamTouchedByLeague || {}),
        [selectedLeagueKey]: true,
      };

      update("selectedTeamsByLeague", nextByLeague);
      update("selectedTeamTouchedByLeague", nextTouched);

      // Back-compat mirror: for the default league also write the
      // legacy top-level field so pre-migration builds loaded in
      // another tab still see the right team name.
      if (selectedLeagueKey === defaultLeagueKey) {
        update("selectedTeam", entry.teamName);
        // update() already sets selectedTeamTouched for selectedTeam writes.
      }
    },
    [selectedLeagueKey, defaultLeagueKey, availableTeams, settings, update],
  );

  const clearSelectedTeam = useCallback(() => setSelectedTeam(""), [setSelectedTeam]);

  // ── Auto-assign on fresh devices ────────────────────────────────
  // Once per (leagueKey, mount) — only if the user hasn't explicitly
  // set a team on this league on this device.
  useEffect(() => {
    if (!selectedLeagueKey) return;
    if (autoAssignedRef.current.has(selectedLeagueKey)) return;
    if (dataLoading) return;
    if (!privateDataEnabled) return;
    if (leagueMismatch) return;
    if (selectionTouched) return;
    if (availableTeams.length === 0) return;

    // 1. Server-resolved default from the registry's defaultTeamMap
    //    (shipped per-league on /api/leagues as ``userDefaultTeam``).
    const serverDefault = selectedLeague?.userDefaultTeam;
    let match = null;
    if (serverDefault?.ownerId) {
      match = availableTeams.find(
        (t) => String(t?.ownerId || "") === String(serverDefault.ownerId),
      ) || null;
    }
    if (!match && serverDefault?.teamName) {
      const needle = normalize(serverDefault.teamName);
      match = availableTeams.find((t) => normalize(t?.name) === needle) || null;
    }

    // 2. Historical "Rossini Panini" fallback — only for the default
    //    league.  New leagues don't inherit Jason's team.
    if (!match && selectedLeagueKey === defaultLeagueKey) {
      match = availableTeams.find(
        (t) => normalize(t?.name) === normalize(DEFAULT_TEAM_NAME),
      ) || null;
    }

    if (match?.name) {
      autoAssignedRef.current.add(selectedLeagueKey);
      setSelectedTeam(match);
    }
  }, [
    selectedLeagueKey,
    defaultLeagueKey,
    selectionTouched,
    privateDataEnabled,
    dataLoading,
    leagueMismatch,
    availableTeams,
    selectedLeague,
    setSelectedTeam,
  ]);

  const needsSelection =
    privateDataEnabled &&
    !dataLoading &&
    !leagueMismatch &&
    availableTeams.length > 0 &&
    !selectedTeam;

  return {
    availableTeams,
    selectedTeam,
    selectedName: selectedTeam?.name || storedName || "",
    selectedOwnerId: selectedTeam?.ownerId || storedOwnerId || "",
    selectedLeagueKey,
    leagueMismatch,
    setSelectedTeam,
    clearSelectedTeam,
    needsSelection,
    loading: dataLoading,
    privateDataEnabled,
    idpEnabled: selectedLeague?.idpEnabled !== false,
    rosterSettings: selectedLeague?.rosterSettings || {},
  };
}

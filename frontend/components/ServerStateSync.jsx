"use client";

import { useEffect, useRef } from "react";
import { useSettings } from "@/components/useSettings";
import { useUserState } from "@/components/useUserState";

/**
 * ServerStateSync — mount once inside AppShell.
 *
 * Bi-directional bridge between the localStorage-backed
 * ``useSettings.selectedTeam`` and the SQLite-backed
 * ``useUserState.selectedTeam``.  Keeps the two in sync without
 * modifying ``useTeam``'s existing localStorage-only read/write
 * pattern — the UI continues to work exactly as it did before, but
 * selectedTeam now follows the user across devices via the server
 * store.
 *
 * Sync semantics (authenticated users only — anonymous requests
 * 401, which ``useUserState`` handles silently by falling back to
 * localStorage-only mode):
 *
 *   - On first mount, once both stores have loaded:
 *       * Server has a selection + local is empty       → push server → local
 *       * Local has a selection + server is empty       → push local → server
 *       * Both have a selection and they disagree       → server wins
 *         (server is the cross-device source of truth)
 *
 *   - On every subsequent local change, mirror to the server.
 *   - Server pushes (e.g. user logs in on another device) arrive via
 *     the 30s useUserState cache TTL — not instant but good enough
 *     for dynasty use cases.
 *
 * Renders nothing.
 */
export default function ServerStateSync() {
  const { settings, update } = useSettings();
  const {
    state: userState,
    loading: userStateLoading,
    serverBacked,
    setSelectedTeam: setSelectedTeamServer,
  } = useUserState();

  const initialSyncDone = useRef(false);
  const lastLocalName = useRef(null);

  // One-shot hydrate: decide the winner of a first-boot conflict
  // between the two stores, then mark that initial sync as done so
  // subsequent effects treat local changes as authoritative (the
  // user is actively picking something).
  useEffect(() => {
    if (initialSyncDone.current) return;
    if (userStateLoading) return;
    if (!serverBacked) {
      // Anonymous / server unreachable — nothing to sync.  Still
      // mark the initial pass done so the local→server mirror
      // effect doesn't fire for the first render churn.
      initialSyncDone.current = true;
      lastLocalName.current = settings?.selectedTeam || "";
      return;
    }
    const serverTeam = userState?.selectedTeam || {};
    const serverName = serverTeam.name || "";
    const localName = settings?.selectedTeam || "";

    if (serverName && serverName !== localName) {
      // Server wins — push server → local.  Keeps the first render
      // showing whatever the user picked on their other device.
      update("selectedTeam", serverName);
    } else if (!serverName && localName) {
      // Local-only selection — probably from before the user_kv
      // layer shipped.  Push up to the server so other devices see
      // it next login.
      setSelectedTeamServer("", localName);
    }
    initialSyncDone.current = true;
    lastLocalName.current = settings?.selectedTeam || "";
  }, [userStateLoading, serverBacked, userState, settings, update, setSelectedTeamServer]);

  // Ongoing mirror: any local change after the initial sync
  // propagates to the server.  Debounce is implicit via React's
  // useEffect batching; useUserState's server-write is fire-and-
  // forget so there's no blocking roundtrip.
  useEffect(() => {
    if (!initialSyncDone.current) return;
    if (!serverBacked) return;
    const currentLocal = settings?.selectedTeam || "";
    if (currentLocal === lastLocalName.current) return;
    lastLocalName.current = currentLocal;
    // We don't know the ownerId here (useSettings is name-only) —
    // leave it empty.  The terminal endpoint resolves either by
    // ownerId OR by name, so the server record still works.  When
    // TeamSwitcher is rewired to call ``useUserState.setSelectedTeam``
    // directly it can pass the ownerId; this effect is the fallback.
    setSelectedTeamServer("", currentLocal);
  }, [settings?.selectedTeam, serverBacked, setSelectedTeamServer]);

  return null;
}

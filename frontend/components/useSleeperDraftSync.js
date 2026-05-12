"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// Polling cadences (ms).  Visible-tab cadence is the user-facing
// latency target; hidden-tab cadence is courteous to Sleeper while
// still catching up when the user returns.  Error backoff stretches
// the interval so a Sleeper outage doesn't generate a retry storm.
const POLL_INTERVAL_ACTIVE_MS = 2500;
const POLL_INTERVAL_HIDDEN_MS = 10000;
const POLL_INTERVAL_ERROR_MS = 8000;

// Treat "no new pick in this long" as a stale connection — the UI
// flips the indicator to amber.  Set generously (auctions can have
// long lulls between nominations).
const STALE_AFTER_MS = 20000;

/**
 * Live Sleeper auction-draft polling hook.
 *
 * Polls ``/api/sleeper/draft/picks`` while ``enabled`` is true,
 * invoking ``onPickArrived(pick)`` for every new pick (in
 * ``pickNo`` order).  Tracks a cursor in a ref so a remount or a
 * brief network blip doesn't replay picks.
 *
 * @param {object} args
 * @param {string} args.leagueKey   — active league key (passed to backend)
 * @param {boolean} args.enabled    — master switch (toggle on the page)
 * @param {(pick: object) => void} args.onPickArrived — called per new pick
 * @returns {{
 *   status: "idle" | "connected" | "stale" | "error" | "complete",
 *   draftId: string | null,
 *   lastPickNo: number,
 *   latestPickNo: number,
 *   lastSyncAt: number | null,
 *   error: string | null,
 * }}
 */
export function useSleeperDraftSync({ leagueKey, enabled, onPickArrived }) {
  const [state, setState] = useState({
    status: "idle",
    draftId: null,
    lastPickNo: 0,
    latestPickNo: 0,
    lastSyncAt: null,
    error: null,
  });

  // Hold the cursor + a few callbacks in refs so the polling effect's
  // identity doesn't change on every re-render (which would trip its
  // own setInterval and restart the timer).
  const cursorRef = useRef(0);
  const onPickArrivedRef = useRef(onPickArrived);
  useEffect(() => {
    onPickArrivedRef.current = onPickArrived;
  }, [onPickArrived]);

  // Reset the cursor whenever the active league changes — picks are
  // per-league, so a switch should start from pick 0 of the new
  // league's draft.
  useEffect(() => {
    cursorRef.current = 0;
    setState((s) => ({
      ...s,
      status: enabled ? "idle" : "idle",
      lastPickNo: 0,
      latestPickNo: 0,
      draftId: null,
      error: null,
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leagueKey]);

  useEffect(() => {
    if (!enabled) {
      setState((s) => ({ ...s, status: "idle", error: null }));
      return undefined;
    }

    let cancelled = false;
    let timer = null;
    let consecutiveErrors = 0;

    const tick = async () => {
      if (cancelled) return;
      const ctl = new AbortController();
      try {
        const url = new URL("/api/sleeper/draft/picks", window.location.origin);
        if (leagueKey) url.searchParams.set("leagueKey", leagueKey);
        url.searchParams.set("afterPickNo", String(cursorRef.current));
        const res = await fetch(url.toString(), {
          cache: "no-store",
          signal: ctl.signal,
        });
        if (cancelled) return;

        if (res.status === 404) {
          // ``no_active_draft`` — keep polling at the error cadence
          // (the draft might start any minute) but flag the state so
          // the UI dims the indicator.
          consecutiveErrors = 0;
          setState((s) => ({
            ...s,
            status: "error",
            error: "No active draft for this league.",
            lastSyncAt: Date.now(),
          }));
          schedule(POLL_INTERVAL_ERROR_MS);
          return;
        }
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const data = await res.json();
        if (cancelled) return;

        const picks = Array.isArray(data?.picks) ? data.picks : [];
        for (const pick of picks) {
          if (!pick || typeof pick.pickNo !== "number") continue;
          if (pick.pickNo <= cursorRef.current) continue;
          try {
            onPickArrivedRef.current?.(pick);
          } catch {
            /* swallow — never let one bad handler kill the loop */
          }
          cursorRef.current = pick.pickNo;
        }

        const latest = Number(data?.latestPickNo) || cursorRef.current;
        const status = data?.status || "unknown";
        consecutiveErrors = 0;

        setState((s) => {
          // ``complete`` is terminal — auto-stop polling once Sleeper
          // marks the draft done so we don't pound the endpoint
          // forever post-draft.
          const next = {
            ...s,
            draftId: data?.draftId || s.draftId,
            lastPickNo: cursorRef.current,
            latestPickNo: latest,
            lastSyncAt: Date.now(),
            error: null,
          };
          if (status === "complete") {
            next.status = "complete";
          } else if (status === "drafting" || status === "pre_draft") {
            next.status = "connected";
          } else {
            next.status = "connected";
          }
          return next;
        });

        if (status === "complete") {
          // Terminal — don't reschedule.
          return;
        }
        schedule();
      } catch (err) {
        if (cancelled) return;
        if (err?.name === "AbortError") return;
        consecutiveErrors += 1;
        setState((s) => ({
          ...s,
          status: "error",
          error: err?.message || "Live sync error",
        }));
        schedule(POLL_INTERVAL_ERROR_MS);
      }
    };

    const schedule = (overrideMs) => {
      if (cancelled) return;
      const hidden = typeof document !== "undefined" && document.hidden;
      const ms =
        overrideMs ??
        (hidden ? POLL_INTERVAL_HIDDEN_MS : POLL_INTERVAL_ACTIVE_MS);
      timer = setTimeout(tick, ms);
    };

    // Kick off immediately so the first poll lands within a render
    // cycle — the user gets feedback that sync is active.
    tick();

    // When the tab becomes visible again, force a refresh so the
    // user catches up to whatever happened while they were away.
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        if (timer) {
          clearTimeout(timer);
          timer = null;
        }
        tick();
      }
    };
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibility);
    }

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibility);
      }
    };
  }, [enabled, leagueKey]);

  // Derive a "stale" state purely from time-since-last-success so the
  // UI can flag long gaps without an extra effect.  Polled state.
  const derivedStatus = (() => {
    if (state.status === "complete") return "complete";
    if (state.status === "error") return "error";
    if (!state.lastSyncAt) return state.status;
    if (Date.now() - state.lastSyncAt > STALE_AFTER_MS) return "stale";
    return state.status;
  })();

  return { ...state, status: derivedStatus };
}

/**
 * Build a Sleeper-team-id ↔ workspace-team-idx map from the
 * /api/data sleeper block and the workspace's teams array.
 *
 * Workspace teams are merged from /api/draft-capital ``teamTotals``
 * which is itself derived from Sleeper's users + rosters — so the
 * display name is the canonical join key.  We index by both
 * ``ownerId`` (Sleeper user_id) and ``rosterId`` so the live pick's
 * primary key (``picked_by``) and fallback (``roster_id``) both
 * resolve when present.
 *
 * Returns ``{ byOwner: Map<string, number>, byRoster: Map<number, number> }``.
 * Empty maps when sleeperTeams is missing — the caller falls back to
 * surfacing the pick with no team-index so the user can record it
 * manually.
 */
export function buildTeamIndexLookup(workspaceTeams, sleeperTeams) {
  const byOwner = new Map();
  const byRoster = new Map();
  const wsTeams = Array.isArray(workspaceTeams) ? workspaceTeams : [];
  const slTeams = Array.isArray(sleeperTeams) ? sleeperTeams : [];
  if (wsTeams.length === 0 || slTeams.length === 0) {
    return { byOwner, byRoster };
  }

  // Workspace team idx keyed by lowercase name for case-insensitive
  // matching.  Names come from /api/draft-capital teamTotals which
  // are emitted from the same Sleeper users feed, so this is a
  // direct match in practice.
  const wsIdxByName = new Map();
  wsTeams.forEach((t, idx) => {
    const key = String(t?.name || "").toLowerCase().trim();
    if (key) wsIdxByName.set(key, idx);
  });

  for (const t of slTeams) {
    const teamName = String(t?.name || "").toLowerCase().trim();
    if (!teamName) continue;
    const idx = wsIdxByName.get(teamName);
    if (idx == null) continue;
    const ownerId = String(t?.ownerId || "").trim();
    if (ownerId) byOwner.set(ownerId, idx);
    const rosterId = Number(t?.roster_id);
    if (Number.isFinite(rosterId)) byRoster.set(rosterId, idx);
  }
  return { byOwner, byRoster };
}

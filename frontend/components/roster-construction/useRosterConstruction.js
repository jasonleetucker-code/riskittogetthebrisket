"use client";

/**
 * useRosterConstruction — fetch one team's Roster Construction payload.
 *
 * Used only inside the lazy panel chunk.  Any failure is a stated, classified
 * state (`lib/roster-construction.js::classifyRosterConstructionFailure`),
 * never a blank and never a number.  A late answer for another league or team
 * is discarded (stale-response guard).  Display only.
 */
import { useEffect, useState } from "react";
import {
  buildRosterConstructionUrl,
  classifyRosterConstructionFailure,
  isStaleRosterConstructionPayload,
} from "@/lib/roster-construction";

export function useRosterConstruction({ leagueKey, rosterId, season, enabled = true } = {}) {
  const url = buildRosterConstructionUrl({ leagueKey, rosterId, season });
  const identity = JSON.stringify([url, enabled]);
  const [state, setState] = useState({
    identity: null,
    payload: null,
    failure: null,
    loading: false,
  });

  useEffect(() => {
    if (!enabled) {
      setState({ identity, payload: null, failure: null, loading: false });
      return undefined;
    }
    let cancelled = false;
    const ctl = new AbortController();
    // Keep the previous payload mounted while the new one computes (no
    // flash-to-empty); the stale guard below hides it if it is another team's.
    setState((prev) => ({ ...prev, identity, failure: null, loading: true }));
    (async () => {
      try {
        const res = await fetch(JSON.parse(identity)[0], {
          signal: ctl.signal,
          headers: { Accept: "application/json" },
        });
        const json = await res.json().catch(() => null);
        if (cancelled) return;
        if (!res.ok || !json || typeof json !== "object") {
          setState({
            identity,
            payload: null,
            failure: classifyRosterConstructionFailure(res.status, json),
            loading: false,
          });
          return;
        }
        const stale = isStaleRosterConstructionPayload(json, { leagueKey, rosterId });
        setState({ identity, payload: stale ? null : json, failure: null, loading: false });
      } catch (err) {
        if (cancelled || err?.name === "AbortError") return;
        setState({
          identity,
          payload: null,
          failure: { kind: "offline", message: "Couldn't reach Roster Construction." },
          loading: false,
        });
      }
    })();
    return () => {
      cancelled = true;
      ctl.abort();
    };
  }, [enabled, identity, leagueKey, rosterId]);

  const current = state.identity === identity;
  const shown =
    state.payload &&
    !isStaleRosterConstructionPayload(state.payload, { leagueKey, rosterId })
      ? state.payload
      : null;
  return {
    payload: shown,
    failure: current ? state.failure : null,
    loading: Boolean(enabled) && (!current || Boolean(state.loading)),
  };
}

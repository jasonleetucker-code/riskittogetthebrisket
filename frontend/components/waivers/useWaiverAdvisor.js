"use client";

/**
 * useWaiverAdvisor — fetch one team's Waiver Advisor payload.
 *
 * Fetches even with no team selected: that team-less request is the gate
 * probe (the backend answers `feature_disabled` before `team_required`), so
 * the page can stay blank while the flag is off.  Any failure is a stated,
 * classified state (`lib/waiver-advisor.js::classifyAdvisorFailure`), never a
 * blank and never a number.  Display only — no value math.
 */
import { useEffect, useState } from "react";
import {
  WAIVER_ADVISOR_ENDPOINT,
  buildAdvisorRequest,
  classifyAdvisorFailure,
  isStaleAdvisorPayload,
} from "@/lib/waiver-advisor";

export function useWaiverAdvisor({ leagueKey, ownerId, position = "ALL", enabled = true } = {}) {
  const identity = JSON.stringify([leagueKey || "", ownerId || "", position, enabled]);
  const [state, setState] = useState({ identity: null, payload: null, failure: null });

  useEffect(() => {
    if (!enabled) {
      setState({ identity, payload: null, failure: null });
      return undefined;
    }
    let cancelled = false;
    const ctl = new AbortController();
    setState({ identity, payload: null, failure: null, loading: true });
    (async () => {
      try {
        const res = await fetch(WAIVER_ADVISOR_ENDPOINT, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: ctl.signal,
          body: JSON.stringify(buildAdvisorRequest({ leagueKey, ownerId, position })),
        });
        const json = await res.json().catch(() => null);
        if (cancelled) return;
        if (!res.ok || !json || typeof json !== "object") {
          setState({ identity, payload: null, failure: classifyAdvisorFailure(res.status, json) });
          return;
        }
        const stale = isStaleAdvisorPayload(json, { leagueKey, ownerId });
        setState({ identity, payload: stale ? null : json, failure: null });
      } catch (err) {
        if (cancelled || err?.name === "AbortError") return;
        setState({
          identity,
          payload: null,
          failure: { kind: "offline", message: "Couldn't reach the waiver advisor." },
        });
      }
    })();
    return () => {
      cancelled = true;
      ctl.abort();
    };
  }, [enabled, leagueKey, ownerId, position, identity]);

  const current = state.identity === identity;
  return {
    payload: current ? state.payload : null,
    failure: current ? state.failure : null,
    loading: Boolean(enabled) && (!current || Boolean(state.loading)),
  };
}

"use client";

import { useEffect, useState } from "react";

/**
 * useBestAvailableIdp — fetches the "Best Available IDPs" waiver card
 * payload for the given league.
 *
 * Silent-vanish posture, same as the FAAB bid fetch in
 * ``useWaiverAnalysis.js``: any non-OK response, malformed body, abort or
 * network failure leaves ``payload`` null and the card renders nothing —
 * this is an optional decision lens, not a page-blocking dependency.
 *
 * ``payload.candidates`` is the FULL sorted list (not pre-sliced to 20) —
 * the component is responsible for filtering by position and THEN
 * slicing to the requested count, since each candidate's score already
 * reflects its rank across the whole cross-position IDP population.
 */
export function useBestAvailableIdp({ leagueKey, enabled = true } = {}) {
  const identity = JSON.stringify([leagueKey || "", enabled]);
  const [state, setState] = useState({ identity: null, payload: null, loading: false });

  useEffect(() => {
    if (!enabled) {
      setState({ identity, payload: null, loading: false });
      return undefined;
    }
    let cancelled = false;
    const ctl = new AbortController();
    setState((previous) => ({ identity, payload: previous.identity === identity ? previous.payload : null, loading: true }));
    (async () => {
      try {
        const res = await fetch("/api/waiver/best-available-idp", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: ctl.signal,
          body: JSON.stringify({ leagueKey: leagueKey || undefined }),
        });
        if (cancelled) return;
        if (!res.ok) {
          setState({ identity, payload: null, loading: false });
          return;
        }
        const json = await res.json();
        if (cancelled) return;
        const valid = json && typeof json === "object" && !Array.isArray(json) &&
          (!leagueKey || !Object.hasOwn(json, "leagueKey") || json.leagueKey === leagueKey);
        setState({ identity, payload: valid ? json : null, loading: false });
      } catch {
        // Includes AbortError on unmount/league switch.
        if (!cancelled) setState({ identity, payload: null, loading: false });
      }
    })();
    return () => {
      cancelled = true;
      ctl.abort();
    };
  }, [enabled, leagueKey, identity]);

  return {
    payload: enabled && state.identity === identity ? state.payload : null,
    loading: enabled && (state.identity !== identity || state.loading),
  };
}

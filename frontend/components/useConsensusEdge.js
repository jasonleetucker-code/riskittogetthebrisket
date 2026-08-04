"use client";
/**
 * useConsensusEdge — tri-state fetch for /api/consensus-edge/*, with the
 * flag-off and data-not-ready states rendered distinctly from real
 * errors.
 *
 * League threading follows the documented module pattern (see
 * lib/dynasty-data.js: useLeague can't be imported from data modules —
 * import cycle): read the active league key from localStorage at fetch
 * time, and refetch on the `league:changed` / `auth:changed` window
 * events.
 *
 * Shape deliberately mirrors useBdvm.js. A second convention for "call a
 * flag-gated backend endpoint and render its three failure modes" would
 * be a drift risk, not a feature.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { classifyEdgeFailure } from "@/lib/consensus-edge";

const LEAGUE_LOCAL_KEY = "next_active_league_v1";

function activeLeagueKey() {
  try {
    return window.localStorage.getItem(LEAGUE_LOCAL_KEY) || "";
  } catch {
    return "";
  }
}

/**
 * @param {string} path — relative endpoint ("/api/consensus-edge/top")
 * @param {object} opts — { params, enabled }
 * @returns {{ loading, data, failure, refetch }}
 *   failure: null | { kind: "disabled"|"not_ready"|"unavailable"|"auth"|"error", message }
 */
export function useConsensusEdge(path, { params, enabled = true } = {}) {
  const [loading, setLoading] = useState(enabled);
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [nonce, setNonce] = useState(0);

  const paramsKey = useMemo(() => JSON.stringify(params || {}), [params]);
  const settledKeyRef = useRef(null);
  const abortRef = useRef(null);

  const refetch = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    const onChange = () => refetch();
    window.addEventListener("league:changed", onChange);
    window.addEventListener("auth:changed", onChange);
    return () => {
      window.removeEventListener("league:changed", onChange);
      window.removeEventListener("auth:changed", onChange);
    };
  }, [refetch]);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return undefined;
    }
    const league = activeLeagueKey();
    const key = `${path}|${paramsKey}|${league}|${nonce}`;
    // A kept-mounted tab re-enabling must not refetch what it already has.
    if (settledKeyRef.current === key) return undefined;

    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    let cancelled = false;
    setLoading(true);

    (async () => {
      try {
        const search = new URLSearchParams();
        for (const [k, v] of Object.entries(params || {})) {
          if (v !== undefined && v !== null && v !== "")
            search.set(k, String(v));
        }
        // Deliberately NOT sent. The backend has never read it, and a
        // parameter that is accepted and ignored reads as "this answer
        // is league-specific" — see consensus_edge/scoring_fit.py. The
        // league still participates in `key` below, so switching
        // leagues refetches; what it does not do is claim to change the
        // answer.
        const qs = search.toString();
        const response = await fetch(`${path}${qs ? `?${qs}` : ""}`, {
          cache: "no-store",
          signal: controller.signal,
        });
        let body = null;
        try {
          body = await response.json();
        } catch {
          body = null;
        }
        if (cancelled) return;
        const classified = classifyEdgeFailure(response.status, body);
        setFailure(classified);
        setData(classified ? null : body);
        settledKeyRef.current = key;
      } catch (err) {
        if (cancelled || err?.name === "AbortError") return;
        setFailure({
          kind: "error",
          message: err?.message || "Request failed",
        });
        setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [path, paramsKey, params, enabled, nonce]);

  return { loading, data, failure, refetch };
}

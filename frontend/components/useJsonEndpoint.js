"use client";

/**
 * useJsonEndpoint — tri-state fetch for a league-scoped private JSON
 * endpoint, with each distinct backend refusal surfaced as its own state
 * rather than as one generic error.
 *
 * Extracted verbatim from `useBdvmEndpoint`, which is now a two-line
 * wrapper over it. The only thing that was ever BDVM-specific is the
 * classifier, so that is the parameter: a second copy of this fetch
 * machinery per surface is how the two would drift on league threading,
 * abort handling or the settled-key rule.
 *
 * League threading follows the documented module pattern (see
 * lib/dynasty-data.js: useLeague can't be imported from data modules —
 * import cycle): read the active league key from localStorage at fetch
 * time, and refetch on the `league:changed` / `auth:changed` window
 * events that useLeague/login dispatch.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const LEAGUE_LOCAL_KEY = "next_active_league_v1";

function readActiveLeagueKey() {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem(LEAGUE_LOCAL_KEY) || "";
  } catch {
    return "";
  }
}

/**
 * @param {string} path — relative endpoint ("/api/roster/intelligence")
 * @param {object} opts
 *   @param {object} [opts.params]   plain object of query params; empty
 *                                   values are omitted, not sent blank
 *   @param {boolean} [opts.enabled] fetch only when true (lazy tabs)
 *   @param {Function} opts.classify REQUIRED. (status, body) => null for
 *                                   2xx, else {kind, message}. Keep it a
 *                                   module-level function: it is an
 *                                   effect dependency, so an inline
 *                                   arrow would refetch every render.
 * @returns {{ loading, data, failure, refetch }}
 */
export function useJsonEndpoint(path, { params, enabled = true, classify } = {}) {
  const [loading, setLoading] = useState(Boolean(enabled));
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const abortRef = useRef(null);
  // Last (path|params|refreshKey) combination that SETTLED (data or
  // failure). Re-enabling a kept-mounted tab with an unchanged key
  // must not refetch — only refetch()/league/auth events (refreshKey)
  // or a param change do.
  const settledKeyRef = useRef("");

  // Serialize params so callers can pass literal objects without
  // re-triggering the effect every render (siteOverridesKey pattern).
  const paramsKey = useMemo(() => JSON.stringify(params || {}), [params]);

  useEffect(() => {
    const bump = () => setRefreshKey((k) => k + 1);
    window.addEventListener("league:changed", bump);
    window.addEventListener("auth:changed", bump);
    return () => {
      window.removeEventListener("league:changed", bump);
      window.removeEventListener("auth:changed", bump);
    };
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;
    const runKey = `${path}|${paramsKey}|${refreshKey}`;
    if (settledKeyRef.current === runKey) return undefined;
    const ctl = new AbortController();
    abortRef.current?.abort();
    abortRef.current = ctl;
    let cancelled = false;

    async function run() {
      setLoading(true);
      try {
        const search = new URLSearchParams();
        const leagueKey = readActiveLeagueKey();
        if (leagueKey) search.set("leagueKey", leagueKey);
        for (const [k, v] of Object.entries(JSON.parse(paramsKey))) {
          if (v !== undefined && v !== null && v !== "") search.set(k, v);
        }
        const qs = search.toString();
        const res = await fetch(qs ? `${path}?${qs}` : path, {
          cache: "no-store",
          signal: ctl.signal,
        });
        let body = null;
        try {
          body = await res.json();
        } catch {
          body = null;
        }
        if (cancelled) return;
        const fail = classify(res.status, body);
        if (fail) {
          setFailure(fail);
          setData(null);
        } else {
          setFailure(null);
          setData(body);
        }
        settledKeyRef.current = runKey;
      } catch (err) {
        if (cancelled || err?.name === "AbortError") return;
        setFailure({ kind: "error", message: err?.message || "Request failed" });
        setData(null);
        settledKeyRef.current = runKey;
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    run();
    return () => {
      cancelled = true;
      ctl.abort();
    };
  }, [path, paramsKey, enabled, refreshKey, classify]);

  const refetch = useCallback(() => setRefreshKey((k) => k + 1), []);

  return { loading, data, failure, refetch };
}

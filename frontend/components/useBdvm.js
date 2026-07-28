"use client";

/**
 * useBdvmEndpoint — tri-state fetch for the BDVM endpoints
 * (/api/bdvm/values | roster | trades) with the flag-off and
 * data-not-ready states rendered distinctly from real errors.
 *
 * League threading follows the documented module pattern (see
 * lib/dynasty-data.js: useLeague can't be imported from data modules —
 * import cycle): read the active league key from localStorage at fetch
 * time, and refetch on the `league:changed` / `auth:changed` window
 * events that useLeague/login dispatch.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { classifyBdvmFailure } from "@/lib/bdvm";

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
 * @param {string} path — relative endpoint ("/api/bdvm/values")
 * @param {object} opts — { params: plain object of query params,
 *                          enabled: fetch only when true (lazy tabs) }
 * @returns {{ loading, data, failure, refetch }}
 *   failure: null | { kind: "disabled"|"not_ready"|"unavailable"|"auth"|"error", message }
 */
export function useBdvmEndpoint(path, { params, enabled = true } = {}) {
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
        const fail = classifyBdvmFailure(res.status, body);
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
  }, [path, paramsKey, enabled, refreshKey]);

  const refetch = useCallback(() => setRefreshKey((k) => k + 1), []);

  return { loading, data, failure, refetch };
}

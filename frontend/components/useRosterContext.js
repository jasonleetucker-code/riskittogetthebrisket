"use client";

/**
 * useRosterContext — fetches the Perfect Draft roster context.
 *
 * Deliberately thin.  The payload is static for the whole draft (rosters,
 * board values, waiver levels, the cut ladder), so this fetches once per
 * (league, team) and lets the optimizer re-run locally against live
 * localStorage state on every recorded pick.  Re-fetching per pick would
 * add latency to the one interaction that has to feel instant.
 *
 * League threading follows the documented module pattern (see
 * `useBdvm.js`): read the active league from localStorage at fetch time —
 * importing `useLeague` from a data module creates a cycle — and refetch on
 * the `league:changed` / `auth:changed` window events.
 */

import { useCallback, useEffect, useRef, useState } from "react";

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
 * @param {object} opts
 * @param {string} [opts.teamName] — display name of the team to analyse
 * @param {boolean} [opts.enabled]
 * @returns {{loading, teams, context, failure, refetch}}
 *   `failure` reuses the BDVM classifier's shape; the panel treats every
 *   non-null value as "vanish silently", which is the house posture for an
 *   add-on surface bolted onto someone else's page.
 */
export function useRosterContext({ teamName = "", enabled = true } = {}) {
  const [loading, setLoading] = useState(Boolean(enabled));
  const [payload, setPayload] = useState(null);
  const [failure, setFailure] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const abortRef = useRef(null);
  const settledKeyRef = useRef("");

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
    const runKey = `${teamName}|${refreshKey}`;
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
        if (teamName) search.set("teamName", teamName);
        const qs = search.toString();
        const res = await fetch(
          qs ? `/api/draft/roster-context?${qs}` : "/api/draft/roster-context",
          { cache: "no-store", signal: ctl.signal },
        );
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
          setPayload(null);
        } else {
          setFailure(null);
          setPayload(body);
        }
        settledKeyRef.current = runKey;
      } catch (err) {
        if (cancelled || err?.name === "AbortError") return;
        setFailure({ kind: "error", message: err?.message || "Request failed" });
        setPayload(null);
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
  }, [teamName, enabled, refreshKey]);

  const refetch = useCallback(() => setRefreshKey((k) => k + 1), []);

  return {
    loading,
    teams: payload?.teams || [],
    context: payload?.context || null,
    failure,
    refetch,
  };
}

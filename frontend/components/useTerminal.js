"use client";

import { useEffect, useMemo, useRef, useState } from "react";

/**
 * useTerminal — fetch the server-side terminal aggregation.
 *
 * Returns the /api/terminal payload for the given (ownerId,
 * windowDays) combination.  Single-flighted + module-cached with a
 * 30s TTL, so multiple components reading the same combination
 * produce one network request.
 *
 * This hook is standalone — it does NOT depend on TerminalLayout or
 * any React context — so any surface in the app can opt in to the
 * server-computed portfolio / movers / signals without reshaping
 * the component tree.
 *
 * The hook is auth-agnostic: an authenticated request returns the
 * private payload (signals, portfolio, watchlist), an anonymous
 * request returns the public slice (league + top150 movers + top-
 * 150 news only).  The ``authenticated`` flag on the payload
 * tells consumers which mode they got.
 *
 * Callers that want the private payload but are happy to fall back
 * to local computation when the fetch 401s should inspect
 * ``state.authenticated`` on the returned payload — when it's
 * false, ``state.portfolio`` and ``state.signals`` will be null /
 * empty and the caller should rely on its own fallback path.
 */

const TTL_MS = 30_000;
const cache = new Map(); // key → { result, expires }
const inflight = new Map(); // key → Promise

function cacheKey({ ownerId, name, windowDays }) {
  return `${ownerId || "_"}::${name || "_"}::${windowDays || 30}`;
}

async function fetchTerminal({ ownerId, name, windowDays, signal }) {
  const key = cacheKey({ ownerId, name, windowDays });
  const now = Date.now();
  const cached = cache.get(key);
  if (cached && cached.expires > now) return cached.result;
  if (inflight.has(key)) return inflight.get(key);

  const params = new URLSearchParams();
  if (ownerId) params.set("team", ownerId);
  if (name) params.set("teamName", name);
  if (windowDays) params.set("windowDays", String(windowDays));
  const url = `/api/terminal?${params.toString()}`;

  const promise = fetch(url, {
    credentials: "same-origin",
    signal,
    headers: { "Cache-Control": "no-store" },
  })
    .then(async (res) => {
      if (!res.ok && res.status !== 503) {
        throw new Error(`terminal ${res.status}`);
      }
      const data = await res.json();
      cache.set(key, { result: data, expires: Date.now() + TTL_MS });
      inflight.delete(key);
      return data;
    })
    .catch((err) => {
      inflight.delete(key);
      throw err;
    });
  inflight.set(key, promise);
  return promise;
}

export function invalidateTerminalCache() {
  cache.clear();
  inflight.clear();
}

/**
 * Read the terminal payload for a team (or the public slice if no
 * ownerId is provided).  ``windowDays`` defaults to 30; callers can
 * widen to 7/30/90/180 via the window selector in the Team Command
 * Header.
 */
export function useTerminal({ ownerId = "", teamName = "", windowDays = 30 } = {}) {
  const [state, setState] = useState({
    loading: true,
    error: null,
    payload: null,
  });
  // Forces a re-fetch when the active league changes — same pattern
  // as useDynastyData.  Keeps the hook signature unchanged while
  // wiring league-awareness for the Phase 1 migration.
  const [leagueRefreshKey, setLeagueRefreshKey] = useState(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    function onLeagueChanged() {
      invalidateTerminalCache();
      setLeagueRefreshKey((v) => v + 1);
    }
    if (typeof window === "undefined") return undefined;
    window.addEventListener("league:changed", onLeagueChanged);
    return () => window.removeEventListener("league:changed", onLeagueChanged);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setState((prev) => ({ ...prev, loading: true, error: null }));
    fetchTerminal({ ownerId, name: teamName, windowDays, signal: controller.signal })
      .then((payload) => {
        if (!mounted.current) return;
        setState({ loading: false, error: null, payload });
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        if (!mounted.current) return;
        setState({
          loading: false,
          error: err?.message || "terminal_fetch_failed",
          payload: null,
        });
      });
    return () => controller.abort();
  }, [ownerId, teamName, windowDays, leagueRefreshKey]);

  const value = useMemo(() => {
    const p = state.payload || {};
    return {
      loading: state.loading,
      error: state.error,
      authenticated: !!p.authenticated,
      stale: !!p.stale,
      staleAs: p.staleAs || null,
      team: p.team || null,
      availableTeams: p.availableTeams || [],
      teamAggregates: p.teamAggregates || null,
      movers: p.movers || { roster: [], league: [], top150: [] },
      signals: p.signals || [],
      portfolio: p.portfolio || null,
      news: p.news || { items: [], count: 0 },
      watchlist: p.watchlist || [],
      trendWindows: p.trendWindows || [7, 30, 90, 180],
      meta: p.meta || {},
      generatedAt: p.generatedAt || null,
      windowDays,
    };
  }, [state, windowDays]);
  return value;
}

"use client";

import { useEffect, useMemo, useState } from "react";
import { useSettings } from "@/components/useSettings";
import { applyValuationModeParam } from "@/lib/valuation-mode";

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
const inflight = new Map(); // key → shared request with subscriber ownership
let cacheEpoch = 0;
const LEAGUE_LOCAL_KEY = "next_active_league_v1";

// Read the active league key from localStorage.  ``useLeague`` writes
// here on every switch and server-side user state mirrors it, so this
// is a fast + sync read.  We can't ``useLeague`` inside this module
// because useLeague already imports ``invalidateTerminalCache`` from
// us — that cycle would blow up at import time.
function readActiveLeagueKey() {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem(LEAGUE_LOCAL_KEY) || "";
  } catch {
    return "";
  }
}

function fetchTerminal({ ownerId, name, windowDays }) {
  const leagueKey = readActiveLeagueKey();
  const params = new URLSearchParams();
  applyValuationModeParam(params);
  if (ownerId) params.set("team", ownerId);
  if (name) params.set("teamName", name);
  if (windowDays) params.set("windowDays", String(windowDays));
  if (leagueKey) params.set("leagueKey", leagueKey);
  // The exact effective query is the identity: absence is not a literal
  // underscore and delimiters inside a team name cannot join fields.
  const key = JSON.stringify([...params.entries()]);
  const now = Date.now();
  const cached = cache.get(key);
  if (cached && cached.expires > now) return { promise: Promise.resolve(cached.result), release() {} };
  function subscribe(entry) {
    entry.subscribers += 1;
    return { promise: entry.promise, release() {
      entry.subscribers -= 1;
      if (entry.subscribers === 0 && inflight.get(key) === entry) {
        inflight.delete(key);
        entry.controller.abort();
      }
    } };
  }
  if (inflight.has(key)) return subscribe(inflight.get(key));

  const url = `/api/terminal?${params.toString()}`;

  const epoch = cacheEpoch;
  const entry = { subscribers: 0, controller: new AbortController(), promise: null };
  entry.promise = fetch(url, {
    credentials: "same-origin",
    signal: entry.controller.signal,
    headers: { "Cache-Control": "no-store" },
  })
    .then(async (res) => {
      if (!res.ok && res.status !== 503) {
        throw new Error(`terminal ${res.status}`);
      }
      const data = await res.json();
      if (epoch === cacheEpoch && inflight.get(key) === entry) cache.set(key, { result: data, expires: Date.now() + TTL_MS });
      if (inflight.get(key) === entry) inflight.delete(key);
      return data;
    })
    .catch((err) => {
      if (inflight.get(key) === entry) inflight.delete(key);
      throw err;
    });
  inflight.set(key, entry);
  return subscribe(entry);
}

export function invalidateTerminalCache() {
  cacheEpoch += 1;
  cache.clear();
  for (const entry of inflight.values()) entry.controller.abort();
  inflight.clear();
}

// Invalidate once per event, including when no terminal panel is mounted.
// Per-subscriber invalidation would discard another subscriber's new flight.
if (typeof window !== "undefined") {
  window.addEventListener("league:changed", invalidateTerminalCache);
  window.addEventListener("auth:changed", invalidateTerminalCache);
}

/**
 * Read the terminal payload for a team (or the public slice if no
 * ownerId is provided).  ``windowDays`` defaults to 30; callers can
 * widen to 7/30/90/180 via the window selector in the Team Command
 * Header.
 */
export function useTerminal({ ownerId = "", teamName = "", windowDays = 30, skip = false } = {}) {
  const [state, setState] = useState({
    loading: true,
    error: null,
    payload: null,
  });
  // Forces a re-fetch when the active league changes — same pattern
  // as useDynastyData.  Keeps the hook signature unchanged while
  // wiring league-awareness for the Phase 1 migration.
  const [leagueRefreshKey, setLeagueRefreshKey] = useState(0);
  // The selected board is a fetch input, so it has to be a fetch
  // DEPENDENCY.  ``fetchTerminal`` reads it from localStorage, which
  // React cannot observe — without this the payload would keep
  // showing the previous board until some other input changed.
  const { settings } = useSettings();
  const valuationMode = settings?.valuationMode || "market";
  const identity = JSON.stringify([ownerId, teamName, windowDays, leagueRefreshKey, valuationMode, skip, cacheEpoch]);

  useEffect(() => {
    function onLeagueChanged() {
      setLeagueRefreshKey((v) => v + 1);
    }
    if (typeof window === "undefined") return undefined;
    window.addEventListener("league:changed", onLeagueChanged);
    window.addEventListener("auth:changed", onLeagueChanged);
    return () => {
      window.removeEventListener("league:changed", onLeagueChanged);
      window.removeEventListener("auth:changed", onLeagueChanged);
    };
  }, []);

  useEffect(() => {
    // ``skip`` (team identity still resolving from the contract):
    // stay in the loading state without fetching.  Before this gate,
    // every terminal surface fired an ``ownerId: ""`` fetch while the
    // contract loaded and a second fetch once the team resolved —
    // two /api/terminal builds per page view, one of them discarded.
    if (skip) return undefined;
    let active = true;
    const epoch = cacheEpoch;
    setState({ identity, loading: true, error: null, payload: null });
    const subscription = fetchTerminal({ ownerId, name: teamName, windowDays });
    subscription.promise
      .then((payload) => {
        if (!active || epoch !== cacheEpoch) return;
        setState({ identity, loading: false, error: null, payload });
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        if (!active || epoch !== cacheEpoch) return;
        setState({
          identity,
          loading: false,
          error: err?.message || "terminal_fetch_failed",
          payload: null,
        });
      });
    return () => { active = false; subscription.release(); };
  }, [ownerId, teamName, windowDays, identity, skip]);

  const value = useMemo(() => {
    const current = !skip && state.identity === identity;
    const p = current ? state.payload || {} : {};
    return {
      loading: current ? state.loading : true,
      error: current ? state.error : null,
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
  }, [state, windowDays, identity, skip]);
  return value;
}

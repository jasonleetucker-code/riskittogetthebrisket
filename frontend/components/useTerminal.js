"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTeam } from "@/components/useTeam";

/**
 * useTerminal — consume the server-side aggregation endpoint.
 *
 * Replaces the old pattern where every terminal panel reached into
 * useApp/useRankHistory/useNews independently and recomputed
 * valueFromRank, windowTrend, volatility, and signal rules
 * client-side.  The backend now computes all of that in one pass and
 * hands back a fully rendered payload.  The client just renders.
 *
 * Request shape: ``GET /api/terminal?team=<ownerId>&teamName=<name>&windowDays=<N>``
 *
 * Response shape: see ``src/api/terminal.py::build_terminal_payload``.
 *
 * Cache: 30s single-flight per (ownerId, windowDays) pair — multiple
 * panels mounting at once issue exactly one request per combination.
 */

const TTL_MS = 30_000;

// Single-flight cache keyed by ``${ownerId}::${windowDays}``.
const cache = new Map();   // key → { result, expires }
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
      if (!res.ok) throw new Error(`terminal ${res.status}`);
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

export function useTerminal({ windowDays = 30 } = {}) {
  const { selectedTeam, loading: teamLoading } = useTeam();
  const ownerId = selectedTeam?.ownerId || "";
  const name = selectedTeam?.name || "";
  const [state, setState] = useState({
    loading: true,
    error: null,
    payload: null,
  });
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (teamLoading) return undefined;
    const controller = new AbortController();
    setState((prev) => ({ ...prev, loading: true, error: null }));
    fetchTerminal({ ownerId, name, windowDays, signal: controller.signal })
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
  }, [ownerId, name, windowDays, teamLoading]);

  const {
    team,
    availableTeams,
    teamAggregates,
    movers,
    signals,
    portfolio,
    news,
    watchlist,
    trendWindows,
    meta,
    generatedAt,
  } = state.payload || {};

  const value = useMemo(
    () => ({
      loading: state.loading,
      error: state.error,
      team: team || null,
      availableTeams: availableTeams || [],
      teamAggregates: teamAggregates || null,
      movers: movers || { roster: [], league: [], top150: [] },
      signals: signals || [],
      portfolio: portfolio || null,
      news: news || { items: [], count: 0 },
      watchlist: watchlist || [],
      trendWindows: trendWindows || [7, 30, 90, 180],
      meta: meta || {},
      generatedAt: generatedAt || null,
      windowDays,
    }),
    [state, windowDays],
  );
  return value;
}

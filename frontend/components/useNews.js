"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchNews as fetchNewsRaw, rankByRelevance } from "@/lib/news-service";

/**
 * useNews — shared fetch + scoring hook for the landing page.
 *
 * Four different panels (MarketTicker, TeamNewsFeed, BuySellHold,
 * ScoutingIntel) all want the same news payload scored against the
 * same roster.  Before this hook every one of them fetched the
 * endpoint independently on mount, issuing up to four parallel
 * requests.  The underlying ``fetchNews`` has no cache, so nothing
 * deduplicated them.
 *
 * This hook single-flights the fetch at the module level (60s TTL)
 * and memoizes the relevance-scored output so every consumer gets
 * the already-scored list for free.  One request per ~minute across
 * the whole landing page, regardless of how many panels consume it.
 */

const TTL_MS = 60_000;

// Module-level cache: single entry.  The fixture is tiny and the
// real endpoint (when wired) will return a compact list too, so we
// don't need a multi-key cache — the scope filter is applied per
// consumer, not baked into the key.
let cache = null;            // { result, expires }
let inflight = null;         // Promise<result>

async function getNews() {
  const now = Date.now();
  if (cache && cache.expires > now) return cache.result;
  if (inflight) return inflight;
  inflight = fetchNewsRaw()
    .then((result) => {
      cache = { result, expires: Date.now() + TTL_MS };
      inflight = null;
      return result;
    })
    .catch((err) => {
      inflight = null;
      throw err;
    });
  return inflight;
}

export function invalidateNewsCache() {
  cache = null;
}

export function useNews({ rosterNames, leagueNames } = {}) {
  const [state, setState] = useState(() => ({
    loading: true,
    error: null,
    items: [],
    source: null,
    unavailable: false,
    reason: null,
  }));

  useEffect(() => {
    let active = true;
    getNews()
      .then((res) => {
        if (!active) return;
        setState({
          loading: false,
          error: null,
          items: Array.isArray(res.items) ? res.items : [],
          source: res.source || null,
          unavailable: !!res.unavailable,
          reason: res.reason || null,
        });
      })
      .catch((err) => {
        if (!active) return;
        setState({
          loading: false,
          error: err?.message || "Failed to load news",
          items: [],
          source: null,
          unavailable: true,
          reason: "fetch_failed",
        });
      });
    return () => {
      active = false;
    };
  }, []);

  // Score once per consumer based on their (possibly differing)
  // rosterNames / leagueNames — the raw items cost us nothing to
  // project.
  const scored = useMemo(() => {
    if (!state.items.length) return [];
    return rankByRelevance(state.items, {
      rosterNames: rosterNames || [],
      leagueNames: leagueNames || [],
    });
  }, [state.items, rosterNames, leagueNames]);

  return { ...state, scored };
}

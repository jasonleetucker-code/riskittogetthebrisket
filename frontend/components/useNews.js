"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchNews as fetchNewsRaw, rankByRelevance } from "@/lib/news-service";
import {
  buildDigestIndex,
  buildNewsIndexByPlayer,
} from "@/lib/player-name-match";

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
// Failed fetches (unavailable state) get a much shorter cache life
// so a transient 503 doesn't pin every mounted surface to "news
// unavailable" for a full minute after the backend recovers.
const FAILURE_TTL_MS = 15_000;
// Retry cadence while a consumer stays mounted after a failure:
// 15s, 30s, then 60s (capped).  Aligned with FAILURE_TTL_MS so the
// first retry always misses the expired failure entry and actually
// refetches.
const RETRY_BASE_MS = 15_000;
const RETRY_MAX_MS = 60_000;

// Module-level cache: single entry.  The payload is a compact
// ~100-item list, so we don't need a multi-key cache — the scope
// filter is applied per consumer, not baked into the key.
let cache = null;            // { result, expires }
let inflight = null;         // Promise<result>

async function getNews() {
  const now = Date.now();
  if (cache && cache.expires > now) return cache.result;
  if (inflight) return inflight;
  inflight = fetchNewsRaw()
    .then((result) => {
      // Unavailable results are cached briefly (dedupe across the
      // panels mounting together) but expire fast so recovery isn't
      // blocked behind the success TTL.
      const ttl = result?.unavailable ? FAILURE_TTL_MS : TTL_MS;
      cache = { result, expires: Date.now() + ttl };
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

/** Test-only: clear all module-level state (cache + inflight). */
export function _resetNewsCacheForTests() {
  cache = null;
  inflight = null;
}

/** Retry delay for the (1-based) nth consecutive failure. */
export function newsRetryDelayMs(attempt) {
  const n = Math.max(1, attempt | 0);
  return Math.min(RETRY_BASE_MS * 2 ** (n - 1), RETRY_MAX_MS);
}

// Exported for tests — the hook wraps this.
export { getNews as _getNewsForTests };

export function useNews({ rosterNames, leagueNames } = {}) {
  const [state, setState] = useState(() => ({
    loading: true,
    error: null,
    items: [],
    digests: [],
    source: null,
    unavailable: false,
    reason: null,
  }));

  useEffect(() => {
    let active = true;
    let timer = null;
    let attempt = 0;

    // Automatic recovery: while this consumer stays mounted, a
    // failed fetch schedules a re-fetch with modest backoff
    // (15s → 30s → 60s cap).  Combined with the short failure TTL
    // in ``getNews`` the retry actually reaches the network, so a
    // transient backend 503 clears itself instead of pinning the
    // page to "news unavailable" until remount.
    const scheduleRetry = () => {
      attempt += 1;
      timer = setTimeout(load, newsRetryDelayMs(attempt));
    };

    function load() {
      getNews()
        .then((res) => {
          if (!active) return;
          setState({
            loading: false,
            error: null,
            items: Array.isArray(res.items) ? res.items : [],
            digests: Array.isArray(res.digests) ? res.digests : [],
            source: res.source || null,
            unavailable: !!res.unavailable,
            reason: res.reason || null,
          });
          if (res.unavailable) {
            scheduleRetry();
          } else {
            attempt = 0;
          }
        })
        .catch((err) => {
          if (!active) return;
          setState({
            loading: false,
            error: err?.message || "Failed to load news",
            items: [],
            digests: [],
            source: null,
            unavailable: true,
            reason: "fetch_failed",
          });
          scheduleRetry();
        });
    }

    load();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
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

  // Index news items by normalized player-name key so consumers
  // (rankings chip, PlayerPopup, News tab) can look up every item
  // about a player in O(1).  Each entry is the FULL newest-first
  // list for that player; look up with
  // ``lookupPlayerNews(byPlayer, name)`` from
  // ``@/lib/player-name-match`` so the fuzzy normalization (initials,
  // suffixes, apostrophes, accents) matches the backend's
  // ``normalize_player_name``.
  const byPlayer = useMemo(
    () => buildNewsIndexByPlayer(state.items),
    [state.items],
  );

  // Per-player digest index (backend ``playerDigests``): resolve a
  // specific row's digest with ``lookupPlayerDigest(digestByPlayer,
  // name, { position })`` — collision twins keep separate entries.
  const digestByPlayer = useMemo(
    () => buildDigestIndex(state.digests),
    [state.digests],
  );

  return { ...state, scored, byPlayer, digestByPlayer };
}

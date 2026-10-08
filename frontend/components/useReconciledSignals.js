"use client";

import { useEffect, useState } from "react";

/**
 * useReconciledSignals — read the ONE Buy/Sell owner,
 * `GET /api/signals/reconciled` (C6-SIG-01), for a consumer surface.
 *
 * League scope (every player any emitter spoke about) for the selected team,
 * so the payload carries both the global BUY universe and that team's roster
 * membership in ONE request.  Module-cached and single-flighted per exact
 * query, so remounts and sibling consumers do not rebuild a payload the
 * server computes from scratch on every call.
 *
 * Private and fail-closed: `enabled: false` (no private session in this
 * shell) never fetches, and a 401/403 is cached as `unauthorized` — the
 * consumer hides private verdicts, and nothing retries into a 401 storm until
 * auth actually changes (`auth:changed`).
 *
 * Status vocabulary: `idle` (disabled / waiting on team identity), `loading`,
 * `ok`, `unauthorized`, `unavailable` (503 — the owner said data not ready),
 * `error`.
 */

const OK_TTL_MS = 5 * 60_000;
const FAILURE_TTL_MS = 60_000;
const cache = new Map(); // key → { result, expires }
const inflight = new Map(); // key → promise
let cacheEpoch = 0;

export function reconciledSignalsUrl({ leagueKey = "", ownerId = "", teamName = "" } = {}) {
  const params = new URLSearchParams();
  params.set("scope", "league");
  if (ownerId) params.set("team", ownerId);
  else if (teamName) params.set("teamName", teamName);
  if (leagueKey) params.set("leagueKey", leagueKey);
  return `/api/signals/reconciled?${params.toString()}`;
}

async function readResult(res) {
  if (res.status === 401 || res.status === 403) {
    // Never forward a private body on an auth failure.
    return { status: "unauthorized", payload: null };
  }
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (res.ok) return { status: "ok", payload: body };
  if (res.status === 503) {
    return { status: "unavailable", payload: null, message: body?.message || null };
  }
  return { status: "error", payload: null, message: body?.error || `http_${res.status}` };
}

export function fetchReconciledSignals(url, { fetchImpl } = {}) {
  const doFetch = fetchImpl || (typeof fetch === "function" ? fetch : null);
  const now = Date.now();
  const cached = cache.get(url);
  if (cached && cached.expires > now) return Promise.resolve(cached.result);
  if (inflight.has(url)) return inflight.get(url);
  const epoch = cacheEpoch;
  const promise = Promise.resolve()
    .then(() =>
      doFetch(url, {
        credentials: "same-origin",
        headers: { "Cache-Control": "no-store" },
      }),
    )
    .then(readResult)
    .catch((err) => ({ status: "error", payload: null, message: err?.message || "fetch_failed" }))
    .then((result) => {
      if (epoch === cacheEpoch) {
        // An auth refusal stays cached until auth changes (the listener below
        // clears it) — retrying a 401 on a timer is the storm we refuse.
        const ttl =
          result.status === "ok"
            ? OK_TTL_MS
            : result.status === "unauthorized"
              ? Number.POSITIVE_INFINITY
              : FAILURE_TTL_MS;
        cache.set(url, { result, expires: now + ttl });
      }
      if (inflight.get(url) === promise) inflight.delete(url);
      return result;
    });
  inflight.set(url, promise);
  return promise;
}

export function invalidateReconciledSignals() {
  cacheEpoch += 1;
  cache.clear();
  inflight.clear();
}

if (typeof window !== "undefined") {
  window.addEventListener("league:changed", invalidateReconciledSignals);
  window.addEventListener("auth:changed", invalidateReconciledSignals);
}

export function useReconciledSignals({ enabled = false, leagueKey = "", ownerId = "", teamName = "" } = {}) {
  const [epoch, setEpoch] = useState(0);
  const url = enabled ? reconciledSignalsUrl({ leagueKey, ownerId, teamName }) : null;
  const [state, setState] = useState({ url: null, status: "idle", payload: null });

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const bump = () => setEpoch((v) => v + 1);
    window.addEventListener("league:changed", bump);
    window.addEventListener("auth:changed", bump);
    return () => {
      window.removeEventListener("league:changed", bump);
      window.removeEventListener("auth:changed", bump);
    };
  }, []);

  useEffect(() => {
    if (!url) return undefined;
    let active = true;
    setState((prev) => (prev.url === url && prev.status !== "loading" ? prev : { url, status: "loading", payload: null }));
    fetchReconciledSignals(url).then((result) => {
      if (active) setState({ url, ...result });
    });
    return () => {
      active = false;
    };
  }, [url, epoch]);

  if (!url) return { status: "idle", payload: null };
  // A result for a different query (team or league switched) is never shown
  // for the current one — a previous team's roster must not leak into SELL.
  if (state.url !== url) return { status: "loading", payload: null };
  return state;
}

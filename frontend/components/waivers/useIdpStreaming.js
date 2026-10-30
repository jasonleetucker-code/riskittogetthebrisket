"use client";

/**
 * useIdpStreaming — fetch one team's Weekly IDP Streaming payload.
 *
 * Used only inside the lazy IdpStreamingPanel chunk (the page's gate probe is
 * ./useIdpStreamingGate.js, which deliberately imports nothing from
 * lib/idp-streaming so that module stays out of the page chunk).  Any
 * failure is a stated, classified state
 * (`lib/idp-streaming.js::classifyStreamingFailure`), never a blank and never
 * a number.  Display only — no projection, value or lineup math.
 */
import { useEffect, useState } from "react";
import {
  IDP_STREAMING_ENDPOINT,
  buildStreamingRequest,
  classifyStreamingFailure,
  isStaleStreamingPayload,
} from "@/lib/idp-streaming";

async function post(body, signal) {
  const res = await fetch(IDP_STREAMING_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal,
    body: JSON.stringify(body),
  });
  const json = await res.json().catch(() => null);
  return { res, json };
}

export function useIdpStreaming({
  leagueKey,
  ownerId,
  params = {},
  enabled = true,
} = {}) {
  const body = buildStreamingRequest({ leagueKey, ownerId, ...params });
  const identity = JSON.stringify([body, enabled]);
  const [state, setState] = useState({
    identity: null,
    payload: null,
    failure: null,
  });

  useEffect(() => {
    if (!enabled) {
      setState({ identity, payload: null, failure: null });
      return undefined;
    }
    let cancelled = false;
    const ctl = new AbortController();
    // Keep the previous payload on screen while the new one computes (no
    // flash-to-empty); `refreshing` marks it as superseded.
    setState((prev) => ({ ...prev, identity, failure: null, loading: true }));
    (async () => {
      try {
        const { res, json } = await post(JSON.parse(identity)[0], ctl.signal);
        if (cancelled) return;
        if (!res.ok || !json || typeof json !== "object") {
          setState({
            identity,
            payload: null,
            failure: classifyStreamingFailure(res.status, json),
          });
          return;
        }
        const stale = isStaleStreamingPayload(json, { leagueKey, ownerId });
        setState({ identity, payload: stale ? null : json, failure: null });
      } catch (err) {
        if (cancelled || err?.name === "AbortError") return;
        setState({
          identity,
          payload: null,
          failure: {
            kind: "offline",
            message: "Couldn't reach weekly IDP streaming.",
          },
        });
      }
    })();
    return () => {
      cancelled = true;
      ctl.abort();
    };
  }, [enabled, identity, leagueKey, ownerId]);

  const current = state.identity === identity;
  // A payload for another league or team never renders, even mid-refresh.
  const shown =
    state.payload &&
    !isStaleStreamingPayload(state.payload, { leagueKey, ownerId })
      ? state.payload
      : null;
  return {
    payload: shown,
    failure: current ? state.failure : null,
    loading: Boolean(enabled) && (!current || Boolean(state.loading)),
  };
}

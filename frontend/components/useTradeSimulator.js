"use client";

import { useCallback, useState } from "react";

/**
 * useTradeSimulator — client hook around ``POST /api/trade/simulate``.
 *
 * No caching — every simulate() is a fresh POST because the input
 * changes on every interaction (user is building a trade).  Dedup
 * would need to cache on the request hash, which isn't worth the
 * complexity for a low-frequency endpoint.
 *
 * Usage:
 *
 *   const { simulate, result, loading, error } = useTradeSimulator();
 *   await simulate({ playersIn: ["Ja'Marr Chase"], playersOut: ["..."] });
 *   // `result` now has the delta payload (or null when loading /
 *   // not yet called)
 */
export function useTradeSimulator() {
  const [state, setState] = useState({
    loading: false,
    error: null,
    result: null,
  });

  const simulate = useCallback(async (body) => {
    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      // Attach the active league key if the caller didn't supply
      // one.  The backend validates it against the registry and
      // returns 503 ``data_not_ready`` when the loaded contract is
      // for a different league — that's a nicer failure mode than
      // simulating the wrong league silently.
      const payload = { ...(body || {}) };
      if (!payload.leagueKey && typeof window !== "undefined") {
        try {
          const k = localStorage.getItem("next_active_league_v1") || "";
          if (k) payload.leagueKey = k;
        } catch { /* ignore */ }
      }
      const res = await fetch("/api/trade/simulate", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const err = await res.json();
          msg = err?.error || msg;
        } catch {
          /* ignore */
        }
        setState({ loading: false, error: msg, result: null });
        return null;
      }
      const data = await res.json();
      setState({ loading: false, error: null, result: data });
      return data;
    } catch (err) {
      setState({
        loading: false,
        error: err?.message || "fetch_failed",
        result: null,
      });
      return null;
    }
  }, []);

  const reset = useCallback(() => {
    setState({ loading: false, error: null, result: null });
  }, []);

  return { ...state, simulate, reset };
}

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
      const res = await fetch("/api/trade/simulate", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
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

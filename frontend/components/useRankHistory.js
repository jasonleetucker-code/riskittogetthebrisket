"use client";

import { useEffect, useState } from "react";
import { fetchRankHistory } from "@/lib/value-history";

/**
 * useRankHistory — shared hook for the landing page.
 *
 * The underlying module-level cache in ``value-history.js`` is
 * single-flight with a 60s TTL, so mounting this hook in N panels
 * produces exactly one network request per 60s regardless of N.
 * Callers still get their own loading/error state.
 */
export function useRankHistory({ days = 30 } = {}) {
  const [state, setState] = useState({
    loading: true,
    error: null,
    history: null,
    days,
  });

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setState((prev) => ({ ...prev, loading: true, error: null }));

    fetchRankHistory({ days, signal: controller.signal })
      .then((res) => {
        if (!active) return;
        setState({
          loading: false,
          error: null,
          history: res.history,
          days: res.days,
        });
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        if (!active) return;
        setState({
          loading: false,
          error: err?.message || "Failed to load rank history",
          history: null,
          days,
        });
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [days]);

  return state;
}

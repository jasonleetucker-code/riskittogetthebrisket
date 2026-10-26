"use client";

/**
 * useTradeAsofGrades — At-the-Time grades for the visible trade history,
 * one POST per distinct history (owner package 2026-10-17).  The backend
 * (``POST /api/trades/asof-grades``) owns every number; this only carries
 * the request and the three honest states: loading, ok, unavailable.
 *
 * @returns {{ status: "idle"|"loading"|"ok"|"unavailable", byTrade: Map, packageModel, reason }}
 */

import { useEffect, useMemo, useState } from "react";
import {
  buildAsofRequest,
  indexAsofResponse,
} from "@/lib/trade-history-grades";

const EMPTY = new Map();

export function useTradeAsofGrades(analyzed) {
  const body = useMemo(() => {
    if (!Array.isArray(analyzed) || analyzed.length === 0) return null;
    return JSON.stringify(buildAsofRequest(analyzed));
  }, [analyzed]);
  const [state, setState] = useState({
    status: "idle",
    byTrade: EMPTY,
    packageModel: null,
    reason: null,
  });

  useEffect(() => {
    if (!body) {
      setState({
        status: "idle",
        byTrade: EMPTY,
        packageModel: null,
        reason: null,
      });
      return undefined;
    }
    const ctrl = new AbortController();
    setState((s) => ({ ...s, status: "loading" }));
    fetch("/api/trades/asof-grades", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body,
      signal: ctrl.signal,
    })
      .then(async (res) => {
        const payload = await res.json().catch(() => null);
        if (!res.ok || !payload) {
          setState({
            status: "unavailable",
            byTrade: EMPTY,
            packageModel: null,
            reason: `http_${res.status}`,
          });
          return;
        }
        setState({
          status: payload.available === false ? "unavailable" : "ok",
          byTrade: indexAsofResponse(payload),
          packageModel: payload.packageModel || null,
          reason:
            payload.available === false
              ? payload.reason || "unavailable"
              : null,
        });
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        setState({
          status: "unavailable",
          byTrade: EMPTY,
          packageModel: null,
          reason: "network_error",
        });
      });
    return () => ctrl.abort();
  }, [body]);

  return state;
}

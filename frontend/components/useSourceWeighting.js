"use client";

import { useCallback, useEffect, useState } from "react";
import { classifyContractFailure } from "@/lib/contract-failure";

/**
 * GET /api/sources/weighting, once per page.
 *
 * Source Health renders two panels off this one auth-gated payload — the
 * per-source voting status (`votingStatus`) and the freshness / weighting
 * diagnostic table (`sources`) — so the page calls this hook once and hands
 * the state to both rather than fetching the same payload twice.
 *
 * `skip` lets a component that was handed the state by its parent keep a
 * stable hook order without issuing its own request.
 */
export async function fetchSourceWeighting() {
  try {
    const res = await fetch("/api/sources/weighting", {
      credentials: "same-origin",
      headers: { "Cache-Control": "no-store" },
    });
    const body = await res.json().catch(() => null);
    if (!res.ok) return { data: null, failure: classifyContractFailure(res.status, body) };
    return { data: body, failure: null };
  } catch (err) {
    return {
      data: null,
      failure: classifyContractFailure(null, { message: err?.message }),
    };
  }
}

export function useSourceWeighting({ skip = false } = {}) {
  const [state, setState] = useState({ loading: !skip, data: null, failure: null });

  const reload = useCallback(async () => {
    setState((s) => ({ ...s, loading: true }));
    const out = await fetchSourceWeighting();
    setState({ loading: false, ...out });
  }, []);

  useEffect(() => {
    if (!skip) reload();
  }, [skip, reload]);

  return { ...state, reload };
}

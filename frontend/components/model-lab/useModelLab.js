"use client";

/**
 * useModelLab — the Model Lab's ONE request: `GET /api/model-lab`.
 *
 * Read-only by construction: this is the only network call the Model Lab
 * UI makes, it is a GET with no body, and `__tests__/model-lab-read-only`
 * pins that no module in the page's import graph issues anything else.
 *
 * The whole payload carries every family's detail, so the family view
 * reads from it rather than issuing a second request per family.
 *
 * Refresh keeps the content already on screen (contract §9: no
 * flash-to-empty); a refresh that fails surfaces the failure ABOVE the
 * prior content instead of replacing it.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { classifyContractFailure } from "@/lib/contract-failure";

export const MODEL_LAB_PATH = "/api/model-lab";

export function useModelLab() {
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const abortRef = useRef(null);

  useEffect(() => {
    const ctrl = new AbortController();
    abortRef.current?.abort();
    abortRef.current = ctrl;
    setLoading(true);
    (async () => {
      let res;
      try {
        res = await fetch(MODEL_LAB_PATH, {
          method: "GET",
          cache: "no-store",
          credentials: "same-origin",
          signal: ctrl.signal,
        });
      } catch (err) {
        if (ctrl.signal.aborted) return;
        setFailure(classifyContractFailure(null, null));
        setLoading(false);
        return;
      }
      let body = null;
      try {
        body = await res.json();
      } catch {
        body = null;
      }
      if (ctrl.signal.aborted) return;
      if (!res.ok) {
        setFailure(classifyContractFailure(res.status, body));
      } else if (!body || typeof body !== "object" || !Array.isArray(body.families)) {
        setFailure({
          kind: "no_data",
          code: "",
          message: "The Model Lab answered without a families list.",
          retryable: true,
        });
      } else {
        setData(body);
        setFailure(null);
      }
      setLoading(false);
    })();
    return () => ctrl.abort();
  }, [refreshKey]);

  const refetch = useCallback(() => setRefreshKey((k) => k + 1), []);

  return { data, failure, loading, refetch };
}

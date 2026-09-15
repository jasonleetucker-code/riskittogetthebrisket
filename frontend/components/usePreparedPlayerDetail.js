"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchPreparedPlayerDetail, refreshPreparedBoard } from "@/lib/prepared-player-detail";

export function usePreparedPlayerDetail(row, contract) {
  const generation = contract?.meta?.readModelGeneration;
  const needsDetail = Boolean(generation || row?.readModelKey);
  const [state, setState] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => {
    if (state?.status === 409) refreshPreparedBoard();
    setAttempt((n) => n + 1);
  }, [state?.status]);
  useEffect(() => {
    if (!row || !needsDetail || !contract) return undefined;
    let active = true;
    setState(null);
    fetchPreparedPlayerDetail(row, contract).then(
      (detail) => { if (active) setState({ input: row, generation, attempt, detail }); },
      (error) => { if (active) setState({ input: row, generation, attempt, error: error.message, status: error.status }); },
    );
    return () => { active = false; };
  }, [row, contract, generation, needsDetail, attempt]);
  if (!row || !needsDetail) return { row, loading: false, error: "", retry };
  const current = state?.input === row && state?.generation === generation && state?.attempt === attempt;
  return {
    row: current ? state.detail || null : null,
    loading: !current,
    error: current ? state.error || "" : "",
    retry,
  };
}

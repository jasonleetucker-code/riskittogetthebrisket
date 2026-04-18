"use client";

import { useCallback, useEffect, useRef, useState } from "react";

async function jfetch(url, opts = {}) {
  const res = await fetch(url, { cache: "no-store", ...opts });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { ok: false, error: text || "Invalid response" };
  }
  return { status: res.status, data };
}

/**
 * useCalibration — thin wrapper around the /api/idp-calibration proxy routes.
 *
 * Exposes imperative actions plus the standard { loading, error, data }
 * state for each operation. No external data-fetching library; matches
 * the repo convention of plain fetch + useState.
 */
export function useCalibration() {
  const [status, setStatus] = useState(null);
  const [runs, setRuns] = useState([]);
  const [production, setProduction] = useState(null);
  const [currentRun, setCurrentRun] = useState(null);
  const [loading, setLoading] = useState({
    status: false,
    runs: false,
    production: false,
    analyze: false,
    promote: false,
    runDetail: false,
    deleteRun: false,
    refreshBoard: false,
  });
  const [error, setError] = useState({});
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const setFlag = (key, value) =>
    setLoading((prev) => ({ ...prev, [key]: value }));
  const setErr = (key, value) =>
    setError((prev) => ({ ...prev, [key]: value || null }));

  const refreshStatus = useCallback(async () => {
    setFlag("status", true);
    setErr("status", null);
    const { status: http, data } = await jfetch("/api/idp-calibration/status");
    if (!mountedRef.current) return data;
    if (http >= 400) {
      setErr("status", data?.error || `HTTP ${http}`);
    } else {
      setStatus(data);
    }
    setFlag("status", false);
    return data;
  }, []);

  const refreshRuns = useCallback(async () => {
    setFlag("runs", true);
    setErr("runs", null);
    const { status: http, data } = await jfetch("/api/idp-calibration/runs");
    if (!mountedRef.current) return data;
    if (http >= 400) {
      setErr("runs", data?.error || `HTTP ${http}`);
    } else {
      setRuns(Array.isArray(data?.runs) ? data.runs : []);
    }
    setFlag("runs", false);
    return data;
  }, []);

  const refreshProduction = useCallback(async () => {
    setFlag("production", true);
    setErr("production", null);
    const { status: http, data } = await jfetch("/api/idp-calibration/production");
    if (!mountedRef.current) return data;
    if (http >= 400) {
      setErr("production", data?.error || `HTTP ${http}`);
    } else {
      setProduction(data);
    }
    setFlag("production", false);
    return data;
  }, []);

  const analyze = useCallback(async ({ testLeagueId, myLeagueId, settings }) => {
    setFlag("analyze", true);
    setErr("analyze", null);
    const { status: http, data } = await jfetch("/api/idp-calibration/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        test_league_id: testLeagueId,
        my_league_id: myLeagueId,
        settings: settings || {},
      }),
    });
    if (!mountedRef.current) return data;
    if (http >= 400 || data?.ok === false) {
      setErr("analyze", data?.error || `HTTP ${http}`);
    } else {
      setCurrentRun(data?.run || null);
      await refreshRuns();
    }
    setFlag("analyze", false);
    return data;
  }, [refreshRuns]);

  const loadRun = useCallback(async (runId) => {
    if (!runId) return null;
    setFlag("runDetail", true);
    setErr("runDetail", null);
    const { status: http, data } = await jfetch(
      `/api/idp-calibration/runs/${encodeURIComponent(runId)}`,
    );
    if (!mountedRef.current) return data;
    if (http >= 400 || data?.ok === false) {
      setErr("runDetail", data?.error || `HTTP ${http}`);
    } else {
      setCurrentRun(data?.run || null);
    }
    setFlag("runDetail", false);
    return data;
  }, []);

  const deleteRun = useCallback(async (runId) => {
    if (!runId) return null;
    setFlag("deleteRun", true);
    setErr("deleteRun", null);
    const { status: http, data } = await jfetch(
      `/api/idp-calibration/runs/${encodeURIComponent(runId)}`,
      { method: "DELETE" },
    );
    if (!mountedRef.current) return data;
    if (http >= 400 || data?.ok === false) {
      setErr("deleteRun", data?.error || `HTTP ${http}`);
    } else {
      await refreshRuns();
      setCurrentRun((prev) => (prev && prev.run_id === runId ? null : prev));
    }
    setFlag("deleteRun", false);
    return data;
  }, [refreshRuns]);

  const promote = useCallback(async ({ runId, activeMode }) => {
    setFlag("promote", true);
    setErr("promote", null);
    const { status: http, data } = await jfetch("/api/idp-calibration/promote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId, active_mode: activeMode || "blended" }),
    });
    if (!mountedRef.current) return data;
    if (http >= 400 || data?.ok === false) {
      setErr("promote", data?.error || `HTTP ${http}`);
    } else {
      await Promise.all([refreshProduction(), refreshStatus()]);
    }
    setFlag("promote", false);
    return data;
  }, [refreshProduction, refreshStatus]);

  const refreshBoard = useCallback(async () => {
    setFlag("refreshBoard", true);
    setErr("refreshBoard", null);
    const { status: http, data } = await jfetch(
      "/api/idp-calibration/refresh-board",
      { method: "POST" },
    );
    if (!mountedRef.current) return data;
    if (http >= 400 || data?.ok === false) {
      setErr("refreshBoard", data?.error || `HTTP ${http}`);
    }
    setFlag("refreshBoard", false);
    return data;
  }, []);

  return {
    status,
    runs,
    production,
    currentRun,
    setCurrentRun,
    loading,
    error,
    refreshStatus,
    refreshRuns,
    refreshProduction,
    analyze,
    loadRun,
    deleteRun,
    promote,
    refreshBoard,
  };
}

// Lightweight fetcher hooks for the ROS engine.  Reads only.
// Mirrors the shape of ``frontend/lib/dynasty-data.js`` but without
// any of the rankings-blend / value-mutation paths — ROS data is a
// separate read-only contract surfaced under /api/ros/*.

"use client";

import { useEffect, useState } from "react";

const FETCH_OPTS = { cache: "no-store" };

async function _getJson(url) {
  const res = await fetch(url, FETCH_OPTS);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} fetching ${url}`);
  }
  return res.json();
}

/**
 * Fetch /api/ros/team-strength for the given league.  Returns
 * ``{ teams, leagueKey, error? }``.  Cached snapshot today; PR2 wires
 * live recomputation against the active roster.
 */
export async function fetchRosTeamStrength(leagueKey) {
  const url = leagueKey
    ? `/api/ros/team-strength?leagueKey=${encodeURIComponent(leagueKey)}`
    : "/api/ros/team-strength";
  return _getJson(url);
}

export async function fetchRosStatus() {
  return _getJson("/api/ros/status");
}

export async function fetchRosSources() {
  return _getJson("/api/ros/sources");
}

export async function fetchRosPlayerValues({ limit = 500 } = {}) {
  return _getJson(`/api/ros/player-values?limit=${limit}`);
}

/**
 * React hook: lazy-fetch ROS team strength for the active league.
 * Returns ``{ data, loading, error }``.  Consumers re-render when the
 * leagueKey changes.
 */
export function useRosTeamStrength(leagueKey) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    fetchRosTeamStrength(leagueKey)
      .then((json) => {
        if (!active) return;
        setData(json);
      })
      .catch((err) => {
        if (!active) return;
        setError(err?.message || "Failed to load ROS team strength.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [leagueKey]);

  return { data, loading, error };
}

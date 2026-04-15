"use client";

import { useEffect, useMemo, useState } from "react";
import { buildRows, fetchDynastyData, getSiteKeys } from "@/lib/dynasty-data";
import { useSettings } from "@/components/useSettings";

export function useDynastyData() {
  // Read user-level source overrides from settings so per-source
  // toggles and weight sliders actually affect the rendered board.
  // `buildRows` forwards these to `computeUnifiedRanks`, which
  // bypasses backend-stamped fields whenever the user's configuration
  // diverges from the canonical registry defaults.
  const { settings } = useSettings();
  const siteOverrides = settings?.siteWeights || null;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [source, setSource] = useState("");
  const [rawData, setRawData] = useState(null);

  useEffect(() => {
    let active = true;
    async function run() {
      try {
        setLoading(true);
        setError("");
        const payload = await fetchDynastyData();
        if (!active) return;

        const data = payload?.data || null;
        setRawData(data);
        setSource(String(payload?.source || ""));

        // Detect structurally-valid but empty payloads that would silently render nothing.
        if (data && typeof data === "object") {
          const hasPlayers = Object.keys(data.players || {}).length > 0;
          const hasPlayersArray = Array.isArray(data.playersArray) && data.playersArray.length > 0;
          if (!hasPlayers && !hasPlayersArray) {
            setError("Data loaded but contains no players. Backend may still be initializing.");
          }
        } else if (!data) {
          setError("No data received from server. Check backend status.");
        }
      } catch (err) {
        if (!active) return;
        setError(err?.message || "Failed to load data");
      } finally {
        if (active) setLoading(false);
      }
    }
    run();
    return () => {
      active = false;
    };
  }, []);

  const rows = useMemo(() => {
    try {
      return buildRows(rawData || {}, { siteOverrides });
    } catch (e) {
      console.error("[useDynastyData] buildRows crashed:", e);
      return [];
    }
    // Recompute whenever the user's site override map changes so
    // toggling a source or moving a weight slider immediately
    // re-blends the rankings.
  }, [rawData, siteOverrides]);
  const siteKeys = useMemo(() => {
    try {
      return getSiteKeys(rawData || {});
    } catch (e) {
      console.error("[useDynastyData] getSiteKeys crashed:", e);
      return [];
    }
  }, [rawData]);

  return {
    loading,
    error,
    source,
    rawData,
    rows,
    siteKeys,
  };
}

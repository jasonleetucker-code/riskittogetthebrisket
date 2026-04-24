"use client";

import { useEffect, useMemo, useState } from "react";
import { buildRows, fetchDynastyData, getSiteKeys } from "@/lib/dynasty-data";
import { useSettings } from "@/components/useSettings";

export function useDynastyData() {
  // Read user-level source overrides from settings so per-source
  // toggles and weight sliders actually affect the rendered board.
  // When the user has customized anything (including a non-default
  // TE premium multiplier), ``fetchDynastyData`` routes through the
  // backend override endpoint (``POST
  // /api/rankings/overrides?view=delta``) which re-runs the canonical
  // ranking pipeline in ``src/api/data_contract.py`` with the
  // overrides + tep_multiplier threaded in, then merges the compact
  // delta onto the cached base contract.  ``buildRows`` is a pure
  // materializer that reads the already-canonical rows off the
  // merged contract; there is no client-side recompute and no
  // frontend TEP multiplication either.
  const { settings } = useSettings();
  const siteOverrides = settings?.siteWeights || null;
  // tepMultiplier: null means "auto from league" (derive on backend
  // from Sleeper's bonus_rec_te).  A finite number means the user
  // dragged the slider and wants that exact override.  Coercing null
  // → 1.0 here would defeat the derivation path entirely, so we
  // preserve the sentinel and let ``fetchDynastyData`` route
  // accordingly (absent body key → backend derives).
  const rawTep = settings?.tepMultiplier;
  const tepMultiplier =
    rawTep === null || rawTep === undefined
      ? null
      : Number.isFinite(Number(rawTep))
        ? Number(rawTep)
        : null;
  // Serialize the override map so the effect's dependency array
  // fires on semantic changes, not reference churn, without forcing
  // callers to memoize on their side.  The tepMultiplier is part of
  // the cache key so a slider change re-fetches the delta without
  // bundling a stale base blend.
  const siteOverridesKey = useMemo(
    () => (siteOverrides ? JSON.stringify(siteOverrides) : ""),
    [siteOverrides],
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [source, setSource] = useState("");
  const [rawData, setRawData] = useState(null);
  // Bumped when the active league changes so the fetch effect below
  // re-fires.  Today's endpoints don't read leagueId (Phase 1 of the
  // multi-league migration adds that); including the bump in the
  // effect deps means the plumbing is ready the moment the endpoint
  // starts routing by league.
  const [leagueRefreshKey, setLeagueRefreshKey] = useState(0);

  useEffect(() => {
    function onLeagueChanged() {
      setLeagueRefreshKey((v) => v + 1);
    }
    if (typeof window === "undefined") return undefined;
    window.addEventListener("league:changed", onLeagueChanged);
    return () => window.removeEventListener("league:changed", onLeagueChanged);
  }, []);

  useEffect(() => {
    let active = true;
    async function run() {
      try {
        setLoading(true);
        setError("");
        const payload = await fetchDynastyData({
          siteOverrides,
          tepMultiplier,
        });
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [siteOverridesKey, tepMultiplier, leagueRefreshKey]);

  const rows = useMemo(() => {
    try {
      return buildRows(rawData || {});
    } catch (e) {
      console.error("[useDynastyData] buildRows crashed:", e);
      return [];
    }
    // ``buildRows`` is a pure materializer — override effects are
    // already baked into ``rawData`` by ``fetchDynastyData`` above.
  }, [rawData]);
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

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
    function bump() {
      setLeagueRefreshKey((v) => v + 1);
    }
    if (typeof window === "undefined") return undefined;
    // ``auth:changed`` fires from ``useAuth.onLoginSuccess`` so a
    // post-401 sign-in immediately re-fires the data fetch instead of
    // leaving the page stuck on the cached "Sign-in required" error.
    window.addEventListener("league:changed", bump);
    window.addEventListener("auth:changed", bump);
    return () => {
      window.removeEventListener("league:changed", bump);
      window.removeEventListener("auth:changed", bump);
    };
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
        const message = err?.message || "Failed to load data";
        // A 401 here means the server-side session is gone (cookie
        // expired, deploy invalidated, allowlist rotated).  The
        // recovery is targeted at the original stuck-state bug:
        // useAuth's sessionStorage cache says "signed-in" while
        // every fetch 401s.  Only redirect when we have that cache
        // flag set — otherwise we'd bounce unauthenticated visitors
        // off PUBLIC_ROUTES (``/``, ``/draft-capital``, ``/trades``)
        // where ``useDynastyData`` is hydrated but auth isn't
        // required.  Also skip the redirect on /login itself to
        // avoid a self-redirect loop on the login form.
        if (typeof window !== "undefined" && /\b401\b/.test(message)) {
          let hadAuthCache = false;
          try {
            hadAuthCache =
              window.sessionStorage.getItem("next_auth_checked_v1") === "true";
            window.sessionStorage.removeItem("next_auth_checked_v1");
          } catch {
            // sessionStorage can throw in private mode — ignore.
          }
          const path = window.location.pathname || "";
          const onLogin = path === "/login" || path.startsWith("/login/");
          if (hadAuthCache && !onLogin) {
            const next = encodeURIComponent(path + window.location.search);
            window.location.replace(`/login?next=${next}`);
            return;
          }
        }
        setError(message);
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

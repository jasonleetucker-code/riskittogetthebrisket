"use client";

import { useEffect, useMemo, useState } from "react";
import {
  buildRows,
  fetchDynastyData,
  getSiteKeys,
  prefetchBaseContract,
} from "@/lib/dynasty-data";
import { useSettings } from "@/components/useSettings";
import {
  classifyContractFailure,
  classifyContractPayload,
  shouldRedirectToLogin,
} from "@/lib/contract-failure";

// Shared materialization cache: the hook is mounted by AppShell AND by
// the page component, and after the fetch-layer dedup both instances
// hold the SAME contract object — but each still paid its own
// ``buildRows`` pass (~1,100 row objects + a sort, twice per page).
// Keyed by contract object identity; consumers already treat rows as
// immutable (the "pure materializer" rule — pages sort/filter copies),
// so sharing one array is safe.  WeakMap so a replaced contract frees
// its rows with it.
const _rowsByContract = new WeakMap();

function buildRowsShared(rawData) {
  if (!rawData || typeof rawData !== "object") return buildRows(rawData || {});
  const hit = _rowsByContract.get(rawData);
  if (hit) return hit;
  const rows = buildRows(rawData);
  _rowsByContract.set(rawData, rows);
  return rows;
}

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
  const { settings, hydrated: settingsHydrated } = useSettings();
  const siteOverrides = settings?.siteWeights || null;
  // Valuation lens. "market" (the default) is today's board; changing
  // it refetches, because the overlay is a separate league-scoped GET.
  const valuationMode = settings?.valuationMode || "market";
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
  const rawTepNative = settings?.tepNativeMultiplier;
  const tepNativeMultiplier =
    rawTepNative === null || rawTepNative === undefined
      ? null
      : Number.isFinite(Number(rawTepNative))
        ? Number(rawTepNative)
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
  // `error` is the message, kept for every existing consumer.  `failure`
  // is the same event as a STATE — kind, code, retryable — so a page can
  // tell "you are signed out" from "the pipeline is still warming up"
  // from "the backend is unreachable" instead of pattern-matching prose.
  // Both are published because eight routes read `error` today and a
  // flag-day rename would be a bigger change than the repair.
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
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

  // Warm the base-contract download immediately on mount.  The base
  // payload does not depend on settings (only the overrides POST
  // does), so there is no reason for the page's largest download to
  // sit behind the settings-hydration gate below — the real fetch
  // joins this in-flight request instead of starting from zero.
  useEffect(() => {
    prefetchBaseContract();
  }, []);

  useEffect(() => {
    let active = true;
    // Do not fetch on the hydration pass.  ``useSettings`` serves
    // SETTINGS_DEFAULTS until hydration completes, so firing here would
    // request the DEFAULT board — market lens, no source overrides, the
    // default TE multiplier — and then immediately re-request the real
    // one, having rendered the wrong numbers in between.  Two round
    // trips, and the first one wins the first paint.  (The BASE
    // contract is settings-independent and is prefetched above; only
    // the overrides POST waits for hydration.)
    //
    // ``loading`` is already true from its initial state, so the page
    // keeps showing its skeleton rather than an empty board; the delay
    // is one commit, not a network round trip.
    if (!settingsHydrated) return undefined;
    async function run() {
      try {
        setLoading(true);
        setError("");
        setFailure(null);
        const payload = await fetchDynastyData({
          siteOverrides,
          tepMultiplier,
          tepNativeMultiplier,
          valuationMode,
        });
        if (!active) return;

        const data = payload?.data || null;
        setRawData(data);
        setSource(String(payload?.source || ""));

        // A payload that ARRIVED can still be unusable, and the two ways
        // it can be are different states: nothing came back at all
        // (`no_data`) versus a well-formed contract with an empty board
        // (`empty` — usually a backend that has not finished its first
        // scrape, which resolves on its own and is not a fault to report
        // as one).
        const payloadFailure = classifyContractPayload(data);
        if (payloadFailure) {
          setFailure(payloadFailure);
          setError(payloadFailure.message);
        }
      } catch (err) {
        if (!active) return;
        // The status now travels ON the error (lib/dynasty-data.js), so
        // this no longer has to read it back out of the message with a
        // regex — which could not tell a 503 from a 500 from a timeout,
        // and would have matched a player named "401" in the body.
        const classified = classifyContractFailure(err?.status ?? null, err?.body ?? null);

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
        if (typeof window !== "undefined" && classified.kind === "auth") {
          let hadAuthCache = false;
          try {
            hadAuthCache =
              window.sessionStorage.getItem("next_auth_checked_v1") === "true";
            window.sessionStorage.removeItem("next_auth_checked_v1");
          } catch {
            // sessionStorage can throw in private mode — ignore.
          }
          if (
            shouldRedirectToLogin(classified, {
              hadAuthCache,
              pathname: window.location.pathname || "",
            })
          ) {
            const next = encodeURIComponent(
              (window.location.pathname || "") + window.location.search,
            );
            window.location.replace(`/login?next=${next}`);
            return;
          }
        }
        setFailure(classified);
        // The message stays what it always was for anything unclassified,
        // so a consumer still reading `error` is never handed less than
        // it had.
        setError(classified.message || err?.message || "Failed to load data");
      } finally {
        if (active) setLoading(false);
      }
    }
    run();
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    settingsHydrated,
    siteOverridesKey,
    tepMultiplier,
    tepNativeMultiplier,
    valuationMode,
    leagueRefreshKey,
    reloadKey,
  ]);

  const rows = useMemo(() => {
    try {
      return buildRowsShared(rawData);
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
    // The classified failure: { kind, code, message, retryable } or null.
    failure,
    source,
    rawData,
    rows,
    siteKeys,
    // A retry the UI can offer. `ErrorState` has had a `retry` prop all
    // along and no route could use it, because nothing here returned one.
    retry: () => setReloadKey((n) => n + 1),
  };
}

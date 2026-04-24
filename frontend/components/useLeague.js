"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useUserState } from "@/components/useUserState";
import { invalidateTerminalCache } from "@/components/useTerminal";
import { _resetBaseContractCache } from "@/lib/dynasty-data";

/**
 * useLeague — which dynasty league is the signed-in user looking at?
 *
 * Composes two sources:
 *
 *   1. ``/api/leagues`` — the registry-backed list of available
 *      leagues + the site-wide default key.  Fetched once per page
 *      load (module-level cache); the registry is immutable at
 *      runtime on the server, so a stale cache is fine.
 *
 *   2. ``useUserState().state.activeLeagueKey`` — the user's saved
 *      preference.  Server-backed via ``/api/user/state`` when
 *      authenticated, localStorage-mirrored for anon users.  Writing
 *      via ``setLeague`` goes through the same hook so it survives
 *      device switches.
 *
 * Resolution order for "which league do I show this user?":
 *
 *   a. ``userState.activeLeagueKey`` if it names an active league
 *   b. registry ``userDefaultKey`` (server resolves from
 *      ``defaultTeamMap[username]``) if present
 *   c. registry ``defaultKey``
 *   d. first active league
 *   e. null (nothing configured — fresh dev box)
 *
 * Returns ``null``-tolerant state so the hook can render even while
 * the leagues endpoint is still in flight.  Callers should read
 * ``loading`` and gate side-effects until it flips false.
 */

const LOCAL_KEY = "next_active_league_v1";

// Module-level cache for /api/leagues.  Same 30s TTL pattern as
// useTerminal — one request per tab rather than per-hook-instance.
let _leaguesCache = null; // { result, expires }
let _leaguesInflight = null;
const LEAGUES_TTL_MS = 60_000;

async function fetchLeagues() {
  const now = Date.now();
  if (_leaguesCache && _leaguesCache.expires > now) return _leaguesCache.result;
  if (_leaguesInflight) return _leaguesInflight;
  _leaguesInflight = fetch("/api/leagues", {
    credentials: "same-origin",
    headers: { "Cache-Control": "no-store" },
  })
    .then(async (res) => {
      if (!res.ok) throw new Error(`leagues ${res.status}`);
      const data = await res.json();
      _leaguesCache = { result: data, expires: Date.now() + LEAGUES_TTL_MS };
      _leaguesInflight = null;
      return data;
    })
    .catch((err) => {
      _leaguesInflight = null;
      throw err;
    });
  return _leaguesInflight;
}

export function invalidateLeaguesCache() {
  _leaguesCache = null;
  _leaguesInflight = null;
}

function readLocalActiveKey() {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem(LOCAL_KEY) || "";
  } catch {
    return "";
  }
}

function writeLocalActiveKey(key) {
  if (typeof window === "undefined") return;
  try {
    if (key) localStorage.setItem(LOCAL_KEY, String(key));
    else localStorage.removeItem(LOCAL_KEY);
  } catch {
    /* quota: ignore */
  }
}

/**
 * Primary hook.
 *
 * Returns:
 *   leagues:            array of active LeagueConfigDto objects
 *   selectedLeague:     the currently-active LeagueConfigDto or null
 *   selectedLeagueKey:  current key (string) or ""
 *   defaultLeagueKey:   registry default (used when user has no pref)
 *   setLeague(key):     persist + broadcast a new selection
 *   loading:            true while /api/leagues is in flight
 *   error:              fetch error message or null
 *   serverBacked:       true iff the user state is server-backed
 */
export function useLeague() {
  const { state: userState, serverBacked, setNotifications } = useUserState();
  // ^ setNotifications isn't used — we import it defensively so any
  // future refactor that rolls activeLeague into setNotifications-
  // style API surfaces in the hook still works.  Strictly unused
  // today but harmless; hook return shape is what matters.
  void setNotifications;

  const [leaguesPayload, setLeaguesPayload] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [localKey, setLocalKey] = useState("");
  const mounted = useRef(true);

  // Initial localStorage read (client-only; SSR returns "").
  useEffect(() => {
    setLocalKey(readLocalActiveKey());
  }, []);

  // Fetch the registry's league list.  Single-flighted via the
  // module cache — many hook instances share one request.
  useEffect(() => {
    mounted.current = true;
    fetchLeagues()
      .then((payload) => {
        if (!mounted.current) return;
        setLeaguesPayload(payload);
        setError(null);
      })
      .catch((err) => {
        if (!mounted.current) return;
        setError(err?.message || "leagues_fetch_failed");
      })
      .finally(() => {
        if (mounted.current) setLoading(false);
      });
    return () => {
      mounted.current = false;
    };
  }, []);

  const leagues = useMemo(
    () => (Array.isArray(leaguesPayload?.leagues) ? leaguesPayload.leagues : []),
    [leaguesPayload],
  );
  const defaultLeagueKey = leaguesPayload?.defaultKey || "";
  const userDefaultKey = leaguesPayload?.userDefaultKey || "";

  // Resolve the selected key.  ``localKey`` is FIRST because it's
  // the optimistic value written synchronously on every setLeague()
  // call — it's the "user just clicked the switcher" signal.  If
  // we deferred to ``userState.activeLeagueKey``, the switcher
  // would appear to do nothing until the 30s useUserState cache
  // TTL expires + a refetch brings back the server's copy.  Since
  // setLeague also PUTs to /api/user/state, the two sources
  // converge on the next refetch regardless.
  const selectedLeagueKey = useMemo(() => {
    const keysActive = new Set(leagues.map((l) => l.key));
    const prefs = [
      localKey,
      userState?.activeLeagueKey || "",
      userDefaultKey,
      defaultLeagueKey,
      leagues[0]?.key || "",
    ];
    for (const candidate of prefs) {
      if (candidate && keysActive.has(candidate)) return candidate;
    }
    return "";
  }, [
    userState?.activeLeagueKey,
    localKey,
    userDefaultKey,
    defaultLeagueKey,
    leagues,
  ]);

  const selectedLeague = useMemo(
    () => leagues.find((l) => l.key === selectedLeagueKey) || null,
    [leagues, selectedLeagueKey],
  );

  const setLeague = useCallback(
    async (nextKey) => {
      const clean = String(nextKey || "").trim();
      if (!clean) return;
      // Local + storage fallback fires immediately so the UI reflects
      // the change before the network round-trip.  For authenticated
      // users we also hit /api/user/state to persist across devices.
      writeLocalActiveKey(clean);
      setLocalKey(clean);
      if (serverBacked) {
        try {
          await fetch("/api/user/state", {
            method: "PUT",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ activeLeagueKey: clean }),
          });
        } catch {
          /* network error — local state still wins */
        }
      }
      // Purge in-flight caches so league-scoped hooks re-fetch on
      // next render.  Today's endpoints don't actually read leagueId
      // (that's Phase 1 of the multi-league migration), so this is
      // currently a no-op on the wire — but the plumbing lands now
      // so the moment endpoints start routing by leagueId, the
      // switcher will trigger the right refreshes without another
      // frontend change.
      try {
        invalidateTerminalCache();
      } catch { /* hook not mounted yet — safe to ignore */ }
      try {
        _resetBaseContractCache();
      } catch { /* dynasty-data module not initialized — ignore */ }

      // Tell every other ``useUserState`` consumer that state changed.
      // The simplest signal is a storage event; since we already wrote
      // localStorage above, fire a synthetic event for same-tab
      // subscribers (native 'storage' only fires cross-tab).
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("league:changed", { detail: { key: clean } }));
      }
    },
    [serverBacked],
  );

  // Cross-component sync within a tab: when setLeague fires from one
  // hook instance, other instances re-read local state.  (Across-tab
  // sync comes for free via the browser's 'storage' event.)
  useEffect(() => {
    function onLeagueChange(ev) {
      if (ev?.detail?.key) setLocalKey(ev.detail.key);
    }
    function onStorage(ev) {
      if (ev?.key === LOCAL_KEY) setLocalKey(ev.newValue || "");
    }
    if (typeof window === "undefined") return undefined;
    window.addEventListener("league:changed", onLeagueChange);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("league:changed", onLeagueChange);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  return {
    leagues,
    selectedLeague,
    selectedLeagueKey,
    defaultLeagueKey,
    userDefaultKey,
    setLeague,
    loading,
    error,
    serverBacked,
  };
}

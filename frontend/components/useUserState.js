"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * useUserState — durable per-user state hydrated from the backend
 * ``/api/user/state`` endpoint.
 *
 * What lives here:
 *   - selectedTeam: { ownerId, name }
 *   - watchlist:    string[] of player names
 *   - dismissedSignals: { [signalKey]: expiresAtEpochMs }
 *
 * Why this exists:
 *   Before this hook, all user-scoped state lived in ``localStorage``.
 *   That works on one device but:
 *     * doesn't sync phone ↔ desktop
 *     * loses all preferences when the browser is cleared
 *     * keys by team *name* → a Sleeper league rename wipes it out
 *
 *   This hook hydrates from the server, falls back to a localStorage
 *   cache while the fetch is in flight (so the UI doesn't flash
 *   defaults on reload), and gracefully degrades to localStorage-only
 *   when the user is unauthenticated or the backend is unreachable.
 *
 * Fallback strategy:
 *   ``/api/user/state`` is auth-gated.  Anonymous requests get 401 —
 *   the hook silently falls back to reading/writing a local-only
 *   mirror at ``LOCAL_STATE_KEY``.  Authenticated users get the
 *   server blob; we mirror it to localStorage so the next reload
 *   hydrates instantly, then reconciles.  Writes go to both (server
 *   for durability, local for offline resilience).
 */

const LOCAL_STATE_KEY = "next_user_state_v1";

const DEFAULT_STATE = Object.freeze({
  selectedTeam: { ownerId: "", name: "" },
  selectedTeamTouched: false,
  watchlist: [],
  dismissedSignals: {},
});

function readLocal() {
  if (typeof window === "undefined") return { ...DEFAULT_STATE };
  try {
    const raw = localStorage.getItem(LOCAL_STATE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        ...DEFAULT_STATE,
        ...parsed,
        selectedTeam: {
          ownerId: parsed?.selectedTeam?.ownerId || "",
          name: parsed?.selectedTeam?.name || "",
        },
        watchlist: Array.isArray(parsed?.watchlist) ? parsed.watchlist : [],
        dismissedSignals:
          parsed?.dismissedSignals && typeof parsed.dismissedSignals === "object"
            ? parsed.dismissedSignals
            : {},
      };
    }
  } catch {
    /* ignore */
  }
  return { ...DEFAULT_STATE };
}

function writeLocal(state) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(LOCAL_STATE_KEY, JSON.stringify(state));
  } catch {
    /* quota: ignore */
  }
}

function pruneExpiredDismissals(dismissed) {
  if (!dismissed || typeof dismissed !== "object") return {};
  const now = Date.now();
  const out = {};
  for (const [k, v] of Object.entries(dismissed)) {
    const ts = Number(v);
    if (Number.isFinite(ts) && ts > now) out[k] = ts;
  }
  return out;
}

/**
 * Single-flight server fetch.  Multiple components calling this in
 * parallel on mount all share one request.
 */
let inflight = null;
let cache = null; // { result, expires }
const CACHE_TTL_MS = 30_000;

async function fetchServerState() {
  const now = Date.now();
  if (cache && cache.expires > now) return cache.result;
  if (inflight) return inflight;
  inflight = fetch("/api/user/state", {
    credentials: "same-origin",
    headers: { "Cache-Control": "no-store" },
  })
    .then(async (res) => {
      if (res.status === 401) {
        cache = { result: null, expires: Date.now() + CACHE_TTL_MS };
        inflight = null;
        return null;
      }
      if (!res.ok) throw new Error(`user/state ${res.status}`);
      const body = await res.json();
      const result = body?.state || {};
      cache = { result, expires: Date.now() + CACHE_TTL_MS };
      inflight = null;
      return result;
    })
    .catch((err) => {
      inflight = null;
      throw err;
    });
  return inflight;
}

async function writeServerState(patch) {
  try {
    const res = await fetch("/api/user/state", {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (res.status === 401) return null; // unauthenticated — local-only
    if (!res.ok) return null;
    const body = await res.json();
    if (body?.state) {
      cache = { result: body.state, expires: Date.now() + CACHE_TTL_MS };
    }
    return body?.state || null;
  } catch {
    return null;
  }
}

// Read the active league key from localStorage — same key
// ``useLeague`` writes on every switcher change.  Can't import
// ``useLeague`` here because this module is imported BY
// ``useLeague`` (cycle).  localStorage is the cycle-safe bridge.
const LEAGUE_LOCAL_KEY = "next_active_league_v1";
function _readActiveLeagueKey() {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem(LEAGUE_LOCAL_KEY) || "";
  } catch {
    return "";
  }
}

async function dismissSignalOnServer(signalKey, ttlMs, opts) {
  try {
    const payload = { signalKey, ttlMs };
    if (opts?.aliasSleeperId) payload.aliasSleeperId = opts.aliasSleeperId;
    if (opts?.aliasDisplayName) payload.aliasDisplayName = opts.aliasDisplayName;
    // Scope the dismissal to the active league so flipping a SELL
    // off on league A doesn't silence the same player's alert on
    // league B.  Backend falls through to legacy flat storage when
    // leagueKey is absent or invalid.
    const leagueKey = _readActiveLeagueKey();
    if (leagueKey) payload.leagueKey = leagueKey;
    const res = await fetch("/api/user/signals/dismiss", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) return null;
    const body = await res.json();
    if (body?.state) {
      cache = { result: body.state, expires: Date.now() + CACHE_TTL_MS };
    }
    return body?.state || null;
  } catch {
    return null;
  }
}

async function restoreSignalOnServer(signalKey) {
  try {
    const payload = { signalKey };
    const leagueKey = _readActiveLeagueKey();
    if (leagueKey) payload.leagueKey = leagueKey;
    const res = await fetch("/api/user/signals/restore", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) return null;
    const body = await res.json();
    if (body?.state) {
      cache = { result: body.state, expires: Date.now() + CACHE_TTL_MS };
    }
    return body?.state || null;
  } catch {
    return null;
  }
}

// Listeners for cross-component sync within a tab.
const subscribers = new Set();
let currentState = null;

function notify(next) {
  currentState = next;
  for (const cb of subscribers) cb();
}

/**
 * Primary hook.
 *
 * Returns:
 *   state:            current user state blob (never null)
 *   loading:          initial hydration in progress
 *   serverBacked:     true if state came from the server (false for
 *                     anon users whose state lives only in localStorage)
 *   setSelectedTeam:  (ownerId, name) => void
 *   clearSelectedTeam:() => void
 *   toggleWatchlist:  (name) => void
 *   dismissSignal:    (signalKey, ttlMs?) => void
 *   restoreSignal:    (signalKey) => void
 */
export function useUserState() {
  const [state, setState] = useState(() => currentState || readLocal());
  const [loading, setLoading] = useState(() => currentState == null);
  const [serverBacked, setServerBacked] = useState(false);
  const mounted = useRef(true);

  // Subscribe to cross-component updates.
  useEffect(() => {
    const cb = () => {
      if (mounted.current && currentState) setState(currentState);
    };
    subscribers.add(cb);
    return () => {
      subscribers.delete(cb);
    };
  }, []);

  const [authBump, setAuthBump] = useState(0);
  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const onAuth = () => setAuthBump((v) => v + 1);
    window.addEventListener("auth:changed", onAuth);
    return () => window.removeEventListener("auth:changed", onAuth);
  }, []);

  useEffect(() => {
    mounted.current = true;
    setLoading(true);
    fetchServerState()
      .then((server) => {
        if (!mounted.current) return;
        if (server) {
          const merged = {
            ...DEFAULT_STATE,
            ...server,
            selectedTeam: {
              ownerId: server.selectedTeam?.ownerId || "",
              name: server.selectedTeam?.name || "",
            },
            watchlist: Array.isArray(server.watchlist) ? server.watchlist : [],
            dismissedSignals: pruneExpiredDismissals(server.dismissedSignals || {}),
            selectedTeamTouched: !!(server.selectedTeam?.ownerId || server.selectedTeam?.name),
          };
          writeLocal(merged);
          notify(merged);
          setState(merged);
          setServerBacked(true);
        } else {
          // Anon or server unavailable — stick with local mirror.
          const local = readLocal();
          notify(local);
          setState(local);
          setServerBacked(false);
        }
      })
      .catch(() => {
        const local = readLocal();
        notify(local);
        setState(local);
        setServerBacked(false);
      })
      .finally(() => {
        if (mounted.current) setLoading(false);
      });
    return () => {
      mounted.current = false;
    };
  }, [authBump]);

  // Mutators — write-through to local + server.
  const persist = useCallback(async (nextState, serverPatch) => {
    writeLocal(nextState);
    notify(nextState);
    if (serverPatch && serverBacked !== false) {
      // Intentionally fire-and-forget — UI already reflects the change.
      writeServerState(serverPatch).catch(() => {});
    }
  }, [serverBacked]);

  const setSelectedTeam = useCallback(
    (ownerId, name) => {
      const selectedTeam = {
        ownerId: String(ownerId || ""),
        name: String(name || ""),
      };
      const next = { ...(currentState || state), selectedTeam, selectedTeamTouched: true };
      persist(next, { selectedTeam });
    },
    [persist, state],
  );

  const clearSelectedTeam = useCallback(() => {
    const next = {
      ...(currentState || state),
      selectedTeam: { ownerId: "", name: "" },
      selectedTeamTouched: true,
    };
    persist(next, { selectedTeam: { ownerId: "", name: "" } });
  }, [persist, state]);

  const toggleWatchlist = useCallback(
    (name) => {
      const clean = String(name || "").trim();
      if (!clean) return;
      const list = Array.isArray((currentState || state).watchlist)
        ? [...(currentState || state).watchlist]
        : [];
      const idx = list.findIndex((x) => String(x).toLowerCase() === clean.toLowerCase());
      if (idx >= 0) list.splice(idx, 1);
      else list.push(clean);
      const next = { ...(currentState || state), watchlist: list };
      persist(next, { watchlist: list });
    },
    [persist, state],
  );

  // Patch the notification fields (email + enabled toggle).  Each
  // field is optional so callers can flip one without clobbering the
  // other; a null / empty-string email clears the stored address.
  const setNotifications = useCallback(
    ({ email, enabled } = {}) => {
      const curr = currentState || state;
      const next = { ...curr };
      const patch = {};
      if (email !== undefined) {
        const clean = email === null ? null : String(email).trim() || null;
        next.notificationsEmail = clean;
        patch.notificationsEmail = clean;
      }
      if (enabled !== undefined) {
        next.notificationsEnabled = !!enabled;
        patch.notificationsEnabled = !!enabled;
      }
      if (Object.keys(patch).length === 0) return;
      persist(next, patch);
    },
    [persist, state],
  );

  const dismissSignal = useCallback(
    (signalKey, ttlMs, opts) => {
      if (!signalKey) return;
      const ttl = Number.isFinite(Number(ttlMs)) ? Number(ttlMs) : 7 * 24 * 3600 * 1000;
      const expiresAt = Date.now() + ttl;
      const curr = currentState || state;
      const dismissed = {
        ...(curr.dismissedSignals || {}),
        [String(signalKey)]: expiresAt,
      };
      // Record the alias mapping locally too so a rename-on-login
      // has the data available for the alias-resolution pass even
      // before the server round-trips.
      let aliases = { ...(curr.dismissalAliases || {}) };
      if (opts?.aliasDisplayName && opts?.aliasSleeperId) {
        aliases[String(opts.aliasDisplayName)] = String(opts.aliasSleeperId);
      }
      const next = { ...curr, dismissedSignals: dismissed, dismissalAliases: aliases };
      writeLocal(next);
      notify(next);
      if (serverBacked) {
        dismissSignalOnServer(String(signalKey), ttl, opts).catch(() => {});
      }
    },
    [serverBacked, state],
  );

  const restoreSignal = useCallback(
    (signalKey) => {
      if (!signalKey) return;
      const dismissed = { ...((currentState || state).dismissedSignals || {}) };
      delete dismissed[String(signalKey)];
      const next = { ...(currentState || state), dismissedSignals: dismissed };
      writeLocal(next);
      notify(next);
      if (serverBacked) {
        restoreSignalOnServer(String(signalKey)).catch(() => {});
      }
    },
    [serverBacked, state],
  );

  // Auto-prune expired dismissals every minute so the UI matches
  // the backend.  Cheap: it's a local dict scan.
  useEffect(() => {
    const id = setInterval(() => {
      const curr = currentState || state;
      const pruned = pruneExpiredDismissals(curr?.dismissedSignals || {});
      const existing = curr?.dismissedSignals || {};
      if (Object.keys(existing).length === Object.keys(pruned).length) return;
      const next = { ...curr, dismissedSignals: pruned };
      writeLocal(next);
      notify(next);
    }, 60_000);
    return () => clearInterval(id);
  }, [state]);

  return {
    state,
    loading,
    serverBacked,
    setSelectedTeam,
    clearSelectedTeam,
    toggleWatchlist,
    setNotifications,
    dismissSignal,
    restoreSignal,
  };
}

/**
 * Force-refresh the server state cache — useful after login, so
 * a fresh session hydrates immediately rather than serving the
 * anonymous default for up to 30s.
 */
export function invalidateUserState() {
  cache = null;
  inflight = null;
}

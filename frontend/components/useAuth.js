"use client";

import { useCallback, useEffect, useState } from "react";

const AUTH_CHECK_KEY = "next_auth_checked_v1";

/**
 * useAuth — lightweight auth state hook.
 * Checks /api/auth/status on mount, caches result for the session.
 * Provides login/logout helpers.
 */
export function useAuth() {
  const [authenticated, setAuthenticated] = useState(null); // null = checking
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    let active = true;
    // sessionStorage can throw synchronously in strict privacy modes
    // and locked-down WebViews — wrap every access so a thrown read
    // can't abort the effect before ``setChecking(false)`` runs.
    function readAuthCache() {
      try {
        return sessionStorage.getItem(AUTH_CHECK_KEY) === "true";
      } catch {
        return false;
      }
    }
    function writeAuthCache(authed) {
      try {
        if (authed) sessionStorage.setItem(AUTH_CHECK_KEY, "true");
        else sessionStorage.removeItem(AUTH_CHECK_KEY);
      } catch {
        // sessionStorage unavailable — accept the in-memory state.
      }
    }

    async function check() {
      // Stale-while-revalidate: paint optimistically from the cached
      // flag for fast first render, but ALWAYS re-verify against the
      // backend.  A stuck "authenticated=true" cache after the cookie
      // is gone is the entire reason this hook used to wedge users on
      // the dashboard with a 401-on-every-request loop.
      const cached = readAuthCache();
      if (cached && active) {
        setAuthenticated(true);
        setChecking(false);
      }
      try {
        // Cap the auth check so a hung fetch (slow network, broken
        // proxy, iOS Safari background-tab throttling) can't leave
        // the UI wedged on ``checking=true`` — every consumer that
        // gates UI on the resolved state would otherwise sit on a
        // blank screen until the request finally errors out.
        const ctl = new AbortController();
        const timer = setTimeout(() => ctl.abort(), 5000);
        let res;
        try {
          res = await fetch("/api/auth/status", {
            credentials: "same-origin",
            signal: ctl.signal,
          });
        } finally {
          clearTimeout(timer);
        }
        // /api/auth/status is public and reports unauthenticated
        // users with 200 + {authenticated: false}, so a non-OK status
        // here means a transient backend/proxy failure (5xx, 502
        // during a deploy, nginx timeout).  Keep the optimistic state
        // when we had one (don't sign out a real session on infra
        // blips); otherwise resolve to unauthenticated so callers
        // that treat ``null`` as "still checking" don't wedge.
        if (!res.ok) {
          if (active && !cached) setAuthenticated(false);
          return;
        }
        const data = await res.json();
        const authed = !!data.authenticated;
        if (active) setAuthenticated(authed);
        writeAuthCache(authed);
      } catch {
        // Network failure: keep optimistic state if we had one,
        // otherwise fall to unauthenticated.  Don't clobber the cache
        // on transient errors.
        if (active && !cached) setAuthenticated(false);
      } finally {
        if (active) setChecking(false);
      }
    }
    check();
    return () => { active = false; };
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
    } catch { /* ignore */ }
    sessionStorage.removeItem(AUTH_CHECK_KEY);
    setAuthenticated(false);
    window.location.href = "/";
  }, []);

  const onLoginSuccess = useCallback(() => {
    sessionStorage.setItem(AUTH_CHECK_KEY, "true");
    setAuthenticated(true);
    // Notify data hooks (useDynastyData, useUserState) so any cached
    // 401 error state from before sign-in clears immediately instead
    // of requiring a full page reload.  Listened for in
    // ``useDynastyData`` and ``useUserState``.
    if (typeof window !== "undefined") {
      try {
        window.dispatchEvent(new Event("auth:changed"));
      } catch {
        /* old browsers without Event constructor — ignore */
      }
    }
  }, []);

  return { authenticated, checking, logout, onLoginSuccess };
}

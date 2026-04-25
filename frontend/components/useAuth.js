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
    async function check() {
      // Stale-while-revalidate: paint optimistically from the cached
      // flag for fast first render, but ALWAYS re-verify against the
      // backend.  A stuck "authenticated=true" cache after the cookie
      // is gone is the entire reason this hook used to wedge users on
      // the dashboard with a 401-on-every-request loop.
      const cached = sessionStorage.getItem(AUTH_CHECK_KEY);
      if (cached === "true" && active) {
        setAuthenticated(true);
        setChecking(false);
      }
      try {
        const res = await fetch("/api/auth/status", { credentials: "same-origin" });
        if (!res.ok) {
          sessionStorage.removeItem(AUTH_CHECK_KEY);
          if (active) setAuthenticated(false);
          return;
        }
        const data = await res.json();
        const authed = !!data.authenticated;
        if (active) setAuthenticated(authed);
        if (authed) sessionStorage.setItem(AUTH_CHECK_KEY, "true");
        else sessionStorage.removeItem(AUTH_CHECK_KEY);
      } catch {
        // Network failure: keep optimistic state if we had one,
        // otherwise fall to unauthenticated.  Don't clobber the cache
        // on transient errors.
        if (active && cached !== "true") setAuthenticated(false);
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
  }, []);

  return { authenticated, checking, logout, onLoginSuccess };
}

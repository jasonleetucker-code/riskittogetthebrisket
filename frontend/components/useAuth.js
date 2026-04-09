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
      try {
        // Check sessionStorage first for fast re-renders
        const cached = sessionStorage.getItem(AUTH_CHECK_KEY);
        if (cached === "true") {
          if (active) {
            setAuthenticated(true);
            setChecking(false);
          }
          return;
        }

        const res = await fetch("/api/auth/status", { credentials: "same-origin" });
        if (!res.ok) {
          if (active) setAuthenticated(false);
          return;
        }
        const data = await res.json();
        const authed = !!data.authenticated;
        if (active) {
          setAuthenticated(authed);
          if (authed) sessionStorage.setItem(AUTH_CHECK_KEY, "true");
        }
      } catch {
        if (active) setAuthenticated(false);
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

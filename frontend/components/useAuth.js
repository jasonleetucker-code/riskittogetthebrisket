"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const AUTH_CHECK_KEY = "next_auth_checked_v1";

// Cap on a single status probe.  Exists so a hung fetch (slow network,
// broken proxy, iOS Safari background-tab throttling) can't leave the
// UI wedged on ``checking = true`` forever.
const PROBE_TIMEOUT_MS = 5000;

// Backoff between probes while the answer is UNKNOWN.  The last value
// repeats for as long as the page lives, so a session that was
// unreachable at mount still recovers on its own instead of requiring
// the user to reload.
const RETRY_BACKOFF_MS = [1000, 2000, 4000, 8000, 30000];

/**
 * useAuth — lightweight auth state hook.
 *
 * ``authenticated`` is deliberately THREE-valued, and the distinction
 * is the whole point of this hook:
 *
 *   true   — the backend said so.
 *   false  — the backend said so.  A genuine signed-out user.
 *   null   — we don't know yet: still probing, or every probe so far
 *            failed/timed out.
 *
 * The bug this replaced collapsed the third case into ``false``: one
 * slow moment on ``/api/auth/status`` (5s cap, no retry) resolved a
 * perfectly valid session to "logged out" for the entire life of the
 * page — no nav, no search, no team switcher — until the user
 * manually reloaded.  A transient timeout must never be
 * indistinguishable from a real sign-out, so a failed probe now leaves
 * the state UNKNOWN and schedules another one.
 *
 * Consumers render ``null`` as neutral chrome (no authed surfaces, but
 * no "Login" affordance either), so an unknown state is quiet rather
 * than actively wrong in either direction.
 */
export function useAuth() {
  const [authenticated, setAuthenticated] = useState(null); // null = unknown
  // Operator flag from /api/auth/status.  Purely a UI affordance: it
  // hides the Ops section of the System menu from users the server
  // would 403 anyway.  Never trusted for access control — every admin
  // endpoint re-checks server-side.
  const [isAdmin, setIsAdmin] = useState(false);
  // Server capability map for flag-gated nav destinations, from the same
  // /api/auth/status probe.  `null` = we have not been told, which the
  // nav model treats as "do not offer" — see nav-model.itemIsOffered.
  // Same posture as isAdmin: a UI affordance, never access control.
  const [features, setFeatures] = useState(null);
  const [checking, setChecking] = useState(true);
  // Exposed so a caller can tell "we never got an answer" apart from
  // "the answer was no" without re-deriving it from authenticated.
  const [authUnknown, setAuthUnknown] = useState(false);
  const attemptRef = useRef(0);

  useEffect(() => {
    let active = true;
    let timer = null;

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

    function scheduleRetry() {
      if (!active) return;
      const i = Math.min(attemptRef.current, RETRY_BACKOFF_MS.length - 1);
      const delay = RETRY_BACKOFF_MS[i];
      attemptRef.current += 1;
      timer = setTimeout(() => {
        probe();
      }, delay);
    }

    /**
     * One probe.  Returns nothing; drives state.
     *
     * Only a 200 is authoritative — ``/api/auth/status`` is public and
     * reports signed-out users as 200 + ``{authenticated: false}``, so
     * any non-OK status is infrastructure (5xx, 502 mid-deploy, nginx
     * timeout), not an answer about this user.
     */
    async function probe() {
      const cached = readAuthCache();
      try {
        const ctl = new AbortController();
        const t = setTimeout(() => ctl.abort(), PROBE_TIMEOUT_MS);
        let res;
        try {
          res = await fetch("/api/auth/status", {
            credentials: "same-origin",
            signal: ctl.signal,
          });
        } finally {
          clearTimeout(t);
        }
        if (!active) return;

        if (!res.ok) {
          // Transient infrastructure failure — NOT an answer.
          markUnknown(cached);
          scheduleRetry();
          return;
        }

        const data = await res.json();
        if (!active) return;
        const authed = !!data.authenticated;
        // Authoritative: stop retrying and commit, in both directions.
        setAuthenticated(authed);
        setIsAdmin(authed && !!data.isAdmin);
        // Only an authoritative answer sets capabilities.  A signed-out
        // response carries none, and a backend too old to send the block
        // leaves this null — both mean "not offered", never "offered".
        setFeatures(authed && data.features ? data.features : null);
        setAuthUnknown(false);
        setChecking(false);
        writeAuthCache(authed);
        attemptRef.current = 0;
      } catch {
        // Abort (our own timeout) or network failure.  Same class as a
        // 5xx: we did not learn anything about this user.
        if (!active) return;
        markUnknown(cached);
        scheduleRetry();
      }
    }

    function markUnknown(cached) {
      // Never wedge on ``checking`` — consumers gate real UI on it.
      setChecking(false);
      setAuthUnknown(true);
      // Stale-while-revalidate: a cached "was signed in" keeps painting
      // optimistically so a blip doesn't tear down the authed shell.
      // Without one we stay null (unknown) rather than claiming false —
      // that claim was the bug.
      if (cached) setAuthenticated(true);
      else setAuthenticated(null);
    }

    // Paint immediately from the cached flag for a fast first render,
    // but ALWAYS re-verify.  A stuck "authenticated=true" cache after
    // the cookie is gone is why this hook used to wedge users on the
    // dashboard in a 401-on-every-request loop.
    if (readAuthCache()) {
      setAuthenticated(true);
      setChecking(false);
    }
    probe();

    // A tab that was backgrounded (or offline) during every retry
    // recovers the moment it comes back, without waiting out the
    // backoff.  Only re-probes while the answer is still unknown.
    function onWake() {
      if (!active) return;
      if (!attemptRef.current) return; // last probe was authoritative
      if (timer) clearTimeout(timer);
      probe();
    }
    if (typeof window !== "undefined") {
      window.addEventListener("focus", onWake);
      window.addEventListener("online", onWake);
    }

    return () => {
      active = false;
      if (timer) clearTimeout(timer);
      if (typeof window !== "undefined") {
        window.removeEventListener("focus", onWake);
        window.removeEventListener("online", onWake);
      }
    };
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
    } catch { /* ignore */ }
    try {
      sessionStorage.removeItem(AUTH_CHECK_KEY);
    } catch { /* sessionStorage unavailable — in-memory state still flips */ }
    setAuthenticated(false);
    setIsAdmin(false);
    setFeatures(null);
    setAuthUnknown(false);
    window.location.href = "/";
  }, []);

  const onLoginSuccess = useCallback(() => {
    try {
      sessionStorage.setItem(AUTH_CHECK_KEY, "true");
    } catch { /* sessionStorage unavailable — in-memory state still flips */ }
    setAuthenticated(true);
    setAuthUnknown(false);
    setChecking(false);
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

  return { authenticated, isAdmin, features, checking, authUnknown, logout, onLoginSuccess };
}

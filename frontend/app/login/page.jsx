"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuthContext } from "@/app/AppShellWrapper";

/**
 * Login page — two sign-in paths:
 *
 * 1. Sleeper username (primary, multi-user) — user types their
 *    Sleeper handle, we look them up via the public Sleeper API.
 *    Session is keyed on their Sleeper user_id so user_kv
 *    (watchlist, dismissals, selectedTeam) partitions per-person.
 *    No password, no account creation; trust-on-first-use for a
 *    league-scoped tool.
 *
 * 2. Admin password (legacy, single-operator) — the hardcoded
 *    ``JASON_LOGIN_USERNAME`` + ``JASON_LOGIN_PASSWORD`` pair the
 *    site used to have as its only sign-in.  Kept for operator
 *    access to scrape controls and for cases where the Sleeper
 *    API is unreachable.
 *
 * Tab between them via the toggle at the top of the card.
 */
export default function LoginPage() {
  const router = useRouter();
  const { onLoginSuccess } = useAuthContext();
  const [mode, setMode] = useState("sleeper"); // "sleeper" | "admin"
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [redirectPath, setRedirectPath] = useState("/rankings");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const next = params.get("next") || "/rankings";
    setRedirectPath(next.startsWith("/") ? next : "/rankings");
  }, []);

  async function handleSleeperSubmit(event) {
    event.preventDefault();
    const trimmedUser = username.trim();
    if (!trimmedUser) {
      setError("Enter your Sleeper username.");
      return;
    }
    setError("");
    setSubmitting(true);
    try {
      const res = await fetch("/api/auth/sleeper-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: trimmedUser, next: redirectPath }),
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        onLoginSuccess?.();
        router.push(data.redirect || redirectPath);
      } else {
        setError(data.error || "Login failed.");
        setSubmitting(false);
      }
    } catch {
      setError("Login request failed. Please try again.");
      setSubmitting(false);
    }
  }

  async function handleAdminSubmit(event) {
    event.preventDefault();
    const trimmedUser = username.trim();
    if (!trimmedUser || !password) {
      setError("Enter both username and password.");
      return;
    }
    setError("");
    setSubmitting(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: trimmedUser,
          password,
          next: redirectPath,
        }),
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        onLoginSuccess?.();
        router.push(data.redirect || redirectPath);
      } else {
        setError(data.error || "Invalid username or password.");
        setSubmitting(false);
      }
    } catch {
      setError("Login request failed. Please try again.");
      setSubmitting(false);
    }
  }

  function switchMode(next) {
    setMode(next);
    setError("");
    setPassword("");
  }

  return (
    <section className="card login-shell">
      <div className="login-panel">
        <span className="badge login-badge">Account</span>
        <h1 style={{ margin: "10px 0 0 0" }}>Sign in</h1>
        <p className="muted" style={{ marginTop: 8 }}>
          Continue to your dynasty rankings and trade workspace.
        </p>

        <div
          role="tablist"
          aria-label="Sign-in method"
          style={{
            display: "flex",
            gap: 6,
            marginTop: 16,
            borderBottom: "1px solid var(--border)",
          }}
        >
          <button
            type="button"
            role="tab"
            aria-selected={mode === "sleeper"}
            className={`login-mode-tab${mode === "sleeper" ? " is-active" : ""}`}
            onClick={() => switchMode("sleeper")}
          >
            Sleeper username
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "admin"}
            className={`login-mode-tab${mode === "admin" ? " is-active" : ""}`}
            onClick={() => switchMode("admin")}
          >
            Admin
          </button>
        </div>

        {mode === "sleeper" ? (
          <form className="login-form" onSubmit={handleSleeperSubmit}>
            <label className="login-label" htmlFor="sleeper-username">
              Sleeper username
            </label>
            <input
              id="sleeper-username"
              className="input login-input"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="e.g. joeschmo"
            />
            <p className="muted" style={{ fontSize: "0.7rem", marginTop: 4, marginBottom: 0 }}>
              We look up your user id on Sleeper and use that to
              find your team in this league.  No password — this is
              a lightweight "who are you" sign-in for league-mates.
            </p>

            {error ? <p className="login-error">{error}</p> : null}

            <button className="button login-button" type="submit" disabled={submitting}>
              {submitting ? "Checking Sleeper…" : "Sign in with Sleeper"}
            </button>
          </form>
        ) : (
          <form className="login-form" onSubmit={handleAdminSubmit}>
            <label className="login-label" htmlFor="admin-username">
              Username
            </label>
            <input
              id="admin-username"
              className="input login-input"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Enter username"
            />

            <label className="login-label" htmlFor="admin-password">
              Password
            </label>
            <input
              id="admin-password"
              className="input login-input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password"
            />

            {error ? <p className="login-error">{error}</p> : null}

            <button className="button login-button" type="submit" disabled={submitting}>
              {submitting ? "Signing in..." : "Sign in"}
            </button>
          </form>
        )}

        <p className="muted" style={{ marginBottom: 0, fontSize: "0.76rem" }}>
          Need help? <Link href="/">Go to Home</Link>
        </p>
      </div>
    </section>
  );
}

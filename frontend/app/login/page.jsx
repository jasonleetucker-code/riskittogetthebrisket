"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuthContext } from "@/app/AppShellWrapper";

/**
 * What to tell the user, given what the server actually said.
 *
 * Split out so the credential answer cannot leak onto a service failure
 * by accident again — the mapping is visible in one place instead of
 * being an `||` fallback at the call site.
 */
function loginErrorMessage(status, data) {
  const stated = data && typeof data === "object" ? data.error : "";
  if (status === 429) {
    return "Too many sign-in attempts. Wait a moment and try again.";
  }
  if (status === 503 || status === 502 || status === 504) {
    return "The sign-in service is unavailable right now. Try again shortly.";
  }
  if (status >= 500) {
    return "The server hit an error signing you in. Try again shortly.";
  }
  if (status === 400 || status === 401 || status === 403) {
    return stated || "Invalid username or password.";
  }
  return stated || `Sign-in failed (HTTP ${status}).`;
}

export default function LoginPage() {
  const router = useRouter();
  const { onLoginSuccess } = useAuthContext();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // Default landing post-login is the Chase Upside home dashboard at "/" —
  // Team Value + Top Movers + Risers/Fallers — which gives a more
  // useful daily-checkin view than the raw rankings table.  Users
  // who deep-linked to a specific page before being bounced to login
  // (``?next=/trade`` etc.) still land back where they intended.
  const [redirectPath, setRedirectPath] = useState("/");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const next = params.get("next") || "/";
    setRedirectPath(next.startsWith("/") ? next : "/");
  }, []);

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
      const data = await res.json().catch(() => null);
      if (res.ok && data?.ok) {
        onLoginSuccess?.();
        router.push(data.redirect || redirectPath);
      } else {
        // "Invalid username or password" is an answer about the
        // CREDENTIALS, and this branch used to give it for every non-ok
        // response — so a rate limit, a backend outage and a 500 all told
        // the user their password was wrong. They then retype a correct
        // password, fail again, and conclude their account is broken.
        //
        // Only 400/401/403 are statements about the credentials. Anything
        // else is a statement about the service, and says so.
        setError(loginErrorMessage(res.status, data));
        setSubmitting(false);
      }
    } catch {
      setError("Could not reach the sign-in service. Check your connection and try again.");
      setSubmitting(false);
    }
  }

  return (
    <section className="card login-shell">
      <div className="login-panel">
        <span className="badge login-badge">Account</span>
        <h1 style={{ margin: "10px 0 0 0" }}>Sign in</h1>
        <p className="muted" style={{ marginTop: 8 }}>
          Continue to your dynasty rankings and trade workspace.
        </p>

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

          {/* role="alert": the failure message was silent to assistive
              tech, so a screen-reader user pressed Sign in and was told
              nothing at all. */}
          {error ? (
            <p className="login-error" role="alert">
              {error}
            </p>
          ) : null}

          <button className="button login-button" type="submit" disabled={submitting}>
            {submitting ? "Signing in..." : "Sign in"}
          </button>
        </form>

        <p className="muted" style={{ marginBottom: 0, fontSize: "0.76rem" }}>
          Need help? <Link href="/">Go to Home</Link>
        </p>
      </div>
    </section>
  );
}

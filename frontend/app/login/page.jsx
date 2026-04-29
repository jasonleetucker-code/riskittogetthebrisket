"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuthContext } from "@/app/AppShellWrapper";

export default function LoginPage() {
  const router = useRouter();
  const { onLoginSuccess } = useAuthContext();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // Default landing post-login is the Brisket Home dashboard at "/" —
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

          {error ? <p className="login-error">{error}</p> : null}

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

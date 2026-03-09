"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const SESSION_KEY = "next_auth_session_v1";

function isValidEmail(value) {
  return /\S+@\S+\.\S+/.test(value);
}

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [redirectPath, setRedirectPath] = useState("/");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const next = params.get("next") || "/";
    setRedirectPath(next.startsWith("/") ? next : "/");
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    const trimmedEmail = email.trim();

    if (!trimmedEmail || !password) {
      setError("Enter both email and password.");
      return;
    }
    if (!isValidEmail(trimmedEmail)) {
      setError("Enter a valid email address.");
      return;
    }
    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }

    setError("");
    setSubmitting(true);

    try {
      localStorage.setItem(
        SESSION_KEY,
        JSON.stringify({
          email: trimmedEmail,
          remember,
          loggedInAt: new Date().toISOString(),
        }),
      );
      router.push(redirectPath);
    } catch {
      setError("Unable to save login session. Please try again.");
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

        <form className="login-form" onSubmit={handleSubmit}>
          <label className="login-label" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            className="input login-input"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
          />

          <label className="login-label" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            className="input login-input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Enter password"
          />

          <label className="login-check">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
            />
            <span>Remember me on this browser</span>
          </label>

          {error ? <p className="login-error">{error}</p> : null}

          <button className="button login-button" type="submit" disabled={submitting}>
            {submitting ? "Signing in..." : "Sign in"}
          </button>
        </form>

        <p className="muted" style={{ marginBottom: 0, fontSize: "0.76rem" }}>
          Demo login only for UI flow. Need an account? <Link href="/">Go to Home</Link>
        </p>
      </div>
    </section>
  );
}

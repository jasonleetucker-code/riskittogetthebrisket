"use client";

import Link from "next/link";
import { useAuthContext } from "@/app/AppShellWrapper";
import TerminalLayout from "@/components/terminal/TerminalLayout";

/**
 * Home page — entry point for the app.
 * Authenticated users see the fantasy-market terminal landing.
 * Unauthenticated users see a landing with League (public) and Login options.
 */

function AuthenticatedHome() {
  return <TerminalLayout />;
}

/**
 * Public landing.
 *
 * This was a title, the line "Choose where you want to go", and two
 * unlabelled buttons — a visitor could not tell what the site was, what
 * lived behind the login, or why the League button was worth pressing.
 * It now says what each side is before asking anyone to choose, which
 * is also the honest place to draw the public/private line: league
 * history and results are open, the valuation and trade tooling is not.
 */
function LandingHome() {
  return (
    <section className="login-shell">
      <div className="login-panel">
        <h1 style={{ margin: "0 0 8px", fontSize: "1.4rem" }}>Chase Upside</h1>
        <p className="muted" style={{ marginBottom: "var(--space-lg)" }}>
          Dynasty fantasy football valuation and trade analysis, plus the full
          public record of our league.
        </p>

        <div
          className="grid-responsive"
          style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}
        >
          <div>
            <Link
              href="/league"
              className="button"
              style={{ display: "block", textAlign: "center", padding: "14px 12px" }}
            >
              League
            </Link>
            <p
              className="muted text-xs"
              style={{ marginTop: 8, lineHeight: 1.45, textAlign: "center" }}
            >
              Open to everyone: champions, records, rivalries, weekly recaps and
              every trade in league history.
            </p>
          </div>
          <div>
            <Link
              href="/login"
              className="button button-primary"
              style={{ display: "block", textAlign: "center", padding: "14px 12px" }}
            >
              Sign in
            </Link>
            <p
              className="muted text-xs"
              style={{ marginTop: 8, lineHeight: 1.45, textAlign: "center" }}
            >
              Members only: player rankings, trade tools, waiver and draft
              analysis.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

export default function HomePage() {
  const { authenticated } = useAuthContext();
  // Render the public landing while ``authenticated`` is still
  // resolving (``null``) instead of returning ``null``.  Returning
  // null here means a stalled auth check (slow network, blocked
  // sessionStorage, etc.) wedges the user on a blank page with no
  // way to recover; the landing page works for every auth state and
  // briefly flashes before the terminal mounts for signed-in users.
  if (authenticated === true) return <AuthenticatedHome />;
  return <LandingHome />;
}

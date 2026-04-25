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

function LandingHome() {
  return (
    <section className="login-shell">
      <div className="login-panel" style={{ textAlign: "center" }}>
        <h1 style={{ margin: "0 0 8px", fontSize: "1.4rem" }}>Risk It To Get The Brisket</h1>
        <p className="muted" style={{ marginBottom: "var(--space-lg)" }}>Choose where you want to go.</p>
        <div className="grid-responsive" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Link href="/league" className="button" style={{ textAlign: "center", padding: "14px 12px" }}>
            League
          </Link>
          <Link href="/login" className="button button-primary" style={{ textAlign: "center", padding: "14px 12px" }}>
            Sign In
          </Link>
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

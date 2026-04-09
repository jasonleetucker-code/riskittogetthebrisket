"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuthContext } from "@/app/AppShellWrapper";

/**
 * Home page — entry point for the app.
 * Authenticated users see a dashboard hub with quick links.
 * Unauthenticated users see a landing with League (public) and Login options.
 */
const DESTINATIONS = [
  { href: "/rankings", label: "Rankings", desc: "Unified player board with multi-source values" },
  { href: "/trade", label: "Trade Calculator", desc: "Evaluate trades with power-weighted analysis" },
  { href: "/edge", label: "Edge Detection", desc: "Find buy-low and sell-high opportunities" },
  { href: "/finder", label: "Trade Finder", desc: "Discover arbitrage trades across your league" },
  { href: "/league", label: "League Hub", desc: "Power rankings, comparisons, draft capital" },
];

function AuthenticatedHome() {
  return (
    <section>
      <div className="card" style={{ marginBottom: "var(--space-md)" }}>
        <h1 className="page-title">Risk It To Get The Brisket</h1>
        <p className="muted text-sm" style={{ marginTop: 4 }}>
          Dynasty trade calculator and league analysis platform.
        </p>
      </div>
      <div className="list">
        {DESTINATIONS.map((d) => (
          <Link key={d.href} href={d.href} className="card" style={{ display: "block" }}>
            <div style={{ fontWeight: 600, fontSize: "0.9rem" }}>{d.label}</div>
            <div className="muted text-xs" style={{ marginTop: 2 }}>{d.desc}</div>
          </Link>
        ))}
      </div>
    </section>
  );
}

function LandingHome() {
  return (
    <section className="login-shell">
      <div className="login-panel" style={{ textAlign: "center" }}>
        <h1 style={{ margin: "0 0 8px", fontSize: "1.4rem" }}>Risk It To Get The Brisket</h1>
        <p className="muted" style={{ marginBottom: "var(--space-lg)" }}>Choose where you want to go.</p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Link href="/draft-capital" className="button" style={{ textAlign: "center", padding: "14px 12px" }}>
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
  const { authenticated, checking } = useAuthContext();

  if (checking) return null;
  if (authenticated) return <AuthenticatedHome />;
  return <LandingHome />;
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuthContext } from "@/app/AppShellWrapper";
import TerminalLayout from "@/components/terminal/TerminalLayout";
import { SkeletonStat, SkeletonTable, SkeletonText } from "@/components/ds/Skeleton";
import styles from "@/components/terminal/terminal.module.css";

/**
 * Home page — entry point for the app.
 * Authenticated users see the fantasy-market terminal landing.
 * Unauthenticated users see a landing with League (public) and Login options.
 */

function AuthenticatedHome() {
  return <TerminalLayout />;
}

/**
 * Neutral shell rendered while ``authenticated`` is still ``null``.
 *
 * This used to render ``LandingHome`` (a ~200px card), which meant
 * EVERY signed-in visit first painted the landing and then swapped in
 * the ~4000px terminal — the single largest layout shift on the site
 * (CLS on ``/`` measured 0.72).  The shell mirrors the terminal's real
 * geometry (command stats row, chart slot, ticker strip, signal rail,
 * 3-column grid) using the CLS-safe skeleton primitives, so the swap
 * to ``TerminalLayout`` lands content into already-reserved space.
 *
 * Signed-OUT visitors briefly see this skeleton before the landing
 * card — the accepted tradeoff (signed-in is the overwhelmingly common
 * state for a private dashboard).  A 4s cap below guarantees a stalled
 * auth probe still lands on the navigable landing page rather than
 * wedging on bones.
 */
function ResolvingHome() {
  return (
    <div className={styles.page} aria-busy="true" aria-label="Loading dashboard">
      <section>
        <SkeletonText lines={2} />
        <div className={styles.commandStats} style={{ marginTop: 12 }}>
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonStat key={i} />
          ))}
        </div>
        <div className={styles.commandChart} style={{ minHeight: 60 }} />
      </section>
      <div style={{ minHeight: 40 }} />
      <div className={styles.railGrid} style={{ minHeight: 150 }} />
      <div className={styles.grid}>
        {Array.from({ length: 3 }).map((_, i) => (
          <div className={styles.col} key={i}>
            <SkeletonTable rows={8} columns={3} />
            <SkeletonTable rows={6} columns={3} />
          </div>
        ))}
      </div>
    </div>
  );
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
  // Fallback for a stalled auth probe (slow network, blocked
  // sessionStorage): after 4s of unresolved ``null``, show the
  // landing page — it works for every auth state and keeps the user
  // navigable instead of wedged on the loading shell.
  const [resolveTimedOut, setResolveTimedOut] = useState(false);
  useEffect(() => {
    if (authenticated !== null) return undefined;
    const t = setTimeout(() => setResolveTimedOut(true), 4000);
    return () => clearTimeout(t);
  }, [authenticated]);

  if (authenticated === true) return <AuthenticatedHome />;
  if (authenticated === false || resolveTimedOut) return <LandingHome />;
  // ``null`` = auth still resolving: hold the terminal-shaped shell so
  // the (typical) signed-in resolution doesn't replace a 200px landing
  // card with a 4000px dashboard — the site's dominant layout shift.
  return <ResolvingHome />;
}

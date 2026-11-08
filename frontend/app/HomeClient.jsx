"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuthContext } from "@/app/AppShellWrapper";
import TerminalLayout from "@/components/terminal/TerminalLayout";
import {
  SkeletonStat,
  SkeletonTable,
  SkeletonText,
} from "@/components/ds/Skeleton";
import styles from "@/components/terminal/terminal.module.css";
import home from "./home.module.css";

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
    <div
      className={styles.page}
      aria-busy="true"
      aria-label="Loading dashboard"
    >
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
function LandingHome({ advisorServed = false }) {
  return (
    <section className={`${home.landing} psi-editorial`}>
      <div className={home.hero}>
        <div className={home.heroCopy}>
          <p className={home.eyebrow}>Dynasty football / League intelligence</p>
          <h1 className={home.title}>Chase Upside</h1>
          <p className={home.standfirst}>
            The game changes.
            <br />
            Keep your perspective.
          </p>
          <p className={home.introduction}>
            Dynasty fantasy football valuation and trade analysis, plus the full
            public record of our league.
          </p>
          <div className={home.actions}>
            <Link href="/league" className={home.publicAction}>
              {advisorServed ? "Go to League Hub" : "League"}
              <span aria-hidden="true">↗</span>
            </Link>
            <Link href="/login" className={home.privateAction}>
              Sign in<span aria-hidden="true">↗</span>
            </Link>
          </div>
          <div className={home.heroFootnote}>
            <span>Public league</span>
            <span>Private front office</span>
          </div>
        </div>
        <aside
          className={home.leagueRail}
          aria-label="Public league experience"
        >
          <p className={home.eyebrow}>Open to everyone</p>
          <h2>
            Every season
            <br />
            leaves a<br />
            <span>story.</span>
          </h2>
          <p>
            Champions. Records. Rivalries. The games and decisions that become
            league history.
          </p>
          <div className={home.railRule} aria-hidden="true">
            <span>01 / THE LEAGUE</span>
            <span>↗</span>
          </div>
          <p className={home.railCaption}>
            {advisorServed ? (
              <>
                Open to everyone: the Brisket Trade Advisor, plus champions,
                records, rivalries, weekly recaps and every trade in league
                history.
              </>
            ) : (
              <>
                Open to everyone: champions, records, rivalries, weekly recaps
                and every trade in league history.
              </>
            )}
          </p>
        </aside>
      </div>
      <div className={home.pathways}>
        <section className={home.publicPath}>
          <p className={home.eyebrow}>The public record</p>
          <h2>
            The league.
            <br />
            The whole story.
          </h2>
          <p>
            Follow the results, revisit the rivalries and explore the people
            behind the league. A place for the history, not just the standings.
          </p>
          <p className={home.pathScope}>
            Public: champions, records, rivalries, weekly recaps and trade
            history.
          </p>
        </section>
        <section className={home.privatePath}>
          <p className={home.eyebrow}>The member workspace</p>
          <h2>
            Read the field.
            <br />
            Research your move.
          </h2>
          <p>
            Put player rankings, trade tools, waiver and draft analysis into
            context. Research and decision tools stay behind your account.
          </p>
          <p className={home.pathScope}>
            Members only: player rankings, trade tools, waiver and draft
            analysis.
          </p>
        </section>
      </div>
      <div className={home.signoff}>
        <span>CU / Chase Upside</span>
        <p>Football intelligence. With perspective.</p>
      </div>
    </section>
  );
}

// `advisorServed`: decided on the server by ./page.jsx — true only when the
// Brisket Trade Advisor is CONFIRMED served.  Off or unknown, the landing
// card reads exactly as it did before the advisor.
export default function HomeClient({ advisorServed = false } = {}) {
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

  // The Home Screen app starts at "/" (the manifest's start_url).  Opened
  // as an installed app WITHOUT a site session, the person is almost
  // certainly a league-mate using the rookie auction room (its own
  // sign-in), so take them there instead of the marketing landing.
  useEffect(() => {
    if (authenticated !== false || typeof window === "undefined") return;
    const standalone =
      (window.matchMedia &&
        window.matchMedia("(display-mode: standalone)").matches) ||
      window.navigator.standalone === true;
    if (standalone) window.location.replace("/auction");
  }, [authenticated]);

  if (authenticated === true) return <AuthenticatedHome />;
  if (authenticated === false || resolveTimedOut)
    return <LandingHome advisorServed={advisorServed} />;
  // ``null`` = auth still resolving: hold the terminal-shaped shell so
  // the (typical) signed-in resolution doesn't replace a 200px landing
  // card with a 4000px dashboard — the site's dominant layout shift.
  return <ResolvingHome />;
}

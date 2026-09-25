/**
 * /game-day — the canonical Game Day surface (W1-25/W1-26), and the owner's
 * private view of this week's matchup (W1-14/W1-15).
 *
 * ONE ROUTE, ONE OWNER. `docs/GAME_DAY_PROBABILITY_SPEC.md` §7's recommended
 * presentation — the two headline weekly probabilities, the best-ball
 * lineup — is exactly what a private matchup view shows, because they are
 * the same numbers from the same simulation. So this is the Game Day route
 * AND the private matchup surface; the state machine (UPCOMING → LIVE →
 * FINAL) lives on it.
 *
 * PRIVATE BY ROUTE, for the same reason /phases is. Everything under
 * /league is served by the isolated public pipeline and must never read
 * private analysis; this page reads GET /api/matchup/intel, which returns
 * projections, win probabilities and roster weaknesses. `public-routes.js`
 * treats every path outside its allowlist as private.
 *
 * PSI (C8-U2): the `.psi-editorial` token scope on the page root, the
 * shared ds PageHeader, and the full-bleed page rule every migrated
 * reference route uses (rankings / players / trade).
 */

import { Suspense } from "react";
// Direct module import, not the ds barrel: this is a SERVER component, and a
// server import of the barrel makes every "use client" module it re-exports
// (DataTable, Dialog, …) a client reference of this page — measured +22 KB
// of first-load JS. Same convention as the app/*/loading.jsx files.
import { PageHeader } from "@/components/ds/PageHeader";
import GameDayPanel, { GameDayLoading } from "@/components/GameDayPanel";
import styles from "./game-day-page.module.css";

export default function GameDayPage() {
  return (
    <section className={`${styles.page} psi-editorial`}>
      <PageHeader
        className={styles.hero}
        eyebrow="Game Day"
        title="This week's matchup"
        description="Score, projected finish and win chance for your selected team, then the games that matter, then the detail."
      />
      {/* `useSearchParams` inside the panel requires a Suspense boundary
          during static prerender — same convention as
          app/players/compare/page.jsx. */}
      <Suspense fallback={<GameDayLoading />}>
        <GameDayPanel />
      </Suspense>
    </section>
  );
}

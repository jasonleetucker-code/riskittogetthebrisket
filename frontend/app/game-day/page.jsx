"use client";

/**
 * /game-day — the canonical Game Day surface (W1-25/W1-26), and the owner's
 * private view of this week's matchup (W1-14/W1-15).
 *
 * ONE ROUTE, ONE OWNER. `docs/GAME_DAY_PROBABILITY_SPEC.md` §7's recommended
 * presentation — the two headline weekly probabilities, the score
 * distributions, the best-ball lineup — is exactly what a private matchup view
 * shows, because they are the same numbers from the same simulation. Building
 * a second route for "Game Day" beside a "matchup" one would be two surface
 * owners for one concept, which is what CLAUDE.md §3.1 exists to prevent. So
 * this is the Game Day route AND the private matchup surface; the state
 * machine (SCHEDULED/PREGAME → LIVE → FINAL) lives on it.
 *
 * PRIVATE BY ROUTE, for the same reason /phases is. Everything under
 * /league is served by the isolated public pipeline and must never read
 * private analysis; this page reads GET /api/matchup/intel, which returns
 * projections, win probabilities and roster weaknesses. `public-routes.js`
 * treats every path outside its allowlist as private, so this route needs
 * no entry there — but it would be a boundary violation under /league,
 * which is why it is not there.
 */

import { Suspense } from "react";
import { LoadingState, PageHeader } from "@/components/ui";
import GameDayPanel from "@/components/GameDayPanel";

export default function GameDayPage() {
  return (
    <section>
      <PageHeader
        title="Game Day"
        subtitle="Your matchup, projected: win probability from the canonical league-week simulation, the expected best-ball lineup for both sides, and what the numbers were built on."
      />
      {/* `useSearchParams` inside the panel requires a Suspense boundary
          during static prerender — same convention as
          app/players/compare/page.jsx. */}
      <Suspense fallback={<LoadingState message="Loading this week's matchup..." />}>
        <GameDayPanel />
      </Suspense>
    </section>
  );
}

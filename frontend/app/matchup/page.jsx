"use client";

/**
 * /matchup — the owner's private view of this week's matchup.
 *
 * PRIVATE BY ROUTE, for the same reason /phases is. Everything under
 * /league is served by the isolated public pipeline and must never read
 * private analysis; this page reads GET /api/matchup/intel, which returns
 * projections, win probabilities and roster weaknesses. `public-routes.js`
 * treats every path outside its allowlist as private, so this route needs
 * no entry there — but it would be a boundary violation under /league,
 * which is why it is not there.
 */

import { PageHeader } from "@/components/ui";
import MatchupIntelPanel from "@/components/MatchupIntelPanel";

export default function MatchupPage() {
  return (
    <section>
      <PageHeader
        title="This Week"
        subtitle="Your matchup, projected: win probability from the canonical league-week simulation, the expected best-ball lineup for both sides, and what the numbers were built on."
      />
      <MatchupIntelPanel />
    </section>
  );
}

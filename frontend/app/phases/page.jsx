"use client";

/**
 * Win-now vs Rebuild — contention phase per team, plus trade partners.
 *
 * WHY THIS ISN'T UNDER /league ANY MORE
 * -------------------------------------
 * It used to live at /league/phases, which put it inside the public
 * route prefix.  Everything under /league is served by the isolated
 * public pipeline (src/public_league/) and AppShell deliberately
 * refuses to hydrate the private contract there.  But contention
 * classification IS private analysis: TeamPhasePanel calls
 * useDynastyData() directly — bypassing that refusal — to rank every
 * team by top-25 roster value.  A public-prefixed route that fetches
 * the private contract is a boundary violation waiting to become a
 * leak the first time the API allowlist is edited.
 *
 * So the page moved to its own private route instead of being
 * special-cased.  /league/phases still resolves — see the redirect
 * shim there.
 */

import { PageHeader } from "@/components/ui";
import TeamPhasePanel from "@/components/TeamPhasePanel";

export default function PhasesPage() {
  return (
    <section>
      <PageHeader
        title="Win-now vs Rebuild"
        subtitle="Each team classified by top-25 roster value × median age, with natural trade-partner suggestions for your franchise."
      />
      <TeamPhasePanel />
    </section>
  );
}

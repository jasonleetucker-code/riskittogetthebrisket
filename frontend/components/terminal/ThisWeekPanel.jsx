"use client";

import { lazy, Suspense } from "react";
import { useTeam } from "@/components/useTeam";
import { useTeamPlan } from "./useTeamPlan";

// Code-split with React.lazy (not next/dynamic — see CLAUDE.md, Perfect
// Draft: next/dynamic pulled Next's loadable runtime into every page's chunk).
// The body and lib/team-plan.js download only after a plan has arrived, so
// with the owner-held flag off (production default) the home page fetches
// one small 503 and never loads the panel code.
const ThisWeekPlan = lazy(() => import("./ThisWeekPlan"));

/**
 * ThisWeekPanel — the "This week" team plan on the signed-in home
 * (owner directive 2026-11-21, DYN10 item #5).  Renders the composed plan
 * from `GET /api/team/plan` for the selected team, and NOTHING at all — no
 * card, no placeholder — when there is no plan: flag off (503), signed out
 * (401), unknown team (404), league out of scope, or a network failure.
 */
export default function ThisWeekPanel() {
  const { selectedTeam, selectedLeagueKey, leagueLoading, loading } = useTeam();
  const ownerId = String(selectedTeam?.ownerId || "");
  const { plan } = useTeamPlan({
    leagueKey: selectedLeagueKey || "",
    ownerId,
    // Hold the request until league and team identity have settled, so it
    // fires once per (league, team) with the right key.
    enabled: !loading && !leagueLoading && Boolean(ownerId),
  });
  if (!plan) return null;
  return (
    <Suspense fallback={null}>
      <ThisWeekPlan plan={plan} />
    </Suspense>
  );
}

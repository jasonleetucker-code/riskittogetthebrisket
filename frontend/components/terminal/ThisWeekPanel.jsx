"use client";

import { lazy, Suspense } from "react";
import { useAuthContext } from "@/app/AppShellWrapper";
import { useTeam } from "@/components/useTeam";
import { useTeamPlan } from "./useTeamPlan";

// Code-split with React.lazy (not next/dynamic — see CLAUDE.md, Perfect
// Draft: next/dynamic pulled Next's loadable runtime into every page's chunk).
// The body and lib/team-plan.js download only after a plan has arrived.
const ThisWeekPlan = lazy(() => import("./ThisWeekPlan"));

/**
 * True only when `/api/auth/status` (already fetched on every page load) says
 * the plan can be served: `features.teamAdvisorPlan.available === true`
 * (server.py::_team_advisor_plan_available — the owner-held flag
 * `team_advisor_plan` plus a loaded board).  Any other shape — absent key,
 * null map, a bare boolean, a truthy non-boolean — is unknown, and unknown
 * makes no request (the same fail-closed read as nav-model's itemIsOffered).
 */
export function teamPlanCapabilityAvailable(features) {
  return features?.teamAdvisorPlan?.available === true;
}

/**
 * ThisWeekPanel — the "This week" team plan on the signed-in home
 * (owner directive 2026-11-21, DYN10 item #5).  Renders the composed plan
 * from `GET /api/team/plan` for the selected team, and NOTHING at all — no
 * card, no placeholder — when there is no plan.
 *
 * With the flag off (the production default) the capability is false, so
 * the home makes NO plan request and loads no panel code.  The route's own
 * answers stay handled as defence in depth: a 503, 401, 404, a league out of
 * scope or a network failure still render nothing.
 */
export default function ThisWeekPanel() {
  const { features } = useAuthContext();
  const { selectedTeam, selectedLeagueKey, leagueLoading, loading } = useTeam();
  const ownerId = String(selectedTeam?.ownerId || "");
  const { plan } = useTeamPlan({
    leagueKey: selectedLeagueKey || "",
    ownerId,
    // Hold the request until the server says the plan can be served and
    // league and team identity have settled, so it fires once per (league,
    // team) with the right key — or never.
    enabled:
      teamPlanCapabilityAvailable(features) && !loading && !leagueLoading && Boolean(ownerId),
  });
  if (!plan) return null;
  return (
    <Suspense fallback={null}>
      <ThisWeekPlan plan={plan} />
    </Suspense>
  );
}

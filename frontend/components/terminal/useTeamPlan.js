"use client";

/**
 * useTeamPlan — fetch one team's composed plan for the home "This week" panel.
 *
 * One request per (league, team) per mount; no polling.  The answer is a plan
 * only when the backend served one FOR that league and team: a 503 (flag
 * `team_advisor_plan` off — the production default — or data not ready), 401,
 * 404, a league out of scope, a non-plan body or a network failure all yield
 * `plan: null`, and the panel renders nothing.  A late answer for a previous
 * league or team is discarded.
 *
 * Self-contained on purpose: it imports nothing from `lib/team-plan.js`, so
 * that module and the panel body stay in the lazy chunk the home page only
 * downloads once a plan has actually arrived.  This file is the one owner of
 * the request and of "is this a plan for me?"; the Next bridge
 * (`app/api/team/plan/route.js`) and the backend route share the path, pinned
 * by test.
 */
import { useEffect, useState } from "react";

export const TEAM_PLAN_HOOK_ENDPOINT = "/api/team/plan";

export function teamPlanRequestUrl(leagueKey, ownerId) {
  const params = [];
  if (leagueKey) params.push(`leagueKey=${encodeURIComponent(leagueKey)}`);
  if (ownerId) params.push(`team=${encodeURIComponent(String(ownerId))}`);
  return params.length
    ? `${TEAM_PLAN_HOOK_ENDPOINT}?${params.join("&")}`
    : TEAM_PLAN_HOOK_ENDPOINT;
}

export function isServedTeamPlan(payload, leagueKey, ownerId) {
  if (!payload || typeof payload !== "object") return false;
  if (payload.available !== true) return false;
  if (!String(payload.contractVersion || "").startsWith("team-plan/")) return false;
  if (!Array.isArray(payload.actions)) return false;
  if (leagueKey && payload.leagueKey !== leagueKey) return false;
  if (ownerId && String(payload.team?.ownerId ?? "") !== String(ownerId)) return false;
  return true;
}

export function useTeamPlan({ leagueKey = "", ownerId = "", enabled = true } = {}) {
  const active = Boolean(enabled) && Boolean(ownerId);
  const identity = active ? teamPlanRequestUrl(leagueKey, ownerId) : null;
  const [state, setState] = useState({ identity: null, plan: null });

  useEffect(() => {
    if (!identity) return undefined;
    let cancelled = false;
    const ctl = new AbortController();
    (async () => {
      let plan = null;
      try {
        const res = await fetch(identity, {
          signal: ctl.signal,
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        if (res.ok) {
          const json = await res.json().catch(() => null);
          plan = isServedTeamPlan(json, leagueKey, ownerId) ? json : null;
        }
      } catch {
        plan = null;
      }
      if (!cancelled) setState({ identity, plan });
    })();
    return () => {
      cancelled = true;
      ctl.abort();
    };
  }, [identity, leagueKey, ownerId]);

  return { plan: identity && state.identity === identity ? state.plan : null };
}

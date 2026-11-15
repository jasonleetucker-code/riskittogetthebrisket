// Server-side read of "is the Brisket Trade Advisor served?" — the ONE
// place the frontend server asks.
//
// Reads the advisor's public teams endpoint and classifies it with
// `classifyTeamsResult`: "ready" (served), "disabled" (flag
// `brisket_trade_advisor` off → 503 advisor_unavailable/disabled, or 404)
// or "unknown" (no answer).  Used by the League Hub (./page.jsx, which adds
// `connection()` because that page is dynamic anyway), the league
// detail pages' back-links, the landing page and the sitemap.
//
// Deliberately no `connection()` here: a static page that reads it becomes
// ISR on the `revalidate` window (one cached backend read shared by every
// visitor, never a per-visitor or browser request).  During `next build`
// the backend is absent, the read answers "unknown", and every surface
// renders exactly as main until the first revalidation.
//
// Surfaces outside the hub switch to advisor wording only on "ready":
// "unknown" never guesses the flag is on (an off flag changes nothing).
import { fetchBackendResult } from "../../lib/server-backend.js";
import { classifyTeamsResult } from "../../lib/trade-advisor-client.js";
import { leagueHomeHrefFor } from "./tabs.js";

export const ADVISOR_TEAMS_PATH = "/api/public/league/trade-advisor/teams";

/** Classified advisor bootstrap: { state: "ready" | "disabled" | "unknown", data? }. */
export async function fetchAdvisorBootstrap({ revalidate = 60 } = {}) {
  const result = await fetchBackendResult(ADVISOR_TEAMS_PATH, { revalidate });
  return classifyTeamsResult(result);
}

/** True only when the advisor is CONFIRMED served. */
export async function advisorConfirmedServed(opts) {
  return (await fetchAdvisorBootstrap(opts)).state === "ready";
}

/** "← League home" href for the league detail pages. */
export async function leagueHomeHref() {
  return leagueHomeHrefFor(await fetchAdvisorBootstrap());
}

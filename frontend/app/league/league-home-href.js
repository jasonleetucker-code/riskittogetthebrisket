// Server-side "← League home" href for the /league/* detail pages.
//
// Reads the Brisket Trade Advisor's public teams endpoint the same way
// ./page.jsx does (same path, same 60 s revalidate, so Next dedupes it with
// the hub's own bootstrap read) and classifies it with the same
// `classifyTeamsResult`.  Advisor off (503 advisor_unavailable/disabled or
// 404) or no answer → `/league`, exactly as before the advisor; confirmed
// served → `/league?tab=overview`.  Rule: `leagueHomeHrefFor` in ./tabs.js.
//
// Deliberately no `connection()`: these pages keep whatever rendering mode
// their own revalidating fetches give them.
import { fetchBackendResult } from "../../lib/server-backend.js";
import { classifyTeamsResult } from "../../lib/trade-advisor-client.js";
import { leagueHomeHrefFor } from "./tabs.js";

export const ADVISOR_TEAMS_PATH = "/api/public/league/trade-advisor/teams";

export async function leagueHomeHref() {
  const result = await fetchBackendResult(ADVISOR_TEAMS_PATH, { revalidate: 60 });
  return leagueHomeHrefFor(classifyTeamsResult(result));
}

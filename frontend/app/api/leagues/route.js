import { NextResponse } from "next/server";

import { proxyGet } from "@/lib/backend-proxy";

// Dev-only bridge to the FastAPI backend, and the missing member of the set.
//
// In production nginx routes every `/api/*` path straight to the backend, so
// this file is never reached. Where Next serves `/api/*` itself — local dev
// and the E2E stack, neither of which runs nginx — its absence was NOT a
// harmless 404. `useLeague()` fetches `/api/leagues` (useLeague.js:53); with
// no route, Next answered the HTML 404 page, the JSON parse failed, and
// `leagues` stayed empty. `selectedLeagueKey` only returns a candidate that
// is in that list (useLeague.js:165-183), so it was permanently "".
//
// That silently un-scopes every league-keyed surface. Concretely on /draft:
// `draftStorageKey` falls back to the UNSUFFIXED legacy key
// (draft/page.jsx:3426-3431), so the league-scoped workspace never hydrates
// and the board sits on `createDefaultWorkspace()`'s placeholder teams for
// the life of the page.
//
// Cookies must be forwarded: the endpoint is public but has an authenticated
// view, adding `userDefaultKey` and per-league `userDefaultTeam` — which is
// exactly the part that tells the UI which league and team to land on.
export async function GET(request) {
  try {
    const { data, status } = await proxyGet("/api/leagues", {
      cookie: request.headers.get("cookie") || "",
    });
    // Pass the upstream status through verbatim so the client can tell
    // "no leagues configured" from "backend down".
    return NextResponse.json(data, {
      status,
      // Per-user (userDefaultKey/userDefaultTeam). Never cache at the edge.
      headers: { "Cache-Control": "no-store, private" },
    });
  } catch (err) {
    return NextResponse.json(
      { error: "leagues_unavailable", detail: err?.message },
      { status: 503, headers: { "Cache-Control": "no-store, private" } },
    );
  }
}

import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

/**
 * Proxy for /api/ros/pick-projections.
 *
 * The backend endpoint has existed, registered and mounted, with no
 * caller — the same shape as /api/player/{id}/realized, which turned
 * out to return an empty list for every player because nothing
 * exercised it. This route is what makes it observable.
 *
 * League-scoped: pick ownership and team strength both follow
 * leagueKey per CLAUDE.md, so the key is forwarded when present and
 * the backend resolves its default when not.
 */
export async function GET(request) {
  try {
    const leagueKey = request?.nextUrl?.searchParams?.get("leagueKey");
    const { data, status } = await proxyGet("/api/ros/pick-projections", {
      cookie: request.headers.get("cookie") || "",
      ...(leagueKey ? { searchParams: { leagueKey } } : {}),
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "Pick projection service unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}

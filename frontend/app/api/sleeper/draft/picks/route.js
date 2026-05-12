import { NextResponse } from "next/server";

// Proxy for the backend's live-draft picks endpoint.  Forwards the
// session cookie (the backend route is private — not on the
// PUBLIC_API allowlist) and passes through ``leagueKey`` +
// ``afterPickNo`` query params.  Polled every ~2.5s by the /draft
// page when live sync is toggled on, so this stays as thin as
// possible — no caching, no transformation.
const BACKEND_BASE = (() => {
  const raw = process.env.BACKEND_API_URL || "http://127.0.0.1:8000/api/data";
  return raw.replace(/\/api\/data\/?$/, "");
})();

export async function GET(request) {
  const incoming = new URL(request.url);
  const target = new URL("/api/sleeper/draft/picks", BACKEND_BASE);
  const leagueKey = incoming.searchParams.get("leagueKey");
  const afterPickNo = incoming.searchParams.get("afterPickNo");
  if (leagueKey) target.searchParams.set("leagueKey", leagueKey);
  if (afterPickNo) target.searchParams.set("afterPickNo", afterPickNo);

  const cookie = request.headers.get("cookie") || "";
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 4000);
  try {
    const res = await fetch(target.toString(), {
      cache: "no-store",
      signal: ctl.signal,
      headers: cookie ? { Cookie: cookie } : undefined,
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      {
        error: "sleeper_proxy_unavailable",
        message: err?.message || "Backend unreachable",
      },
      { status: 503 },
    );
  } finally {
    clearTimeout(timer);
  }
}

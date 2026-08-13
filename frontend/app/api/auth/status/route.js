import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

export async function GET(request) {
  try {
    // Forward cookies for session auth
    const cookie = request.headers.get("cookie") || "";
    const url = new URL("/api/auth/status", process.env.BACKEND_API_URL || "http://127.0.0.1:8000");
    const ctl = new AbortController();
    // 3000 ms was the SOURCE OF THE 502 in E2E console logs — traced and
    // independently reproduced. Same class of defect as the dynasty-data
    // bridge's old 4s budget: the backend's event loop can stall for ~10s
    // (measured; see that route's note), so a 3s budget reports a
    // live-but-busy backend as unreachable.
    //
    // Harmless to the USER — `useAuth` treats any non-OK as UNKNOWN and
    // retries, keeping the optimistic cached session, which is exactly
    // what the catch below is written for. `authenticated` gates search,
    // never data: AppShell calls `useDynastyData()` unconditionally.
    //
    // NOT harmless to DIAGNOSIS. It put an unexplained `502 (Bad Gateway)`
    // into the console of every failing run, which reads as infrastructure
    // breakage rather than "the backend was busy", and sourcing it needed
    // a sweep of all 45 bridge routes — the console line names a status
    // but not a URL.
    //
    // Keep that value in mind if this ever needs lowering: this 502 is now
    // the most reliable available SIGNAL that the backend stalled >3s
    // during a page load. Raising the budget makes the signal rarer. That
    // is the right trade only because tests/e2e/helpers/journey.js now
    // records `msg.location().url`, so the next failing run names its own
    // endpoints directly rather than needing this one as a proxy.
    //
    // 15s sits above the measured stall while staying well under the data
    // fetch's budget — this is a tiny JSON probe, not a 4 MB transfer.
    const timer = setTimeout(() => ctl.abort(), 15000);
    try {
      const res = await fetch(url.toString(), {
        cache: "no-store",
        signal: ctl.signal,
        headers: { Cookie: cookie },
      });
      const data = await res.json();
      return NextResponse.json(data, { status: res.status });
    } finally {
      clearTimeout(timer);
    }
  } catch {
    // Backend unreachable / timeout / parse failure — return a
    // non-2xx so callers (notably ``useAuth``) can distinguish a
    // transient infra blip from a genuine ``{authenticated: false}``
    // and preserve the optimistic cached session instead of forcing
    // a sign-out on every backend hiccup.
    return NextResponse.json(
      { authenticated: false, error: "auth_status_unreachable" },
      { status: 502 },
    );
  }
}

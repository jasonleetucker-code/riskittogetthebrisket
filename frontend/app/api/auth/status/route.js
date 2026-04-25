import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

export async function GET(request) {
  try {
    // Forward cookies for session auth
    const cookie = request.headers.get("cookie") || "";
    const url = new URL("/api/auth/status", process.env.BACKEND_API_URL || "http://127.0.0.1:8000");
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 3000);
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

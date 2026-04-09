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
    return NextResponse.json({ authenticated: false }, { status: 200 });
  }
}

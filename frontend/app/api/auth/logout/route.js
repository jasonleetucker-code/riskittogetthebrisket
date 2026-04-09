import { NextResponse } from "next/server";

export async function POST(request) {
  try {
    const cookie = request.headers.get("cookie") || "";
    const url = new URL("/api/auth/logout", process.env.BACKEND_API_URL || "http://127.0.0.1:8000");
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 3000);
    try {
      const res = await fetch(url.toString(), {
        method: "POST",
        cache: "no-store",
        signal: ctl.signal,
        headers: { Cookie: cookie },
      });
      const data = await res.json().catch(() => ({}));
      return NextResponse.json(data, { status: res.status });
    } finally {
      clearTimeout(timer);
    }
  } catch {
    return NextResponse.json({ ok: true }, { status: 200 });
  }
}

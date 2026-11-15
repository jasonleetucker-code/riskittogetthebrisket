import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_API_URL
  ? new URL("/api/scrape", process.env.BACKEND_API_URL.replace(/\/api\/data$/, "")).toString()
  : "http://127.0.0.1:8000/api/scrape";

export async function POST(request) {
  // The backend gates /api/scrape on an admin session (W22-F007), so the bridge must forward
  // the caller's cookie or every dev/E2E call is an anonymous request that gets refused.
  const cookie = request.headers.get("cookie") || "";
  try {
    const res = await fetch(BACKEND, {
      method: "POST",
      headers: { Cookie: cookie },
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ error: "Backend unreachable" }, { status: 502 });
  }
}

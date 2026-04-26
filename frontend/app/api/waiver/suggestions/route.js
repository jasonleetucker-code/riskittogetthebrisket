import { NextResponse } from "next/server";

const SUGGESTIONS_URL = (() => {
  const base = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(/\/api\/data\/?$/, "");
  return `${base}/api/waiver/suggestions`;
})();

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 10000);
  try {
    // Forward the user's session cookies so the backend's auth gate
    // accepts the call (waiver suggestions read league rosters which
    // are private per-league data).
    const cookie = request.headers.get("cookie") || "";
    const res = await fetch(SUGGESTIONS_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(cookie ? { cookie } : {}),
      },
      body: JSON.stringify(body),
      signal: ctl.signal,
      cache: "no-store",
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { error: "Waiver service unavailable", detail: err?.message },
      { status: 503 },
    );
  } finally {
    clearTimeout(timer);
  }
}

import { NextResponse } from "next/server";

// Pre-compute backend suggestions URL once at module load.
const SUGGESTIONS_URL = (() => {
  const base = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(/\/api\/data\/?$/, "");
  return `${base}/api/trade/suggestions`;
})();

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 5000);
  try {
    const res = await fetch(SUGGESTIONS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: ctl.signal,
      cache: "no-store",
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { error: "Suggestion service unavailable", detail: err?.message },
      { status: 503 },
    );
  } finally {
    clearTimeout(timer);
  }
}

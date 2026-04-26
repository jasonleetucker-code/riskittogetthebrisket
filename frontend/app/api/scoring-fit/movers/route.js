import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_API_URL
  ? new URL("/api/scoring-fit/movers", process.env.BACKEND_API_URL.replace(/\/api\/data$/, "")).toString()
  : "http://127.0.0.1:8000/api/scoring-fit/movers";

export async function GET() {
  try {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 5000);
    const res = await fetch(BACKEND, { cache: "no-store", signal: ctl.signal });
    clearTimeout(timer);
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ has_baseline: false, risers: [], fallers: [] }, { status: 200 });
  }
}

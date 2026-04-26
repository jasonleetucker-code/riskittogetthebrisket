import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_API_URL
  ? new URL("/api/idp-fit-health", process.env.BACKEND_API_URL.replace(/\/api\/data$/, "")).toString()
  : "http://127.0.0.1:8000/api/idp-fit-health";

export async function GET() {
  try {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 5000);
    const res = await fetch(BACKEND, { cache: "no-store", signal: ctl.signal });
    clearTimeout(timer);
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ error: "Backend unreachable" }, { status: 502 });
  }
}

import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_API_URL
  ? new URL("/api/scrape", process.env.BACKEND_API_URL.replace(/\/api\/data$/, "")).toString()
  : "http://127.0.0.1:8000/api/scrape";

export async function POST() {
  try {
    const res = await fetch(BACKEND, { method: "POST", cache: "no-store" });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ error: "Backend unreachable" }, { status: 502 });
  }
}

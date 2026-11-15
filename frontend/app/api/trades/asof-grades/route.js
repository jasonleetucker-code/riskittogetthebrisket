import { NextResponse } from "next/server";
import { proxyPost } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI.  At-the-Time trade grades for /trades (owner package 2026-10-17):
// one ledger read for the whole visible history.
export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_json" }, { status: 400 });
  }
  try {
    const { data, status } = await proxyPost("/api/trades/asof-grades", body, {
      cookie: request.headers.get("cookie") || "",
      timeoutMs: 30000,
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "asof_grades_unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}

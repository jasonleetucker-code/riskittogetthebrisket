import { NextResponse } from "next/server";
import { proxyPost } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. First compute of a BDVM valuation takes seconds (full
// engine run before the cache warms), hence the long timeout.
export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_json" }, { status: 400 });
  }
  try {
    const { data, status } = await proxyPost("/api/bdvm/trade-eval", body, {
      cookie: request.headers.get("cookie") || "",
      timeoutMs: 30000,
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "bdvm_unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}

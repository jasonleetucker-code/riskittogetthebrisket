import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. First compute of a BDVM valuation takes seconds (full
// engine run before the cache warms), hence the long timeout.
export async function GET(request) {
  try {
    const searchParams = {};
    for (const key of ["leagueKey", "surplusMode"]) {
      const value = request?.nextUrl?.searchParams?.get(key);
      if (value) searchParams[key] = value;
    }
    const { data, status } = await proxyGet("/api/bdvm/values", {
      cookie: request.headers.get("cookie") || "",
      searchParams,
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

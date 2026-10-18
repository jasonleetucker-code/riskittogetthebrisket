import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. Manager Intelligence is private; the session cookie is forwarded
// so the backend's auth gate decides. Activity reads every week of every
// league, so it gets a longer timeout than the profile bridge.
export async function GET(request) {
  try {
    const searchParams = {};
    for (const key of ["username", "window", "season", "league", "scope"]) {
      const value = request?.nextUrl?.searchParams?.get(key);
      if (value) searchParams[key] = value;
    }
    const { data, status } = await proxyGet("/api/manager-intel/activity", {
      cookie: request.headers.get("cookie") || "",
      searchParams,
      timeoutMs: 90000,
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      {
        error: "upstream_unavailable",
        message: "Manager Intelligence is unavailable.",
        detail: err?.message,
      },
      { status: 503 },
    );
  }
}

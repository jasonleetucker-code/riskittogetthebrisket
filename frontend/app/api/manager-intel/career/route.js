import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. The career view (Manager Intelligence Batch E) is private; the
// session cookie is forwarded so the backend's auth gate decides. It walks
// every league's previous seasons, so it shares the activity bridge's timeout.
export async function GET(request) {
  try {
    const searchParams = {};
    for (const key of ["username", "scope"]) {
      const value = request?.nextUrl?.searchParams?.get(key);
      if (value) searchParams[key] = value;
    }
    const { data, status } = await proxyGet("/api/manager-intel/career", {
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

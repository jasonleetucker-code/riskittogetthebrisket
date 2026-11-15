import { NextResponse } from "next/server";
import { proxyDelete, proxyGet, proxyPost } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. Saved managers (Manager Intelligence Batch F) are private and
// per user; the session cookie is forwarded so the backend's auth gate
// decides. GET re-reads each saved manager's name on Sleeper (memoised).
function unavailable(err) {
  return NextResponse.json(
    {
      error: "upstream_unavailable",
      message: "Saved managers are unavailable.",
      detail: err?.message,
    },
    { status: 503 },
  );
}

export async function GET(request) {
  try {
    const { data, status } = await proxyGet("/api/manager-intel/saved", {
      cookie: request.headers.get("cookie") || "",
      timeoutMs: 30000,
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return unavailable(err);
  }
}

export async function POST(request) {
  try {
    const body = await request.json().catch(() => null);
    const { data, status } = await proxyPost("/api/manager-intel/saved", body, {
      cookie: request.headers.get("cookie") || "",
      timeoutMs: 15000,
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return unavailable(err);
  }
}

export async function DELETE(request) {
  try {
    const userId = request?.nextUrl?.searchParams?.get("userId") || "";
    const { data, status } = await proxyDelete("/api/manager-intel/saved", {
      cookie: request.headers.get("cookie") || "",
      searchParams: userId ? { userId } : undefined,
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return unavailable(err);
  }
}

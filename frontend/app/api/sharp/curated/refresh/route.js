import { NextResponse } from "next/server";
import { proxyPost } from "@/lib/backend-proxy";

export const dynamic = "force-dynamic";

export async function POST(request) {
  const body = await request.json().catch(() => ({}));
  try {
    const { data, status } = await proxyPost("/api/sharp/curated/refresh", body, {
      cookie: request.headers.get("cookie") || "",
      timeoutMs: 120000,
    });
    return NextResponse.json(data, { status });
  } catch (error) {
    return NextResponse.json(
      { error: "curated_sharp_refresh_failed", message: error?.message || "Request failed" },
      { status: 503 },
    );
  }
}

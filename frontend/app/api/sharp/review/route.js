import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

export const dynamic = "force-dynamic";

export async function GET(request) {
  const searchParams = Object.fromEntries(new URL(request.url).searchParams.entries());
  try {
    const { data, status } = await proxyGet("/api/sharp/review", {
      timeoutMs: 20000,
      searchParams,
    });
    return NextResponse.json(data, { status });
  } catch (error) {
    return NextResponse.json(
      { error: "sharp_review_unavailable", message: error?.message || "Request failed" },
      { status: 503 },
    );
  }
}

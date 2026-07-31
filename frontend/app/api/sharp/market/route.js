import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

export async function GET(request) {
  const incoming = new URL(request.url).searchParams;
  const searchParams = Object.fromEntries(incoming.entries());
  try {
    const { data, status } = await proxyGet("/api/sharp/market", {
      timeoutMs: 20000,
      searchParams,
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "sharp_market_unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}

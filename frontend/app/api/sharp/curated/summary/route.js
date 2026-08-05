import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const { data, status } = await proxyGet("/api/sharp/curated/summary", { timeoutMs: 20000 });
    return NextResponse.json(data, { status });
  } catch (error) {
    return NextResponse.json(
      { error: "curated_sharp_unavailable", message: error?.message || "Request failed" },
      { status: 503 },
    );
  }
}

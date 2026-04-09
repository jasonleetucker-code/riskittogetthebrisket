import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

export async function GET() {
  try {
    const { data, status } = await proxyGet("/api/draft-capital");
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "Draft capital service unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}

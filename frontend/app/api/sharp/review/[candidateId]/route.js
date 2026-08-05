import { NextResponse } from "next/server";
import { proxyPost } from "@/lib/backend-proxy";

export const dynamic = "force-dynamic";

export async function POST(request, { params }) {
  const { candidateId } = await params;
  const body = await request.json().catch(() => ({}));
  try {
    const { data, status } = await proxyPost(
      `/api/sharp/review/${encodeURIComponent(candidateId)}`,
      body,
      { timeoutMs: 30000 },
    );
    return NextResponse.json(data, { status });
  } catch (error) {
    return NextResponse.json(
      { error: "sharp_review_unavailable", message: error?.message || "Request failed" },
      { status: 503 },
    );
  }
}

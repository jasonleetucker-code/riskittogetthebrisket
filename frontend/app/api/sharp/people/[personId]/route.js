import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

export const dynamic = "force-dynamic";

export async function GET(request, { params }) {
  const { personId } = await params;
  try {
    const { data, status } = await proxyGet(`/api/sharp/people/${encodeURIComponent(personId)}`, {
      cookie: request.headers.get("cookie") || "",
      timeoutMs: 20000,
    });
    return NextResponse.json(data, { status });
  } catch (error) {
    return NextResponse.json(
      { error: "sharp_person_unavailable", message: error?.message || "Request failed" },
      { status: 503 },
    );
  }
}

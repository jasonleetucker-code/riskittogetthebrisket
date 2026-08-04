import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to FastAPI.
export async function GET() {
  try {
    const { data, status } = await proxyGet("/api/consensus-edge/health", { timeoutMs: 15000 });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "consensus_edge_unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}

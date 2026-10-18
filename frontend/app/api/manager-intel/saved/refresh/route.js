import { NextResponse } from "next/server";
import { proxyPost } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. The in-app new-activity check (Manager Intelligence Batch F)
// reads up to three saved managers' activity, so it shares the activity
// bridge's timeout.
export async function POST(request) {
  try {
    const { data, status } = await proxyPost(
      "/api/manager-intel/saved/refresh",
      {},
      { cookie: request.headers.get("cookie") || "", timeoutMs: 90000 },
    );
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

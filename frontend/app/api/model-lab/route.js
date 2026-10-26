import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev/E2E bridge only — in production nginx routes /api/* straight to FastAPI.
// The Model Lab is PRIVATE and admin-only (backend ``_require_admin_session``);
// forwarding the caller's cookie is what lets the backend decide, and the
// answer is never cached here.
export async function GET(request) {
  try {
    const { data, status } = await proxyGet("/api/model-lab", {
      cookie: request.headers.get("cookie") || "",
      timeoutMs: 30000,
    });
    return NextResponse.json(data, { status, headers: { "Cache-Control": "no-store" } });
  } catch (err) {
    return NextResponse.json(
      { error: "model_lab_unavailable", detail: err?.message },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}

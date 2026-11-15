import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev/E2E bridge only — in production nginx routes /api/* straight to FastAPI.
// One Model Lab family; PRIVATE and admin-only on the backend. Family ids are
// snake_case; anything else (".." included) is refused here so it can never
// resolve to another backend route.
const FAMILY_ID = /^[a-z0-9_]{1,64}$/;

export async function GET(request, { params }) {
  try {
    const { family = "" } = await params;
    if (!FAMILY_ID.test(family)) {
      return NextResponse.json(
        { error: "unknown_family", message: "No such model family." },
        { status: 404, headers: { "Cache-Control": "no-store" } },
      );
    }
    const { data, status } = await proxyGet(`/api/model-lab/${encodeURIComponent(family)}`, {
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

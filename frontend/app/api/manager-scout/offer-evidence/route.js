import { NextResponse } from "next/server";
import { proxyPost } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. The /trade counterparty panel (TC-B / TCM-O12): Manager Scout's
// evidence for ONE package. Private and league-scoped; the session cookie is
// forwarded so the backend's auth gate decides, and leagueKey stays in the
// query string like every Manager Scout call.
export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_body", field: "body" }, { status: 400 });
  }
  try {
    const leagueKey = request?.nextUrl?.searchParams?.get("leagueKey");
    const path = leagueKey
      ? `/api/manager-scout/offer-evidence?leagueKey=${encodeURIComponent(leagueKey)}`
      : "/api/manager-scout/offer-evidence";
    const { data, status } = await proxyPost(path, body, {
      cookie: request.headers.get("cookie") || "",
      timeoutMs: 30000,
    });
    return NextResponse.json(data, { status, headers: { "Cache-Control": "no-store" } });
  } catch (err) {
    return NextResponse.json(
      { error: "manager_scout_unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}

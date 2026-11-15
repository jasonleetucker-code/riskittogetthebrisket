import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev bridge for GET /api/market/trades/reference (C3-CALC-01 / TC-07).
// Production nginx routes /api/ straight to the backend; this keeps the
// Next dev server answering the same path.  Values are comma-joined by the
// caller, so forwarding one value per key loses nothing.

export const dynamic = "force-dynamic";
export const revalidate = 0;

const NO_STORE_HEADERS = {
  "Cache-Control": "private, no-store, no-cache, max-age=0, must-revalidate",
  Pragma: "no-cache",
};

export async function GET(request) {
  const searchParams = Object.fromEntries(new URL(request.url).searchParams.entries());
  try {
    const { data, status } = await proxyGet("/api/market/trades/reference", {
      cookie: request.headers.get("cookie") || "",
      timeoutMs: 20000,
      searchParams,
    });
    return NextResponse.json(data, { status, headers: NO_STORE_HEADERS });
  } catch (err) {
    return NextResponse.json(
      { error: "trade_ledger_unavailable", detail: err?.message },
      { status: 503, headers: NO_STORE_HEADERS },
    );
  }
}

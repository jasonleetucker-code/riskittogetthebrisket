import { NextResponse } from "next/server";

const BACKEND = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
  /\/api\/data\/?$/,
  "",
);

export async function POST(request) {
  const cookie = request.headers.get("cookie") || "";
  const ctl = new AbortController();
  // Rebuilding the full contract is usually 1-3s but allow headroom.
  const timer = setTimeout(() => ctl.abort(), 30_000);
  try {
    const res = await fetch(`${BACKEND}/api/idp-calibration/refresh-board`, {
      method: "POST",
      headers: { Cookie: cookie },
      cache: "no-store",
      signal: ctl.signal,
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { ok: false, error: "IDP calibration service unavailable", detail: err?.message },
      { status: 503 },
    );
  } finally {
    clearTimeout(timer);
  }
}

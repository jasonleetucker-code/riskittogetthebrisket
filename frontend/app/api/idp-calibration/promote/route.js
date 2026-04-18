import { NextResponse } from "next/server";

const BACKEND = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
  /\/api\/data\/?$/,
  "",
);

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  const cookie = request.headers.get("cookie") || "";
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 10_000);
  try {
    const res = await fetch(`${BACKEND}/api/idp-calibration/promote`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Cookie: cookie },
      body: JSON.stringify(body || {}),
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

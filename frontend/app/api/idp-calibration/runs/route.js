import { NextResponse } from "next/server";

const BACKEND = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
  /\/api\/data\/?$/,
  "",
);

export async function GET(request) {
  const cookie = request.headers.get("cookie") || "";
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 5000);
  try {
    const res = await fetch(`${BACKEND}/api/idp-calibration/runs`, {
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

export async function DELETE(request) {
  const cookie = request.headers.get("cookie") || "";
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 10_000);
  try {
    const res = await fetch(`${BACKEND}/api/idp-calibration/runs`, {
      method: "DELETE",
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

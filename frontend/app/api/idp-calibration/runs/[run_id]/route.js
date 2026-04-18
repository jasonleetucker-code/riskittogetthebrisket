import { NextResponse } from "next/server";

const BACKEND = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
  /\/api\/data\/?$/,
  "",
);

export async function GET(request, { params }) {
  const cookie = request.headers.get("cookie") || "";
  const awaited = await params;
  const runId = encodeURIComponent(String(awaited?.run_id || ""));
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 8000);
  try {
    const res = await fetch(`${BACKEND}/api/idp-calibration/runs/${runId}`, {
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

export async function DELETE(request, { params }) {
  const cookie = request.headers.get("cookie") || "";
  const awaited = await params;
  const runId = encodeURIComponent(String(awaited?.run_id || ""));
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 8000);
  try {
    const res = await fetch(`${BACKEND}/api/idp-calibration/runs/${runId}`, {
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

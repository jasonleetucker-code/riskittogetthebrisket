import { NextResponse } from "next/server";

const URL_BACKEND = (() => {
  const base = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(/\/api\/data\/?$/, "");
  return `${base}/api/waiver/drops`;
})();

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 8000);
  try {
    const cookie = request.headers.get("cookie") || "";
    const res = await fetch(URL_BACKEND, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(cookie ? { cookie } : {}) },
      body: JSON.stringify(body),
      signal: ctl.signal,
      cache: "no-store",
    });
    return NextResponse.json(await res.json(), { status: res.status });
  } catch (err) {
    return NextResponse.json({ drops: [], error: err?.message }, { status: 200 });
  } finally {
    clearTimeout(timer);
  }
}

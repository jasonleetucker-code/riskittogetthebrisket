const endpoint = new URL("/api/telemetry/web-vitals", process.env.BACKEND_API_URL || "http://127.0.0.1:8000");
const limit = 8192;
const jsonError = (error, status) => Response.json({ error }, { status, headers: { "Cache-Control": "no-store" } });

// Public tiny-body dev bridge. The backend validates the metric allowlist;
// cookies, URL/referrer, and arbitrary client headers are never forwarded.
export async function POST(request) {
  if (Number(request.headers.get("content-length")) > limit) return jsonError("body_too_large", 413);
  const reader = request.body?.getReader();
  if (!reader) return jsonError("invalid_metric", 400);
  const chunks = [];
  let size = 0;
  const ctl = new AbortController();
  let timer;
  try {
    const read = async () => {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > limit) { await reader.cancel(); return null; }
        chunks.push(value);
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
      return new TextDecoder().decode(bytes);
    };
    const timeout = new Promise((_, reject) => { timer = setTimeout(() => { ctl.abort(); reader.cancel().catch(() => {}); reject(new Error("timeout")); }, 4000); });
    const body = await Promise.race([read(), timeout]);
    if (body === null) return jsonError("body_too_large", 413);
    try { JSON.parse(body); } catch { return jsonError("invalid_metric", 400); }
    const upstream = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body,
      cache: "no-store", referrerPolicy: "no-referrer", redirect: "error", signal: ctl.signal });
    const responseBody = await upstream.text();
    return new Response(upstream.status === 204 ? null : responseBody, { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch {
    return jsonError("telemetry_unavailable", 503);
  } finally {
    clearTimeout(timer);
  }
}

import { streamWithUpstreamIdleAbort } from "@/lib/upstream-stream";

// Next-fronted dev/E2E bridge. Production nginx sends /api/* to FastAPI.
const origin = new URL(process.env.BACKEND_API_URL || "http://127.0.0.1:8000").origin;
const allowed = /^(?:rankings|trade\/context|players\/catalog|players\/[A-Za-z0-9_-]{1,128})$/;
const responseHeaders = ["content-type", "etag", "vary", "www-authenticate", "retry-after", "server-timing", "x-request-id", "x-payload-view", "x-read-model-generation"];

export async function GET(request, context) {
  const { path = [] } = await context.params;
  const route = path.join("/");
  if (!allowed.test(route)) return Response.json({ error: "not_found" }, { status: 404, headers: { "Cache-Control": "no-store" } });
  const target = new URL(`/api/read-models/${route}`, origin);
  const incoming = new URL(request.url);
  for (const key of ["leagueKey", "generation"]) {
    const value = incoming.searchParams.get(key);
    if (value) target.searchParams.set(key, value);
  }
  const headers = new Headers();
  for (const name of ["cookie", "if-none-match", "traceparent", "x-request-id"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 4000);
  try {
    const upstream = await fetch(target, { headers, cache: "no-store", signal: ctl.signal, redirect: "error" });
    clearTimeout(timer);
    const forwarded = new Headers();
    for (const name of responseHeaders) {
      const value = upstream.headers.get(name);
      if (value) forwarded.set(name, value);
    }
    const policy = upstream.headers.get("cache-control") || "";
    forwarded.set("cache-control", upstream.ok || upstream.status === 304
      ? (/\bprivate\b|\bno-store\b/.test(policy) ? policy : "private, no-cache") : "no-store");
    if (upstream.status === 304) return new Response(null, { status: 304, headers: forwarded });
    if (upstream.ok && !/\bapplication\/json\b/i.test(upstream.headers.get("content-type") || "")) {
      ctl.abort();
      return Response.json({ error: "backend_non_json" }, { status: 502, headers: { "Cache-Control": "no-store" } });
    }
    return new Response(upstream.body ? streamWithUpstreamIdleAbort(upstream, ctl) : null, { status: upstream.status, headers: forwarded });
  } catch {
    return Response.json({ error: "backend_unavailable" }, { status: 503, headers: { "Cache-Control": "no-store" } });
  } finally {
    clearTimeout(timer);
  }
}

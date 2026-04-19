// Proxy for POST /api/chat — forwards the request (including the
// session cookie) to the FastAPI backend and streams the backend's
// Server-Sent Events response straight back to the browser.
//
// Unlike the JSON proxies in sibling directories, this route must
// preserve streaming end-to-end: passing `upstream.body` directly
// into the outgoing ``Response`` forwards each SSE frame as soon
// as the backend emits it, instead of buffering the entire payload
// before responding.

const BACKEND = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
  /\/api\/data\/?$/,
  "",
);

export const dynamic = "force-dynamic";

export async function POST(request) {
  const cookie = request.headers.get("cookie") || "";

  // Pass through the body verbatim — don't round-trip through
  // ``request.json()`` because the backend handles the validation
  // and we want error-shape responses to surface cleanly.
  const body = await request.text();

  let upstream;
  try {
    upstream = await fetch(`${BACKEND}/api/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Cookie: cookie,
      },
      body,
      cache: "no-store",
      // No timeout — the conversation can stream for a minute+
      // on long multi-turn exchanges.  The browser controls
      // cancellation via the client-side AbortController.
    });
  } catch (err) {
    return Response.json(
      {
        ok: false,
        error: "Chat backend unavailable",
        detail: err?.message || String(err),
      },
      { status: 503 },
    );
  }

  // Non-2xx upstream responses are plain JSON error bodies — forward
  // them without trying to stream.
  const contentType = upstream.headers.get("Content-Type") || "";
  if (!contentType.includes("text/event-stream")) {
    const text = await upstream.text();
    return new Response(text, {
      status: upstream.status,
      headers: {
        "Content-Type": contentType || "application/json",
        "Cache-Control": "no-store",
      },
    });
  }

  // Stream pass-through.  ``upstream.body`` is a ReadableStream; the
  // outgoing ``Response`` hands it to the browser unmodified.
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-store",
      "X-Accel-Buffering": "no",
      Connection: "keep-alive",
    },
  });
}

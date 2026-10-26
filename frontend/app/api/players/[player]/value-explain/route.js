import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev/E2E bridge for GET /api/players/{player}/value-explain.
//
// In production nginx routes /api/* straight to FastAPI and this file is
// never reached; it exists so the Player File's value explanation works
// where Next serves /api/* itself (dev and the E2E stack).
//
// PRIVATE: the backend endpoint sits behind the session gate
// (server.py::_private_api_gate — it is not on the public allowlist), so the
// caller's cookie is forwarded. Never surface this on a public /league page.
//
// Mirrored backend endpoint: server.py::get_player_value_explain()
// Payload owner: src/api/source_weighting_explain.py::player_explain()
export const dynamic = "force-dynamic";

export async function GET(request, { params }) {
  const { player } = await params;
  const id = String(player ?? "").trim();
  // A dot segment would be resolved by URL() and step out of /api/players/.
  if (!id || id === "." || id === "..") {
    return NextResponse.json({ error: "player_not_found", player: id }, { status: 404 });
  }
  try {
    const { data, status } = await proxyGet(
      `/api/players/${encodeURIComponent(id)}/value-explain`,
      {
        cookie: request.headers.get("cookie") || "",
        // Leave-one-out re-runs the aggregator per voter; still sub-second,
        // but the first call after a board load can be slower.
        timeoutMs: 15000,
      },
    );
    return NextResponse.json(data, {
      status,
      headers: { "Cache-Control": "no-store, private" },
    });
  } catch (err) {
    return NextResponse.json(
      { error: "value_explain_unavailable", detail: err?.message },
      { status: 503, headers: { "Cache-Control": "no-store, private" } },
    );
  }
}

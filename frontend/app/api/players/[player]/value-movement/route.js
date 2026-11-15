import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev/E2E bridge for GET /api/players/{player}/value-movement.
//
// In production nginx routes /api/* straight to FastAPI and this file is
// never reached; it exists so the Player File's "Why it moved" disclosure
// works where Next serves /api/* itself (dev and the E2E stack).
//
// PRIVATE: the backend endpoint sits behind the session gate
// (server.py::_private_api_gate — it is not on the public allowlist), so the
// caller's cookie is forwarded. Never surface this on a public /league page.
//
// Mirrored backend endpoint: server.py::get_player_value_movement()
// Payload owner: src/history/movement.py::value_movement() via
// src/api/value_movement.py::player_value_movement()
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
      `/api/players/${encodeURIComponent(id)}/value-movement`,
      { cookie: request.headers.get("cookie") || "" },
    );
    return NextResponse.json(data, {
      status,
      headers: { "Cache-Control": "no-store, private" },
    });
  } catch (err) {
    return NextResponse.json(
      { error: "value_movement_unavailable", detail: err?.message },
      { status: 503, headers: { "Cache-Control": "no-store, private" } },
    );
  }
}

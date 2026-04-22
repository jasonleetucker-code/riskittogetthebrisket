import { ImageResponse } from "next/og";

export const runtime = "nodejs";
export const contentType = "image/png";
export const size = { width: 1200, height: 630 };
export const alt = "Player journey";

function _backend() {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
}

async function fetchPlayer(playerId) {
  try {
    const res = await fetch(
      `${_backend()}/api/public/league/player/${encodeURIComponent(playerId)}`,
      { next: { revalidate: 60 } },
    );
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export default async function PlayerOGImage({ params }) {
  const { playerId } = await params;
  const data = await fetchPlayer(playerId);
  const p = data?.player;
  const ident = p?.identity || {};
  const top = p?.totalsByOwner?.[0];

  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: "100%",
          height: "100%",
          background: "linear-gradient(135deg, #0f0a1a 0%, #1a0f2e 50%, #12264f 100%)",
          color: "#eaf2ff",
          padding: "60px 80px",
          fontFamily: "Inter, ui-sans-serif, system-ui",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", gap: 16, color: "#FFC704", fontSize: 28 }}>
          <span style={{ letterSpacing: "0.15em", textTransform: "uppercase", fontWeight: 700 }}>
            Brisket League · Player Journey
          </span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ fontSize: 96, fontWeight: 800, letterSpacing: "-0.02em", lineHeight: 0.95 }}>
            {ident.playerName || "Unknown"}
          </div>
          <div style={{ fontSize: 34, color: "#99a6c8" }}>
            {[ident.position, ident.nflTeam, ident.yearsExp !== null && ident.yearsExp !== undefined ? `${ident.yearsExp} yr exp` : null]
              .filter(Boolean)
              .join(" · ")}
          </div>
        </div>

        {top ? (
          <div
            style={{
              display: "flex",
              gap: 60,
              padding: "24px 32px",
              border: "2px solid #34d399",
              borderRadius: 20,
              background: "rgba(52,211,153,0.08)",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ fontSize: 18, color: "#99a6c8", textTransform: "uppercase", letterSpacing: "0.12em" }}>
                Top manager
              </div>
              <div style={{ fontSize: 44, fontWeight: 800 }}>{top.displayName}</div>
            </div>
            <div style={{ display: "flex", gap: 40 }}>
              <Stat label="Total pts" value={`${top.pointsTotal}`} color="#34d399" />
              <Stat label="Wks started" value={`${top.weeksStarted}`} color="#FFC704" />
              <Stat label="Wks rostered" value={`${top.weeksRostered}`} color="#eaf2ff" />
            </div>
          </div>
        ) : (
          <div style={{ fontSize: 28, color: "#99a6c8" }}>No scored weeks yet for this player.</div>
        )}

        <div style={{ display: "flex", justifyContent: "space-between", color: "#99a6c8", fontSize: 22 }}>
          <div>riskittogetthebrisket.org</div>
          {p?.ownershipArc?.length ? (
            <div>{p.ownershipArc.map((o) => o.displayName).join(" → ")}</div>
          ) : null}
        </div>
      </div>
    ),
    size,
  );
}

function Stat({ label, value, color }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "center" }}>
      <div style={{ fontSize: 16, color: "#99a6c8", textTransform: "uppercase", letterSpacing: "0.12em" }}>
        {label}
      </div>
      <div style={{ fontSize: 44, fontWeight: 800, color, fontFamily: "monospace" }}>{value}</div>
    </div>
  );
}

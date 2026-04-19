import { ImageResponse } from "next/og";

// Dynamic OG image for /league/franchise/[owner].
// Renders a branded card with the franchise name, cumulative record,
// titles, and a big championship star.  Auto-picked up by Next.js at
// the franchise route without any additional metadata wiring.

export const runtime = "nodejs";
export const contentType = "image/png";
export const size = { width: 1200, height: 630 };
export const alt = "Franchise profile";

function _backend() {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
}

async function fetchFranchise(ownerId) {
  const url = `${_backend()}/api/public/league/franchise?owner=${encodeURIComponent(ownerId)}`;
  try {
    const res = await fetch(url, { next: { revalidate: 60 } });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export default async function FranchiseOGImage({ params }) {
  const { owner } = await params;
  const ownerId = decodeURIComponent(String(owner || ""));
  const payload = await fetchFranchise(ownerId);
  const fr = payload?.franchiseDetail || payload?.data?.detail?.[ownerId];

  const name = fr?.displayName || "Franchise";
  const teamName = fr?.currentTeamName || "";
  const cum = fr?.cumulative || {};
  const record = fr
    ? `${cum.wins ?? 0}-${cum.losses ?? 0}${cum.ties ? `-${cum.ties}` : ""}`
    : "";
  const titles = cum.championships || 0;
  const seasons = cum.seasonsPlayed || 0;

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
        <div style={{ display: "flex", alignItems: "center", gap: 16, color: "#FFC62F", fontSize: 28 }}>
          <span style={{ letterSpacing: "0.15em", textTransform: "uppercase", fontWeight: 700 }}>
            Brisket League · Franchise
          </span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 24 }}>
            <div style={{ fontSize: 96, fontWeight: 800, lineHeight: 0.95, letterSpacing: "-0.02em" }}>
              {name}
            </div>
          </div>
          {teamName && (
            <div style={{ fontSize: 32, color: "#99a6c8" }}>{teamName}</div>
          )}
          <div style={{ display: "flex", gap: 48, marginTop: 20, fontSize: 30 }}>
            <Stat label="Record" value={record || "—"} color="#eaf2ff" />
            <Stat label="Titles" value={`${titles}×`} color="#fbbf24" />
            <Stat label="Seasons" value={`${seasons}`} color="#FFC62F" />
            {cum.playoffAppearances ? (
              <Stat label="Playoffs" value={`${cum.playoffAppearances}`} color="#34d399" />
            ) : null}
          </div>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", color: "#99a6c8", fontSize: 22 }}>
          <div>riskittogetthebrisket.org</div>
          <div style={{ fontFamily: "monospace" }}>
            {fr?.topRival ? `Rival: ${fr.topRival.displayName} · Index ${fr.topRival.rivalryIndex}` : ""}
          </div>
        </div>
      </div>
    ),
    size,
  );
}

function Stat({ label, value, color }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ fontSize: 18, color: "#99a6c8", textTransform: "uppercase", letterSpacing: "0.12em" }}>
        {label}
      </div>
      <div style={{ fontSize: 54, fontWeight: 800, color, fontFamily: "monospace" }}>{value}</div>
    </div>
  );
}

import { ImageResponse } from "next/og";

export const runtime = "nodejs";
export const contentType = "image/png";
export const size = { width: 1200, height: 630 };
export const alt = "Rivalry head-to-head";

function _backend() {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
}

function parsePairSlug(slug) {
  if (!slug) return { a: "", b: "" };
  const decoded = decodeURIComponent(String(slug));
  const parts = decoded.includes("-vs-")
    ? decoded.split("-vs-")
    : decoded.includes(":")
    ? decoded.split(":")
    : [decoded];
  return { a: String(parts[0] || ""), b: String(parts[1] || "") };
}

async function fetchRivalries() {
  try {
    const res = await fetch(`${_backend()}/api/public/league/rivalries`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function nameFor(managers, ownerId) {
  const m = (managers || []).find((x) => String(x.ownerId) === String(ownerId));
  return m?.displayName || m?.currentTeamName || ownerId || "—";
}

export default async function RivalryOGImage({ params }) {
  const { pair } = await params;
  const { a, b } = parsePairSlug(pair);
  const data = await fetchRivalries();
  const managers = data?.league?.managers || [];
  const detail = (data?.data?.rivalries || []).find((r) => {
    const ids = new Set((r.ownerIds || []).map(String));
    return ids.has(a) && ids.has(b);
  });

  const nameA = nameFor(managers, a);
  const nameB = nameFor(managers, b);
  const record = detail
    ? `${detail.winsA}–${detail.winsB}${detail.ties ? `–${detail.ties}` : ""}`
    : "—";
  const index = detail?.rivalryIndex ?? "—";
  const meetings = detail?.totalMeetings ?? 0;
  const playoffMeetings = detail?.playoffMeetings ?? 0;

  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: "100%",
          height: "100%",
          background: "linear-gradient(135deg, #0f0a1a 0%, #1a0f22 50%, #1a0f2e 100%)",
          color: "#eaf2ff",
          padding: "60px 80px",
          fontFamily: "Inter, ui-sans-serif, system-ui",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", gap: 16, color: "#f87171", fontSize: 28 }}>
          <span style={{ letterSpacing: "0.15em", textTransform: "uppercase", fontWeight: 700 }}>
            Brisket League · Rivalry
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 40, justifyContent: "center" }}>
          <div style={{ fontSize: 72, fontWeight: 800, textAlign: "right", flex: 1, lineHeight: 0.95 }}>
            {nameA}
          </div>
          <div style={{ fontSize: 72, fontWeight: 800, color: "#f87171" }}>vs</div>
          <div style={{ fontSize: 72, fontWeight: 800, textAlign: "left", flex: 1, lineHeight: 0.95 }}>
            {nameB}
          </div>
        </div>

        <div style={{ display: "flex", gap: 60, justifyContent: "center", fontSize: 34 }}>
          <Stat label="Rivalry Index" value={String(index)} color="#fbbf24" />
          <Stat label="Meetings" value={String(meetings)} color="#eaf2ff" />
          <Stat label="Playoff" value={String(playoffMeetings)} color="#FFC704" />
          <Stat label="Series" value={record} color="#34d399" />
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", color: "#99a6c8", fontSize: 22 }}>
          <div>riskittogetthebrisket.org</div>
          <div style={{ fontFamily: "monospace" }}>
            {detail?.closestGame ? `Closest: ${detail.closestGame.margin} pts` : ""}
          </div>
        </div>
      </div>
    ),
    size,
  );
}

function Stat({ label, value, color }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "center" }}>
      <div style={{ fontSize: 18, color: "#99a6c8", textTransform: "uppercase", letterSpacing: "0.12em" }}>
        {label}
      </div>
      <div style={{ fontSize: 62, fontWeight: 800, color, fontFamily: "monospace" }}>{value}</div>
    </div>
  );
}

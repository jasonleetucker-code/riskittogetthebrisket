import { ImageResponse } from "next/og";

export const runtime = "nodejs";
export const contentType = "image/png";
export const size = { width: 1200, height: 630 };
export const alt = "Matchup recap";

function _backend() {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
}

async function fetchMatchup(season, week, matchupId) {
  try {
    const res = await fetch(
      `${_backend()}/api/public/league/matchup/${encodeURIComponent(season)}/${encodeURIComponent(week)}/${encodeURIComponent(matchupId)}`,
      { next: { revalidate: 60 } },
    );
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export default async function MatchupOGImage({ params }) {
  const { season, week, matchup } = await params;
  const data = await fetchMatchup(season, week, matchup);
  const m = data?.matchup;

  const homeName = m?.home?.displayName || "Home";
  const awayName = m?.away?.displayName || "Away";
  const homePts = m?.home?.points ?? "—";
  const awayPts = m?.away?.points ?? "—";
  const winnerIsHome = m?.winnerOwnerId === m?.home?.ownerId;
  const winnerIsAway = m?.winnerOwnerId === m?.away?.ownerId;
  const topScorer = winnerIsHome
    ? m?.home?.topScorer
    : winnerIsAway
    ? m?.away?.topScorer
    : null;

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
        <div style={{ display: "flex", color: "#FFC62F", fontSize: 28, letterSpacing: "0.15em", textTransform: "uppercase", fontWeight: 700 }}>
          {`Brisket League · ${season} Week ${week}${m?.isPlayoff ? " · Playoffs" : ""}`}
        </div>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 40 }}>
          <Side name={homeName} points={homePts} winner={winnerIsHome} />
          <div style={{ display: "flex", fontSize: 48, color: "#99a6c8", fontFamily: "monospace" }}>—</div>
          <Side name={awayName} points={awayPts} winner={winnerIsAway} />
        </div>

        <div style={{ display: "flex", fontSize: 28, color: "#eaf2ff", fontWeight: 700, paddingInline: 40, justifyContent: "center" }}>
          {topScorer?.playerName
            ? `Led by ${topScorer.playerName} · ${topScorer.points} pts`
            : " "}
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", color: "#99a6c8", fontSize: 22 }}>
          <div style={{ display: "flex" }}>riskittogetthebrisket.org</div>
          <div style={{ display: "flex", fontFamily: "monospace" }}>
            {m?.margin !== undefined ? `Margin ${m.margin}` : ""}
          </div>
        </div>
      </div>
    ),
    size,
  );
}

function Side({ name, points, winner }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 12,
        padding: "24px 32px",
        borderRadius: 20,
        border: `2px solid ${winner ? "#34d399" : "#4F2683"}`,
        background: winner ? "rgba(52,211,153,0.08)" : "transparent",
        minWidth: 360,
      }}
    >
      <div style={{ display: "flex", fontSize: 40, fontWeight: 700, lineHeight: 1.05 }}>{String(name)}</div>
      <div
        style={{
          display: "flex",
          fontSize: 92,
          fontWeight: 800,
          fontFamily: "monospace",
          color: winner ? "#34d399" : "#eaf2ff",
        }}
      >
        {String(points)}
      </div>
    </div>
  );
}

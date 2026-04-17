// Server-rendered matchup recap page.  First-paint is instant — all
// data is fetched in the RSC and streamed with the page shell instead
// of appearing after a client-side useEffect.
//
// Also provides rich Open Graph / Twitter Card metadata so links to
// this page render a nice preview in Slack, iMessage, Twitter, etc.

import Link from "next/link";
import { Avatar, Card, Stat } from "../../../../shared-server.jsx";
import { buildManagerLookup, fmtPoints } from "../../../../shared-helpers.js";
import { EmptyState, PageHeader } from "@/components/ui";

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
  const url = `${_backend()}/api/public/league/matchup/${encodeURIComponent(season)}/${encodeURIComponent(week)}/${encodeURIComponent(matchupId)}`;
  try {
    const res = await fetch(url, { next: { revalidate: 60 } });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }) {
  const { season, week, matchup } = await params;
  const data = await fetchMatchup(season, week, matchup);
  if (!data || !data.matchup) {
    return {
      title: `${season} Week ${week} matchup · Brisket League`,
      description: "Public matchup recap for the Risk It To Get The Brisket dynasty league.",
    };
  }
  const m = data.matchup;
  const home = m.home?.displayName || "Home";
  const away = m.away?.displayName || "Away";
  const title = `${home} ${m.home?.points} — ${m.away?.points} ${away} · ${season} Wk ${week}`;
  const description = m.narrative || `${home} vs ${away} · ${season} Week ${week} recap.`;
  return {
    title,
    description,
    openGraph: {
      title,
      description,
      type: "article",
      siteName: "Risk It To Get The Brisket",
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
    },
  };
}

export default async function MatchupRecapPage({ params }) {
  const { season, week, matchup } = await params;
  const payload = await fetchMatchup(season, week, matchup);

  if (!payload || !payload.matchup) {
    return (
      <section>
        <div className="card">
          <EmptyState
            title="Matchup not found"
            message={`No public recap for ${season} week ${week} matchup ${matchup}.`}
          />
          <div style={{ marginTop: 10 }}>
            <Link href="/league?tab=weekly" style={{ color: "var(--cyan)" }}>
              ← All weekly recaps
            </Link>
          </div>
        </div>
      </section>
    );
  }

  const managers = buildManagerLookup(payload.league);
  const m = payload.matchup;

  return (
    <section>
      <div className="card">
        <div style={{ fontSize: "0.72rem", marginBottom: 6 }}>
          <Link href="/league" style={{ color: "var(--cyan)" }}>← League home</Link>
          {" · "}
          <Link href="/league?tab=weekly" style={{ color: "var(--cyan)" }}>
            All weekly recaps
          </Link>
        </div>
        <PageHeader
          title={`${season} · Week ${week}${m.isPlayoff ? " (playoffs)" : ""}`}
          subtitle={m.narrative}
        />
      </div>

      <div className="row" style={{ marginTop: "var(--space-md)", gap: 14 }}>
        <SideCard side={m.home} managers={managers} isWinner={m.winnerOwnerId === m.home.ownerId} />
        <SideCard side={m.away} managers={managers} isWinner={m.winnerOwnerId === m.away.ownerId} />
      </div>

      <Card title="Game summary">
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
            gap: 10,
          }}
        >
          <Stat label="Margin" value={fmtPoints(m.margin)} sub="final" />
          <Stat
            label="Winner"
            value={m.winnerOwnerId ? (
              m.home.ownerId === m.winnerOwnerId
                ? m.home.displayName
                : m.away.displayName
            ) : "Tie"}
          />
          <Stat label="Home pts" value={fmtPoints(m.home.points)} sub={m.home.displayName} />
          <Stat label="Away pts" value={fmtPoints(m.away.points)} sub={m.away.displayName} />
        </div>
      </Card>
    </section>
  );
}

function SideCard({ side, managers, isWinner }) {
  const top = side.topScorer;
  return (
    <div
      className="card"
      style={{
        flex: "1 1 380px",
        borderColor: isWinner ? "var(--cyan)" : "var(--border)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Avatar managers={managers} ownerId={side.ownerId} size={36} />
        <div>
          <div style={{ fontSize: "1.05rem", fontWeight: 800 }}>{side.displayName}</div>
          <div style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>{side.teamName}</div>
        </div>
        <div
          style={{
            marginLeft: "auto",
            fontSize: "1.4rem",
            fontWeight: 800,
            fontFamily: "var(--mono)",
            color: isWinner ? "var(--green)" : "var(--text)",
          }}
        >
          {fmtPoints(side.points)}
        </div>
      </div>

      {side.preWeekRecord && (
        <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginTop: 4 }}>
          Entered week {side.preWeekRecord.wins}-{side.preWeekRecord.losses}
          {side.preWeekRecord.ties ? `-${side.preWeekRecord.ties}` : ""}
          {side.preWeekRecord.standing ? ` · ${ordinal(side.preWeekRecord.standing)} seed` : ""}
        </div>
      )}

      {top && (
        <div style={{ marginTop: 10, fontSize: "0.78rem" }}>
          <span style={{ color: "var(--subtext)" }}>Top scorer:</span>{" "}
          <Link
            href={top.playerId ? `/league/player/${encodeURIComponent(top.playerId)}` : "#"}
            style={{ color: "var(--cyan)", fontWeight: 600 }}
          >
            {top.playerName || "—"}
          </Link>
          <span style={{ color: "var(--subtext)" }}> · {fmtPoints(top.points)} pts</span>
        </div>
      )}

      {side.biggestBenchMiss && (
        <div style={{ marginTop: 4, fontSize: "0.7rem", color: "var(--amber)" }}>
          Bench miss: {side.biggestBenchMiss.playerName} ({fmtPoints(side.biggestBenchMiss.points)})
        </div>
      )}

      <div style={{ marginTop: 10 }}>
        <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginBottom: 4 }}>Starters</div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Player</th>
                <th>Pos</th>
                <th style={{ textAlign: "right" }}>Pts</th>
              </tr>
            </thead>
            <tbody>
              {(side.starters || []).map((p, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 600 }}>
                    <Link
                      href={p.playerId ? `/league/player/${encodeURIComponent(p.playerId)}` : "#"}
                      style={{ color: "var(--cyan)" }}
                    >
                      {p.playerName}
                    </Link>
                  </td>
                  <td style={{ fontFamily: "var(--mono)" }}>{p.position}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtPoints(p.points)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{ marginTop: 10 }}>
        <Link
          href={`/league/franchise/${encodeURIComponent(side.ownerId)}`}
          style={{ color: "var(--cyan)", fontSize: "0.7rem" }}
        >
          Franchise page →
        </Link>
      </div>
    </div>
  );
}

function ordinal(n) {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

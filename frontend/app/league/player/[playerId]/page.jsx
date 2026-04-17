// Server-rendered player-journey page.
//
// Given a Sleeper player_id, follows them across every roster, trade,
// waiver, and starter-slot in the 2-season window.  No one else in
// dynasty tooling surfaces this — the whole point is that all the data
// is already in our public snapshot.

import Link from "next/link";
import { Avatar, Card, Stat } from "../../shared-server.jsx";
import { buildManagerLookup, fmtPoints } from "../../shared-helpers.js";
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

async function fetchPlayer(playerId) {
  const url = `${_backend()}/api/public/league/player/${encodeURIComponent(playerId)}`;
  try {
    const res = await fetch(url, { next: { revalidate: 60 } });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }) {
  const { playerId } = await params;
  const payload = await fetchPlayer(playerId);
  if (!payload || !payload.player) {
    return {
      title: `Player journey · Brisket League`,
      description: "Public player transaction + scoring history across the Brisket dynasty league.",
    };
  }
  const p = payload.player.identity;
  const totals = payload.player.totalsByOwner || [];
  const top = totals[0];
  const title = `${p.playerName} (${p.position}) — league journey`;
  const description = top
    ? `${p.playerName} scored ${top.pointsTotal} pts for ${top.displayName} across ${top.weeksRostered} weeks.`
    : `${p.playerName}'s transaction history in the Brisket dynasty league.`;
  return {
    title,
    description,
    openGraph: { title, description, type: "article", siteName: "Risk It To Get The Brisket" },
    twitter: { card: "summary", title, description },
  };
}

export default async function PlayerJourneyPage({ params }) {
  const { playerId } = await params;
  const payload = await fetchPlayer(playerId);

  if (!payload || !payload.player) {
    return (
      <section>
        <div className="card">
          <EmptyState
            title="Player not found"
            message={`No public journey data for player ${playerId}.`}
          />
          <div style={{ marginTop: 10 }}>
            <Link href="/league" style={{ color: "var(--cyan)" }}>← Back to league</Link>
          </div>
        </div>
      </section>
    );
  }

  const managers = buildManagerLookup(payload.league);
  const p = payload.player;
  const ident = p.identity;

  return (
    <section>
      <div className="card">
        <div style={{ fontSize: "0.72rem", marginBottom: 6 }}>
          <Link href="/league" style={{ color: "var(--cyan)" }}>← League home</Link>
        </div>
        <PageHeader
          title={ident.playerName || ident.playerId}
          subtitle={[
            ident.position || "?",
            ident.nflTeam || null,
            ident.yearsExp !== null && ident.yearsExp !== undefined
              ? `${ident.yearsExp} yr${ident.yearsExp === 1 ? "" : "s"} exp`
              : null,
          ].filter(Boolean).join(" · ")}
        />
      </div>

      {p.draftOrigin && (
        <Card title="Drafted">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Avatar managers={managers} ownerId={p.draftOrigin.ownerId} size={28} />
            <div>
              <div style={{ fontWeight: 700 }}>{p.draftOrigin.displayName}</div>
              <div style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>
                {p.draftOrigin.season} rookie draft · Round {p.draftOrigin.round} · Pick {p.draftOrigin.pickNo}
              </div>
            </div>
          </div>
        </Card>
      )}

      {p.ownershipArc && p.ownershipArc.length > 0 && (
        <Card title="Ownership arc" subtitle="Managers who rostered this player, in order">
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            {p.ownershipArc.map((o, i) => (
              <div key={o.ownerId} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Link
                  href={`/league/franchise/${encodeURIComponent(o.ownerId)}`}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    color: "var(--cyan)",
                    fontWeight: 600,
                  }}
                >
                  <Avatar managers={managers} ownerId={o.ownerId} size={22} />
                  {o.displayName}
                </Link>
                {i < p.ownershipArc.length - 1 && (
                  <span style={{ color: "var(--subtext)", fontSize: "1.1rem" }}>→</span>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card title="Impact by manager" subtitle="Points this player scored while on each roster">
        {p.totalsByOwner.length === 0 ? (
          <div style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>
            No scored weeks on record yet for this player.
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Manager</th>
                  <th style={{ textAlign: "right" }}>Pts started</th>
                  <th style={{ textAlign: "right" }}>Pts benched</th>
                  <th style={{ textAlign: "right" }}>Total pts</th>
                  <th style={{ textAlign: "right" }}>Wks started</th>
                  <th style={{ textAlign: "right" }}>Wks rostered</th>
                </tr>
              </thead>
              <tbody>
                {p.totalsByOwner.map((row) => (
                  <tr key={row.ownerId}>
                    <td style={{ fontWeight: 600 }}>
                      <Link
                        href={`/league/franchise/${encodeURIComponent(row.ownerId)}`}
                        style={{ color: "var(--cyan)" }}
                      >
                        {row.displayName}
                      </Link>
                    </td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                      {fmtPoints(row.pointsStarted)}
                    </td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--subtext)" }}>
                      {fmtPoints(row.pointsBenched)}
                    </td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--cyan)" }}>
                      {fmtPoints(row.pointsTotal)}
                    </td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.weeksStarted}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.weeksRostered}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="row" style={{ marginTop: "var(--space-md)", gap: 14 }}>
        {p.bestWeek && (
          <div className="card" style={{ flex: "1 1 260px" }}>
            <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase" }}>
              Best week
            </div>
            <div style={{ fontSize: "1.1rem", fontWeight: 800, marginTop: 4 }}>
              {fmtPoints(p.bestWeek.points)} pts
            </div>
            <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 2 }}>
              {p.bestWeek.season} Week {p.bestWeek.week} · {p.bestWeek.displayName}
            </div>
          </div>
        )}
        {p.worstWeek && (
          <div className="card" style={{ flex: "1 1 260px" }}>
            <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase" }}>
              Worst week
            </div>
            <div style={{ fontSize: "1.1rem", fontWeight: 800, marginTop: 4 }}>
              {fmtPoints(p.worstWeek.points)} pts
            </div>
            <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 2 }}>
              {p.worstWeek.season} Week {p.worstWeek.week} · {p.worstWeek.displayName}
            </div>
          </div>
        )}
      </div>

      <Card title="Transaction timeline" subtitle="Every trade, waiver, and FA event involving this player">
        {p.events.length === 0 ? (
          <div style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>
            No public transactions on record for this player in the 2-season window.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {p.events.map((e, i) => (
              <div
                key={`${e.transactionId}-${i}`}
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius)",
                  padding: 10,
                }}
              >
                <div style={{ fontSize: "0.64rem", color: "var(--subtext)" }}>
                  {e.season} · Wk {e.week} · {e.txType} · {e.kind}
                </div>
                <div style={{ fontSize: "0.82rem", marginTop: 2 }}>
                  {e.kind === "add" ? "Added by " : "Dropped by "}
                  <Link
                    href={`/league/franchise/${encodeURIComponent(e.toOwnerId || e.fromOwnerId || "")}`}
                    style={{ color: "var(--cyan)", fontWeight: 600 }}
                  >
                    {e.toDisplayName || e.fromDisplayName || "—"}
                  </Link>
                  {e.faabBid !== null && e.faabBid !== undefined && (
                    <span style={{ color: "var(--subtext)", fontSize: "0.72rem" }}>
                      {" "}· FAAB ${e.faabBid}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </section>
  );
}

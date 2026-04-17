"use client";

// HistorySection — public /league tab view.
// Extracted from page.jsx to keep the tab file lean.

import { Avatar, Card, EmptyCard, ManagerInline, MiniLeaderboard, fmtNumber } from "../shared.jsx";

function HistorySection({ managers, data, onNavigate }) {
  const hof = data?.hallOfFame || [];
  const seasons = data?.seasons || [];
  const champs = data?.championsBySeason || [];
  if (!hof.length && !seasons.length) return <EmptyCard label="Hall of Fame" />;

  const byPoints = [...hof].sort((a, b) => b.pointsFor - a.pointsFor);
  const byPlayoffs = [...hof].sort((a, b) => b.playoffAppearances - a.playoffAppearances);
  const byFinals = [...hof].sort((a, b) => b.finalsAppearances - a.finalsAppearances);

  return (
    <>
      {champs.length > 0 && (
        <Card title="Champion timeline" subtitle="Winners of the final playoff matchup">
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {champs.map((c) => (
              <div
                key={c.season}
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius)",
                  padding: 10,
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  cursor: "pointer",
                }}
                onClick={() => onNavigate("franchise", { owner: c.ownerId })}
              >
                <Avatar managers={managers} ownerId={c.ownerId} size={36} />
                <div>
                  <div style={{ fontSize: "0.66rem", color: "var(--subtext)" }}>{c.season}</div>
                  <div style={{ fontWeight: 700, fontSize: "1rem" }}>{c.displayName}</div>
                  <div style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>{c.teamName}</div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card title="Hall of Fame" subtitle="Cumulative stats across the last 2 seasons">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th style={{ textAlign: "left" }}>Manager</th>
                <th style={{ textAlign: "right" }}>Seasons</th>
                <th style={{ textAlign: "right" }}>Record</th>
                <th style={{ textAlign: "right" }}>Titles</th>
                <th style={{ textAlign: "right" }}>Finals</th>
                <th style={{ textAlign: "right" }}>Playoffs</th>
                <th style={{ textAlign: "right" }}>Reg 1st</th>
                <th style={{ textAlign: "right" }}>Points</th>
              </tr>
            </thead>
            <tbody>
              {hof.map((row) => (
                <tr
                  key={row.ownerId}
                  onClick={() => onNavigate("franchise", { owner: row.ownerId })}
                  style={{ cursor: "pointer" }}
                >
                  <td style={{ fontWeight: 600 }}>
                    <ManagerInline managers={managers} ownerId={row.ownerId} compact />
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.seasonsPlayed}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {row.wins}-{row.losses}{row.ties ? `-${row.ties}` : ""}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.championships || 0}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.finalsAppearances || 0}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.playoffAppearances || 0}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.regularSeasonFirstPlace || 0}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtNumber(row.pointsFor, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="row" style={{ marginTop: "var(--space-md)", gap: 14 }}>
        <MiniLeaderboard
          managers={managers}
          title="Points leaders"
          rows={byPoints}
          metric={(r) => fmtNumber(r.pointsFor, 1)}
          onRowClick={(ownerId) => onNavigate("franchise", { owner: ownerId })}
        />
        <MiniLeaderboard
          managers={managers}
          title="Playoff appearances"
          rows={byPlayoffs}
          metric={(r) => r.playoffAppearances || 0}
          onRowClick={(ownerId) => onNavigate("franchise", { owner: ownerId })}
        />
        <MiniLeaderboard
          managers={managers}
          title="Finals appearances"
          rows={byFinals}
          metric={(r) => r.finalsAppearances || 0}
          onRowClick={(ownerId) => onNavigate("franchise", { owner: ownerId })}
        />
      </div>

      {seasons.map((s) => (
        <Card
          key={s.leagueId}
          title={`${s.season} season`}
          subtitle={[
            s.champion ? `Champion: ${s.champion.displayName}` : null,
            s.topSeed ? `Top seed: ${s.topSeed.displayName}` : null,
            s.regularSeasonPointsLeader ? `Points leader: ${s.regularSeasonPointsLeader.displayName}` : null,
          ].filter(Boolean).join(" · ")}
        >
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Team</th>
                  <th style={{ textAlign: "right" }}>W-L-T</th>
                  <th style={{ textAlign: "right" }}>PF</th>
                  <th style={{ textAlign: "right" }}>PA</th>
                  <th style={{ textAlign: "right" }}>Seed</th>
                  <th style={{ textAlign: "right" }}>Final</th>
                </tr>
              </thead>
              <tbody>
                {(s.standings || []).map((row) => (
                  <tr
                    key={row.ownerId}
                    onClick={() => onNavigate("franchise", { owner: row.ownerId })}
                    style={{ cursor: "pointer" }}
                  >
                    <td style={{ fontWeight: 600 }}>
                      <ManagerInline managers={managers} ownerId={row.ownerId} compact />
                      <span style={{ marginLeft: 6, color: "var(--subtext)", fontSize: "0.7rem" }}>
                        {row.teamName}
                      </span>
                      {row.madePlayoffs && (
                        <span style={{ marginLeft: 6, fontSize: "0.65rem", color: "var(--green)" }}>★</span>
                      )}
                    </td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                      {row.wins}-{row.losses}{row.ties ? `-${row.ties}` : ""}
                    </td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtNumber(row.pointsFor, 1)}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtNumber(row.pointsAgainst, 1)}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.standing}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.finalPlace ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}
    </>
  );
}

export default HistorySection;

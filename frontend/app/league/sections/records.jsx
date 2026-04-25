"use client";

// RecordsSection — public /league tab view.
// Extracted from page.jsx to keep the tab file lean.

import { Card, EmptyCard, fmtNumber, fmtPoints } from "../shared.jsx";

const POSITION_LABELS = {
  QB: "Quarterbacks",
  RB: "Running backs",
  WR: "Wide receivers",
  TE: "Tight ends",
  K:  "Kickers",
  DL: "Defensive linemen",
  LB: "Linebackers",
  DB: "Defensive backs",
};

function RecordsSection({ data }) {
  if (!data) return <EmptyCard label="Records" />;

  const groups = [
    { title: "Highest single-week scores", key: "singleWeekHighest" },
    { title: "Lowest single-week scores", key: "singleWeekLowest" },
    { title: "Biggest margin of victory", key: "biggestMargin" },
    { title: "Narrowest victories", key: "narrowestVictory" },
    { title: "Most points in a loss", key: "mostPointsInLoss" },
    { title: "Fewest points in a win", key: "fewestPointsInWin" },
  ];

  const playerPositions =
    data.playerRecordPositions ||
    Object.keys(data.playerRecords || {});
  const playerRecordsHasContent = playerPositions.some(
    (pos) => (data.playerRecords?.[pos] || []).length > 0,
  );

  return (
    <>
      <Card title="Record book" subtitle="Single-game extremes (each row is one NFL week)">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 10 }}>
          {groups.map((g) => (
            <div key={g.key} style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}>
              <div style={{ fontWeight: 700, marginBottom: 6, fontSize: "0.86rem" }}>{g.title}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                {(data[g.key] || []).slice(0, 5).map((r, i) => (
                  <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.74rem" }}>
                    <span>
                      <span style={{ color: "var(--subtext)", marginRight: 4 }}>{i + 1}.</span>
                      {r.teamName}
                      <span style={{ color: "var(--subtext)", marginLeft: 4 }}>
                        ({r.season} wk {r.week})
                      </span>
                    </span>
                    <span style={{ fontFamily: "var(--mono)", color: "var(--cyan)" }}>
                      {r.margin !== undefined && g.key.toLowerCase().includes("margin")
                        ? `${fmtPoints(r.margin)} (${fmtPoints(r.points)})`
                        : fmtPoints(r.points)}
                    </span>
                  </div>
                ))}
                {(data[g.key] || []).length === 0 && (
                  <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>—</div>
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Season totals" subtitle="Most points scored / allowed in a regular season (no playoffs)">
        <div className="row">
          <div className="card" style={{ flex: "1 1 260px" }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Most points in a season</div>
            {(data.mostPointsInSeason || []).slice(0, 5).map((r, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.76rem", padding: "2px 0" }}>
                <span>
                  <span style={{ color: "var(--subtext)", fontFamily: "var(--mono)", marginRight: 6 }}>{i + 1}.</span>
                  {r.displayName} <span style={{ color: "var(--subtext)" }}>({r.season})</span>
                </span>
                <span style={{ fontFamily: "var(--mono)", color: "var(--cyan)" }}>{fmtNumber(r.totalPoints, 1)}</span>
              </div>
            ))}
          </div>
          <div className="card" style={{ flex: "1 1 260px" }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Most points against in a season</div>
            {(data.mostPointsAgainstInSeason || []).slice(0, 5).map((r, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.76rem", padding: "2px 0" }}>
                <span>
                  <span style={{ color: "var(--subtext)", fontFamily: "var(--mono)", marginRight: 6 }}>{i + 1}.</span>
                  {r.displayName} <span style={{ color: "var(--subtext)" }}>({r.season})</span>
                </span>
                <span style={{ fontFamily: "var(--mono)", color: "var(--red)" }}>{fmtNumber(r.totalPointsAgainst, 1)}</span>
              </div>
            ))}
          </div>
        </div>
      </Card>

      {playerRecordsHasContent && (
        <Card
          title="Player records · single-week"
          subtitle="Top starter-only single-week scores by position (regular season)"
        >
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 10 }}>
            {playerPositions.map((pos) => {
              const rows = data.playerRecords?.[pos] || [];
              if (!rows.length) return null;
              return (
                <div key={pos} style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}>
                  <div style={{ fontWeight: 700, marginBottom: 6, fontSize: "0.86rem" }}>
                    {POSITION_LABELS[pos] || pos}
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                    {rows.slice(0, 5).map((r, i) => (
                      <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.74rem" }}>
                        <span>
                          <span style={{ color: "var(--subtext)", marginRight: 4 }}>{i + 1}.</span>
                          {r.playerName || r.playerId}
                          <span style={{ color: "var(--subtext)", marginLeft: 4 }}>
                            ({r.displayName}, {r.season} wk {r.week})
                          </span>
                        </span>
                        <span style={{ fontFamily: "var(--mono)", color: "var(--cyan)" }}>
                          {fmtPoints(r.points)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      <Card title="Streaks" subtitle="Longest consecutive wins / losses (ties end streaks)">
        <div className="row">
          <div className="card" style={{ flex: "1 1 260px" }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Longest win streaks</div>
            {(data.longestWinStreaks || []).slice(0, 5).map((r, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.76rem", padding: "2px 0" }}>
                <span>
                  <span style={{ color: "var(--subtext)", fontFamily: "var(--mono)", marginRight: 6 }}>{i + 1}.</span>
                  {r.displayName}
                </span>
                <span style={{ fontFamily: "var(--mono)", color: "var(--green)" }}>{r.length} wins</span>
              </div>
            ))}
          </div>
          <div className="card" style={{ flex: "1 1 260px" }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Longest losing streaks</div>
            {(data.longestLossStreaks || []).slice(0, 5).map((r, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.76rem", padding: "2px 0" }}>
                <span>
                  <span style={{ color: "var(--subtext)", fontFamily: "var(--mono)", marginRight: 6 }}>{i + 1}.</span>
                  {r.displayName}
                </span>
                <span style={{ fontFamily: "var(--mono)", color: "var(--red)" }}>{r.length} losses</span>
              </div>
            ))}
          </div>
        </div>
      </Card>

      <Card title="Transactions & FAAB" subtitle="Season-level activity records">
        <div className="row">
          <div className="card" style={{ flex: "1 1 220px" }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Most trades in a season</div>
            {(data.mostTradesInSeason || []).slice(0, 5).map((r, i) => (
              <div key={i} style={{ fontSize: "0.74rem", padding: "2px 0" }}>
                {r.season}: <strong>{r.tradeCount}</strong> trades
              </div>
            ))}
          </div>
          <div className="card" style={{ flex: "1 1 220px" }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Most waivers in a season</div>
            {(data.mostWaiversInSeason || []).slice(0, 5).map((r, i) => (
              <div key={i} style={{ fontSize: "0.74rem", padding: "2px 0" }}>
                {r.season}: <strong>{r.waiverCount}</strong> waivers
              </div>
            ))}
          </div>
          <div className="card" style={{ flex: "1 1 220px" }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Largest FAAB bids</div>
            {(data.largestFaabBid || []).slice(0, 5).map((r, i) => (
              <div key={i} style={{ fontSize: "0.74rem", padding: "2px 0" }}>
                ${r.bid} · {r.displayName} · {r.playerName || r.playerId}
              </div>
            ))}
            {(!data.largestFaabBid || data.largestFaabBid.length === 0) && (
              <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>No FAAB bids on file.</div>
            )}
          </div>
        </div>
      </Card>

      {data.playoffRecords && (
        <Card title="Playoff records">
          <div className="row">
            <div className="card" style={{ flex: "1 1 260px" }}>
              <div style={{ fontWeight: 700, marginBottom: 8 }}>Most points in playoffs</div>
              {(data.playoffRecords.mostPointsInPlayoffs || []).slice(0, 5).map((r, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.76rem", padding: "2px 0" }}>
                  <span>{r.teamName}</span>
                  <span style={{ fontFamily: "var(--mono)", color: "var(--cyan)" }}>{fmtPoints(r.points)}</span>
                </div>
              ))}
            </div>
            <div className="card" style={{ flex: "1 1 260px" }}>
              <div style={{ fontWeight: 700, marginBottom: 8 }}>Most playoff wins in a season</div>
              {(data.playoffRecords.mostPlayoffWinsInSeason || []).slice(0, 5).map((r, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.76rem", padding: "2px 0" }}>
                  <span>{r.displayName} <span style={{ color: "var(--subtext)" }}>({r.season})</span></span>
                  <span style={{ fontFamily: "var(--mono)", color: "var(--cyan)" }}>{r.playoffWins}</span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}
    </>
  );
}

export default RecordsSection;

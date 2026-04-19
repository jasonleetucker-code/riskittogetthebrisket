"use client";

// DraftSection — public /league tab view.
// Extracted from page.jsx to keep the tab file lean.

import { useEffect, useState } from "react";
import { Card, EmptyCard } from "../shared.jsx";

function DraftSection({ data, initialOwner, setOwner }) {
  if (!data) return <EmptyCard label="Drafts" />;
  const board = data.stockpileLeaderboard || [];
  const ownership = data.pickOwnership || {};
  const defaultOwner = board.find((r) => r.ownerId === initialOwner)?.ownerId
    || board[0]?.ownerId
    || "";
  const [selectedOwner, setSelectedOwnerInner] = useState(defaultOwner);
  useEffect(() => {
    if (initialOwner && ownership[initialOwner] && initialOwner !== selectedOwner) {
      setSelectedOwnerInner(initialOwner);
    }
  }, [initialOwner]); // eslint-disable-line react-hooks/exhaustive-deps
  function selectOwner(ownerId) {
    setSelectedOwnerInner(ownerId);
    if (setOwner) setOwner(ownerId);
  }
  const drafts = data.drafts || [];
  const ownerPicks = ownership[selectedOwner] || [];

  return (
    <>
      <Card title="Weighted pick stockpile" subtitle="1st round = 4 pts, 2nd = 3, 3rd = 2, 4th+ = 1">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Manager</th>
                <th style={{ textAlign: "right" }}>Total picks</th>
                <th style={{ textAlign: "right" }}>Weighted</th>
              </tr>
            </thead>
            <tbody>
              {board.map((row, i) => (
                <tr
                  key={row.ownerId}
                  onClick={() => selectOwner(row.ownerId)}
                  style={{
                    cursor: "pointer",
                    background: selectedOwner === row.ownerId ? "rgba(255, 198, 47, 0.08)" : "transparent",
                  }}
                >
                  <td style={{ fontWeight: 600 }}>
                    <span style={{ color: "var(--subtext)", marginRight: 6, fontFamily: "var(--mono)" }}>{i + 1}.</span>
                    {row.displayName}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.totalPicks}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--cyan)" }}>{row.weightedScore}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {selectedOwner && (
        <Card
          title="Pick inventory"
          subtitle={`Picks owned by ${board.find((r) => r.ownerId === selectedOwner)?.displayName || "this manager"}`}
        >
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {ownerPicks.length === 0 && (
              <div style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>No tracked picks.</div>
            )}
            {ownerPicks.map((p, i) => (
              <span
                key={i}
                style={{
                  fontFamily: "var(--mono)",
                  fontSize: "0.72rem",
                  border: "1px solid var(--border)",
                  padding: "3px 8px",
                  borderRadius: 4,
                  color: p.isTraded ? "var(--amber)" : "var(--text)",
                }}
              >
                {p.label}{p.isTraded ? "*" : ""}
              </span>
            ))}
          </div>
          <div style={{ fontSize: "0.66rem", color: "var(--subtext)", marginTop: 6 }}>
            Amber picks (*) were acquired via trade.
          </div>
        </Card>
      )}

      {data.mostTradedPick && (
        <Card title="Most-traded pick">
          <div>
            <div style={{ fontWeight: 700, fontSize: "0.94rem" }}>{data.mostTradedPick.label}</div>
            <div style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>
              Changed hands {data.mostTradedPick.moveCount} time{data.mostTradedPick.moveCount === 1 ? "" : "s"}
            </div>
          </div>
        </Card>
      )}

      {drafts.map((d) => (
        <Card
          key={d.draftId}
          title={`${d.season} rookie draft`}
          subtitle={`${d.status} · ${d.rounds || "?"} rounds · ${(d.picks || []).length} picks`}
        >
          {d.firstRoundRecap && d.firstRoundRecap.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>First round recap</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 6 }}>
                {d.firstRoundRecap.map((p, i) => (
                  <div key={i} style={{ border: "1px solid var(--border)", borderRadius: 6, padding: 8 }}>
                    <div style={{ fontSize: "0.66rem", color: "var(--subtext)", fontFamily: "var(--mono)" }}>
                      {d.season} 1.{String(p.pickNo).padStart(2, "0")}
                    </div>
                    <div style={{ fontWeight: 700 }}>{p.playerName || "Unknown"}</div>
                    <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>
                      {p.position || "?"}{p.nflTeam ? ` · ${p.nflTeam}` : ""} · {p.teamName}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ textAlign: "right" }}>Pick</th>
                  <th>Player</th>
                  <th>Pos</th>
                  <th>NFL</th>
                  <th>Team</th>
                </tr>
              </thead>
              <tbody>
                {(d.picks || []).map((p, i) => (
                  <tr key={i}>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                      {p.round}.{String(p.pickNo).padStart(2, "0")}
                    </td>
                    <td>{p.playerName || "—"}</td>
                    <td style={{ fontFamily: "var(--mono)" }}>{p.position || ""}</td>
                    <td style={{ fontFamily: "var(--mono)" }}>{p.nflTeam || ""}</td>
                    <td>{p.teamName}</td>
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

export default DraftSection;

"use client";

// Division-title odds beside the playoff-odds chart (owner decision
// 2026-11-08).  Pure rendering of the public ``playoffOdds`` section:
// ``frontend/lib/division-odds.js`` groups and formats, the backend computes.

import { divisionOddsGroups, divisionRuleNote, fmtSimulatedShare } from "@/lib/division-odds";

export default function DivisionOddsTable({ data }) {
  const groups = divisionOddsGroups(data);
  if (!groups) return null;
  const final = data?.scheduleCertainty === "final";
  const note = divisionRuleNote(data);
  return (
    <div data-testid="division-odds">
      {note ? (
        <p style={{ fontSize: "0.72rem", color: "var(--subtext)", margin: "0 0 8px" }}>{note}</p>
      ) : null}
      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
        {groups.map((g) => (
          <table key={g.division} style={{ width: "100%", fontSize: "0.76rem", borderCollapse: "collapse" }}>
            <caption style={{ textAlign: "left", fontWeight: 600, padding: "0 0 4px" }}>{g.name}</caption>
            <thead>
              <tr style={{ color: "var(--subtext)" }}>
                <th style={{ textAlign: "left", fontWeight: 500 }}>Team</th>
                <th style={{ textAlign: "right", fontWeight: 500 }} title="Simulated chance to win the division">
                  Div title
                </th>
                <th style={{ textAlign: "right", fontWeight: 500 }} title="Simulated chance to make the playoffs">
                  Playoffs
                </th>
              </tr>
            </thead>
            <tbody>
              {g.teams.map((t) => (
                <tr key={t.ownerId}>
                  <td>{t.displayName || t.ownerId}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {fmtSimulatedShare(t.divisionChampionProbability, { final })}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--subtext)" }}>
                    {fmtSimulatedShare(t.playoffProbability, { final })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
      </div>
    </div>
  );
}

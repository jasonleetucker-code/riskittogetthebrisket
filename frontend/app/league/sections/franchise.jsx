"use client";

// FranchiseSection — public /league tab view.
// Extracted from page.jsx to keep the tab file lean.

import { useEffect, useState } from "react";
import { Avatar, Card, EmptyCard, Stat, fmtNumber } from "../shared.jsx";
import FranchiseTrajectory from "@/components/graphs/FranchiseTrajectory";

function FranchiseSection({ managers, data, onNavigate, initialOwner, setOwner }) {
  const index = data?.index || [];
  const detail = data?.detail || {};
  const initial = initialOwner && detail[initialOwner] ? initialOwner : (index[0]?.ownerId || "");
  const [selected, setSelectedInner] = useState(initial);

  // If the URL owner changes externally (back nav), reflect it.
  useEffect(() => {
    if (initialOwner && detail[initialOwner] && initialOwner !== selected) {
      setSelectedInner(initialOwner);
    }
  }, [initialOwner]); // eslint-disable-line react-hooks/exhaustive-deps

  function selectOwner(ownerId) {
    setSelectedInner(ownerId);
    if (setOwner) setOwner(ownerId);
  }

  if (!index.length) return <EmptyCard label="Franchises" />;
  const fr = detail[selected] || null;

  return (
    <>
      <Card title="Franchise index" subtitle="Sorted by titles, then best finish, then wins">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
          {index.map((row) => (
            <div
              key={row.ownerId}
              onClick={() => selectOwner(row.ownerId)}
              style={{
                border: "1px solid",
                borderColor: selected === row.ownerId ? "var(--cyan)" : "var(--border)",
                borderRadius: "var(--radius)",
                padding: 10,
                cursor: "pointer",
                background: selected === row.ownerId ? "rgba(255, 198, 47, 0.08)" : "transparent",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Avatar managers={managers} ownerId={row.ownerId} size={28} />
                <div>
                  <div style={{ fontWeight: 700 }}>{row.displayName}</div>
                  <div style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>{row.currentTeamName}</div>
                </div>
              </div>
              <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginTop: 6 }}>
                {row.championships}× ★ · {row.wins}-{row.losses} · {row.seasonsPlayed} seasons
              </div>
            </div>
          ))}
        </div>
      </Card>

      {fr && (
        <Card
          title={fr.displayName}
          subtitle={`Current: ${fr.currentTeamName || "—"}${fr.currentLeagueId ? ` · League id ${fr.currentLeagueId.slice(-6)}` : ""}`}
          action={
            fr.topRival && (
              <span style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>
                Top rival:{" "}
                <strong style={{ color: "var(--cyan)", cursor: "pointer" }} onClick={() => onNavigate("rivalries")}>
                  {fr.topRival.displayName}
                </strong>{" "}
                · Index {fr.topRival.rivalryIndex}
              </span>
            )
          }
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
            <Avatar managers={managers} ownerId={selected} size={56} />
            <div style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>
              Owner ID: <span style={{ fontFamily: "var(--mono)" }}>{selected}</span>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10, marginBottom: 14 }}>
            <Stat label="Seasons" value={fr.cumulative.seasonsPlayed} />
            <Stat
              label="Record"
              value={`${fr.cumulative.wins}-${fr.cumulative.losses}${fr.cumulative.ties ? `-${fr.cumulative.ties}` : ""}`}
            />
            <Stat label="Points for" value={fmtNumber(fr.cumulative.pointsFor, 1)} />
            <Stat
              label="Titles"
              value={fr.cumulative.championships}
              sub={`${fr.cumulative.finalsAppearances} finals`}
            />
            <Stat
              label="Playoffs"
              value={fr.cumulative.playoffAppearances}
              sub={`${fr.cumulative.regularSeasonFirstPlace} reg 1st`}
            />
            <Stat
              label="Trades"
              value={fr.tradeCount}
              sub={`${fr.waiverCount} waivers`}
            />
          </div>

          {fr.draftCapital && (
            <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10, marginBottom: 14 }}>
              <div style={{ fontWeight: 700, marginBottom: 6 }}>Draft capital</div>
              <div style={{ fontSize: "0.78rem", color: "var(--subtext)", marginBottom: 6 }}>
                Weighted score {fr.draftCapital.weightedScore} · {fr.draftCapital.totalPicks} owned picks
              </div>
              {(fr.draftCapital.picks || []).length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {(fr.draftCapital.picks || []).map((p, i) => (
                    <span
                      key={i}
                      style={{
                        fontFamily: "var(--mono)",
                        fontSize: "0.7rem",
                        border: "1px solid var(--border)",
                        padding: "2px 6px",
                        borderRadius: 4,
                        color: p.isTraded ? "var(--amber)" : "var(--text)",
                      }}
                    >
                      {p.label}{p.isTraded ? "*" : ""}
                    </span>
                  ))}
                </div>
              )}
              <div style={{ fontSize: "0.66rem", color: "var(--subtext)", marginTop: 6 }}>
                * acquired via trade
              </div>
            </div>
          )}

          <div style={{ fontWeight: 600, marginBottom: 6 }}>Season results</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Season</th>
                  <th>Team</th>
                  <th style={{ textAlign: "right" }}>W-L-T</th>
                  <th style={{ textAlign: "right" }}>PF</th>
                  <th style={{ textAlign: "right" }}>PA</th>
                  <th style={{ textAlign: "right" }}>Seed</th>
                  <th style={{ textAlign: "right" }}>Final</th>
                </tr>
              </thead>
              <tbody>
                {(fr.seasonResults || []).map((r, i) => (
                  <tr key={i}>
                    <td>{r.season}</td>
                    <td style={{ fontWeight: 600 }}>{r.teamName}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                      {r.wins}-{r.losses}{r.ties ? `-${r.ties}` : ""}
                    </td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtNumber(r.pointsFor, 1)}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtNumber(r.pointsAgainst, 1)}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.standing}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.finalPlace ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {(fr.aliases || []).length > 1 && (
            <div style={{ marginTop: 14, fontSize: "0.72rem", color: "var(--subtext)" }}>
              Team-name history: {(fr.aliases || []).map((a) => `${a.teamName} (${a.season})`).join(" → ")}
            </div>
          )}
        </Card>
      )}

      {fr && (fr.seasonResults || []).length > 0 && (
        <Card title="Scoring trajectory" subtitle="Points-for by season — a proxy for roster strength (no per-week roster-value snapshots available)">
          <FranchiseTrajectory
            seasons={(fr.seasonResults || []).map((r) => ({
              season: Number(r.season),
              pointsFor: r.pointsFor,
              wins: r.wins,
              madePlayoffs:
                Number.isFinite(Number(r.finalPlace)) && Number(r.finalPlace) > 0,
              finalPlace: r.finalPlace,
            }))}
          />
        </Card>
      )}
    </>
  );
}

export default FranchiseSection;

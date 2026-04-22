"use client";

import { useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useSettings } from "@/components/useSettings";
import { PageHeader, LoadingState, EmptyState } from "@/components/ui";
import {
  POS_GROUPS,
  OFFENSE_GROUPS,
  POS_GROUP_COLORS,
  POS_GROUP_LABELS,
  buildPlayerMetaMap,
  buildAllTeamSummaries,
  computeGroupAverages,
  findWaiverWireGems,
  buildLeagueEdgeMap,
  scoreTeamTiers,
  ordinal,
} from "@/lib/league-analysis";
import AgeCurveOverlay from "@/components/graphs/AgeCurveOverlay";

const VALUE_MODES = [
  { key: "full", label: "Players + Picks" },
  { key: "players", label: "Players only" },
  { key: "starters", label: "Starters only" },
];

export default function RostersPage() {
  const { rows, rawData, loading, error } = useApp();
  const { settings, update } = useSettings();
  const [valueMode, setValueMode] = useState("full");
  const [activeGroups, setActiveGroups] = useState(
    new Set(["QB", "RB", "WR", "TE", "PICKS"]),
  );

  const sleeperTeams = rawData?.sleeper?.teams || [];
  const pickAliases = rawData?.pickAliases || null;
  const myTeam = settings.selectedTeam || "";

  const playerMeta = useMemo(() => buildPlayerMetaMap(rows), [rows]);

  const teams = useMemo(
    () => buildAllTeamSummaries(sleeperTeams, playerMeta, rows, valueMode, pickAliases),
    [sleeperTeams, playerMeta, rows, valueMode, pickAliases],
  );

  // Sort by active group totals
  const sortedTeams = useMemo(() => {
    return teams
      .map((t) => ({
        ...t,
        activeTotal: POS_GROUPS.reduce(
          (s, g) => s + (activeGroups.has(g) ? (t.byGroup[g] || 0) : 0),
          0,
        ),
      }))
      .sort((a, b) => b.activeTotal - a.activeTotal);
  }, [teams, activeGroups]);

  const maxActiveTotal = sortedTeams[0]?.activeTotal || 1;

  const groupAvg = useMemo(() => computeGroupAverages(teams), [teams]);

  const waiverGems = useMemo(
    () => findWaiverWireGems(rows, sleeperTeams),
    [rows, sleeperTeams],
  );

  const leagueEdge = useMemo(
    () => buildLeagueEdgeMap(rows, sleeperTeams, myTeam),
    [rows, sleeperTeams, myTeam],
  );

  const teamTiers = useMemo(
    () => scoreTeamTiers(sleeperTeams, playerMeta, rows, pickAliases),
    [sleeperTeams, playerMeta, rows, pickAliases],
  );

  function toggleGroup(g) {
    setActiveGroups((prev) => {
      const next = new Set(prev);
      if (next.has(g)) next.delete(g);
      else next.add(g);
      return next;
    });
  }

  if (loading) return <LoadingState message="Loading roster data..." />;
  if (error) return <div className="card"><EmptyState title="Error" message={error} /></div>;

  if (!sleeperTeams.length) {
    return (
      <div className="card">
        <PageHeader title="Roster Dashboard" subtitle="Team strength rankings with position breakdowns." />
        <EmptyState title="No league data" message="Load dynasty data with a Sleeper league to see roster rankings." />
      </div>
    );
  }

  return (
    <section>
      <div className="card">
        <PageHeader
          title="Roster Dashboard"
          subtitle="Power rankings, position breakdowns, waiver wire, and trade targets."
          actions={
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <select
                className="input"
                value={myTeam}
                onChange={(e) => update("selectedTeam", e.target.value)}
                style={{ flex: 1, minWidth: 0 }}
              >
                <option value="">My team...</option>
                {sleeperTeams.map((t) => (
                  <option key={t.name} value={t.name}>{t.name}</option>
                ))}
              </select>
              <select
                className="input"
                value={valueMode}
                onChange={(e) => setValueMode(e.target.value)}
                style={{ flex: 1, minWidth: 0 }}
              >
                {VALUE_MODES.map((m) => (
                  <option key={m.key} value={m.key}>{m.label}</option>
                ))}
              </select>
            </div>
          }
        />

        {/* Position filter */}
        <div className="filter-bar" style={{ marginBottom: 12 }}>
          <span style={{ fontWeight: 600, fontSize: "0.72rem", color: "var(--subtext)" }}>Positions:</span>
          {POS_GROUPS.map((g) => (
            <label key={g} style={{ display: "flex", alignItems: "center", gap: 3, fontSize: "0.68rem", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={activeGroups.has(g)}
                onChange={() => toggleGroup(g)}
                style={{ width: 13, height: 13, accentColor: POS_GROUP_COLORS[g] }}
              />
              <span style={{ color: POS_GROUP_COLORS[g], fontWeight: 700 }}>{g}</span>
            </label>
          ))}
        </div>

        {/* Legend */}
        <div style={{ display: "flex", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
          {POS_GROUPS.filter((g) => activeGroups.has(g)).map((g) => (
            <div key={g} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: "0.62rem" }}>
              <div style={{ width: 10, height: 10, borderRadius: 2, background: POS_GROUP_COLORS[g] }} />
              {g}
            </div>
          ))}
        </div>

        {/* Team rankings table */}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th style={{ width: 28 }}>#</th>
                <th style={{ width: 140 }}>Team</th>
                <th style={{ width: 65, textAlign: "right" }}>Total</th>
                <th>Position Breakdown</th>
              </tr>
            </thead>
            <tbody>
              {sortedTeams.map((team, idx) => {
                const isMe = team.name === myTeam;
                return (
                  <tr key={team.name} style={isMe ? { background: "rgba(200, 56, 3, 0.06)" } : undefined}>
                    <td style={{ fontFamily: "var(--mono)", fontWeight: 700, color: "var(--subtext)" }}>{idx + 1}</td>
                    <td style={{ fontWeight: 700, ...(isMe ? { color: "var(--cyan)" } : {}) }}>
                      {team.name}
                      <div style={{ fontSize: "0.58rem", color: "var(--subtext)", fontWeight: 400 }}>
                        {team.playerCount} players{team.pickCount ? `, ${team.pickCount} picks` : ""}
                      </div>
                    </td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)", fontWeight: 600 }}>
                      {Math.round(team.activeTotal).toLocaleString()}
                    </td>
                    <td>
                      <div style={{ display: "flex", height: 20, borderRadius: 3, overflow: "hidden" }}>
                        {POS_GROUPS.filter((g) => activeGroups.has(g)).map((g) => {
                          const gVal = team.byGroup[g] || 0;
                          if (gVal <= 0) return null;
                          const pct = (gVal / maxActiveTotal) * 100;
                          return (
                            <div
                              key={g}
                              title={`${g}: ${Math.round(gVal).toLocaleString()}`}
                              style={{
                                width: `${pct.toFixed(1)}%`,
                                background: POS_GROUP_COLORS[g],
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                fontSize: "0.56rem",
                                color: "#fff",
                                fontWeight: 700,
                                overflow: "hidden",
                                whiteSpace: "nowrap",
                              }}
                            >
                              {pct > 5 ? `${g} ${Math.round(gVal / 1000)}k` : ""}
                            </div>
                          );
                        })}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Contender / Rebuilder Tiers */}
      {teamTiers.length > 0 && <TeamTiersCard tiers={teamTiers} myTeam={myTeam} />}

      {/* League Edge Map */}
      {leagueEdge.length > 0 && <LeagueEdgeCard edges={leagueEdge} />}

      {/* Age curve overlay — position typical age-value curves + my roster */}
      {myTeam && (() => {
        const me = sortedTeams.find((t) => t.name === myTeam);
        if (!me) return null;
        const rosterNames = new Set(
          (me.playerDetails || []).map((p) => String(p.name).toLowerCase()),
        );
        const boardRows = rows
          .filter((r) => r.pos !== "PICK" && r.pos !== "K")
          .map((r) => ({ pos: r.pos, age: r.age, rankDerivedValue: r.values?.full }));
        const rosterRows = rows
          .filter(
            (r) =>
              r.pos !== "PICK" &&
              r.pos !== "K" &&
              rosterNames.has(String(r.name).toLowerCase()),
          )
          .map((r) => ({
            pos: r.pos,
            age: r.age,
            rankDerivedValue: r.values?.full,
            name: r.name,
          }));
        return (
          <div className="card" style={{ padding: "var(--space-md)" }}>
            <h2 className="section-title">Age curves</h2>
            <p className="text-xs muted" style={{ marginTop: 4, marginBottom: "var(--space-sm)" }}>
              Typical value by age for each position (median of the live board).
              Dots are players on your roster.  Use it to spot roster-aging risk:
              a cluster of RBs past the position's value peak is a flag to sell;
              a cluster before the peak is a sign you're set up for the window.
            </p>
            <AgeCurveOverlay boardRows={boardRows} rosterRows={rosterRows} />
          </div>
        );
      })()}

      {/* Trade Targets */}
      {myTeam && <TradeTargetsCard myTeam={myTeam} teams={sortedTeams} groupAvg={groupAvg} />}

      {/* Waiver Wire Gems */}
      {waiverGems.length > 0 && <WaiverWireCard gems={waiverGems} />}
    </section>
  );
}

function TradeTargetsCard({ myTeam, teams, groupAvg }) {
  const myTeamData = teams.find((t) => t.name === myTeam);
  if (!myTeamData) return null;

  const myStrengths = {};
  OFFENSE_GROUPS.forEach((g) => {
    myStrengths[g] = groupAvg[g] > 0 ? (myTeamData.byGroup[g] || 0) / groupAvg[g] : 1;
  });

  const weakest = OFFENSE_GROUPS.slice().sort((a, b) => myStrengths[a] - myStrengths[b]);
  const strongest = OFFENSE_GROUPS.slice().sort((a, b) => myStrengths[b] - myStrengths[a]);

  // Find trade targets at weakest positions
  const needPositions = weakest.slice(0, 2);
  const targetSections = needPositions.map((needPos) => {
    const pctOfAvg = (myStrengths[needPos] * 100).toFixed(0);
    const targets = [];

    for (const otherTeam of teams) {
      if (otherTeam.name === myTeam) continue;
      const otherStrength = groupAvg[needPos] > 0 ? (otherTeam.byGroup[needPos] || 0) / groupAvg[needPos] : 0;
      if (otherStrength < 1.0) continue;

      for (const p of otherTeam.players) {
        if (p.group !== needPos || p.meta < 1200 || p.meta > 8000) continue;

        // Find what the other team needs
        let theirNeed = "";
        let worstRatio = Infinity;
        for (const g of OFFENSE_GROUPS) {
          const ratio = groupAvg[g] > 0 ? (otherTeam.byGroup[g] || 0) / groupAvg[g] : 1;
          if (ratio < worstRatio) { worstRatio = ratio; theirNeed = g; }
        }

        targets.push({
          ...p,
          teamName: otherTeam.name,
          theirNeed: worstRatio < 1.0 ? theirNeed : "",
        });
      }
    }

    targets.sort((a, b) => b.meta - a.meta);
    return { needPos, pctOfAvg, targets: targets.slice(0, 8) };
  });

  // Surplus players from strongest positions
  const surplus = (myTeamData.players || [])
    .filter((p) => strongest.slice(0, 2).includes(p.group) && p.meta >= 1500)
    .sort((a, b) => b.meta - a.meta)
    .slice(0, 6);

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, fontSize: "0.82rem", marginBottom: 10 }}>Trade Targets</div>

      {/* Strength summary */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 14 }}>
        <span className="badge" style={{ background: "var(--green-soft)", color: POS_GROUP_COLORS[strongest[0]] }}>
          Strongest: {strongest[0]} ({(myStrengths[strongest[0]] * 100).toFixed(0)}%)
        </span>
        <span className="badge" style={{ background: "var(--red-soft, rgba(220,50,50,0.1))", color: POS_GROUP_COLORS[weakest[0]] }}>
          Weakest: {weakest[0]} ({(myStrengths[weakest[0]] * 100).toFixed(0)}%)
        </span>
      </div>

      {/* Need positions */}
      {targetSections.map(({ needPos, pctOfAvg, targets }) => (
        <div key={needPos} style={{ marginBottom: 14 }}>
          <h4 style={{ fontSize: "0.78rem", margin: "0 0 6px" }}>
            Need: {needPos}{" "}
            <span style={{ fontWeight: 400, fontSize: "0.7rem", color: "var(--subtext)" }}>
              (you&apos;re at {pctOfAvg}% of league avg)
            </span>
          </h4>
          {targets.length === 0 ? (
            <div style={{ fontSize: "0.68rem", color: "var(--subtext)" }}>
              No clear trade targets — other teams are also thin here.
            </div>
          ) : (
            targets.map((t, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0", fontSize: "0.72rem" }}>
                <span style={{ color: POS_GROUP_COLORS[needPos], fontFamily: "var(--mono)", fontWeight: 700, width: 28, fontSize: "0.62rem" }}>
                  {t.pos}
                </span>
                <span style={{ flex: 1, fontWeight: 600 }}>{t.name}</span>
                <span style={{ fontFamily: "var(--mono)", width: 60, textAlign: "right" }}>{t.meta.toLocaleString()}</span>
                <span style={{ fontSize: "0.64rem", color: "var(--subtext)", minWidth: 100 }}>
                  {t.teamName}
                  {t.theirNeed && <span style={{ color: "var(--amber)" }}> (need {t.theirNeed})</span>}
                </span>
              </div>
            ))
          )}
        </div>
      ))}

      {/* Surplus */}
      {surplus.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <h4 style={{ fontSize: "0.78rem", margin: "0 0 6px", color: "var(--green)" }}>
            Your Trade Chips{" "}
            <span style={{ fontWeight: 400, fontSize: "0.7rem", color: "var(--subtext)" }}>
              (surplus from strong positions)
            </span>
          </h4>
          {surplus.map((p, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0", fontSize: "0.72rem" }}>
              <span style={{ color: POS_GROUP_COLORS[p.group], fontFamily: "var(--mono)", fontWeight: 700, width: 28, fontSize: "0.62rem" }}>
                {p.pos}
              </span>
              <span style={{ flex: 1, fontWeight: 600 }}>{p.name}</span>
              <span style={{ fontFamily: "var(--mono)", width: 60, textAlign: "right" }}>{p.meta.toLocaleString()}</span>
              <span style={{ fontSize: "0.64rem", color: "var(--green)", minWidth: 100 }}>your roster</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TeamTiersCard({ tiers, myTeam }) {
  const TIER_COLORS = { contender: "var(--green)", middle: "var(--amber)", rebuilder: "var(--red)" };
  const TIER_BG = { contender: "rgba(39,174,96,0.08)", middle: "transparent", rebuilder: "rgba(231,76,60,0.06)" };

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, fontSize: "0.82rem", marginBottom: 10 }}>Contender / Rebuilder Tiers</div>
      <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginBottom: 10 }}>
        Teams scored by starter quality (70%), roster depth (20%), and pick surplus penalty (-10%).
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 8 }}>
        {tiers.map((t) => {
          const isMe = t.name === myTeam;
          return (
            <div
              key={t.name}
              style={{
                border: "1px solid var(--border)",
                borderLeft: `3px solid ${TIER_COLORS[t.tier]}`,
                borderRadius: 6,
                padding: "10px 14px",
                background: isMe ? "rgba(200,56,3,0.06)" : TIER_BG[t.tier],
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontWeight: 700, fontSize: "0.78rem" }}>
                  {isMe ? <span style={{ color: "var(--cyan)" }}>{t.name}</span> : t.name}
                </span>
                <span style={{ fontFamily: "var(--mono)", fontSize: "0.62rem", color: "var(--subtext)" }}>#{t.rank}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 4 }}>
                <span style={{ fontSize: "0.68rem", fontWeight: 700, color: TIER_COLORS[t.tier] }}>{t.tierLabel}</span>
                <span style={{ fontFamily: "var(--mono)", fontSize: "0.66rem", color: "var(--subtext)" }}>
                  {Math.round(t.totalValue).toLocaleString()} total
                </span>
              </div>
              <div style={{ display: "flex", gap: 10, marginTop: 4, fontSize: "0.6rem", color: "var(--subtext)" }}>
                <span>Starters: {Math.round(t.starterValue).toLocaleString()}</span>
                <span>Depth: {Math.round(t.depthValue).toLocaleString()}</span>
                {t.pickValue > 0 && <span>Picks: {Math.round(t.pickValue).toLocaleString()}</span>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function LeagueEdgeCard({ edges }) {
  const maxEdge = Math.max(1, ...edges.map((t) => Math.max(t.sellEdge, t.buyEdge)));

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, fontSize: "0.82rem", marginBottom: 6 }}>League Edge Map</div>
      <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginBottom: 10 }}>
        Market vs. model edge per team. Sell = market overvalues their players. Buy = market undervalues.
      </div>
      {edges.map((t) => {
        const sellPct = Math.round((t.sellEdge / maxEdge) * 100);
        const buyPct = Math.round((t.buyEdge / maxEdge) * 100);
        return (
          <div
            key={t.name}
            style={{
              padding: "8px 10px",
              borderBottom: "1px solid var(--border-dim)",
              background: t.isMe ? "rgba(200,56,3,0.08)" : "",
              borderLeft: t.isMe ? "3px solid var(--cyan)" : "3px solid transparent",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
              <span style={{ fontWeight: 600, minWidth: 90, fontSize: "0.73rem" }} className="truncate">
                {t.name}{t.isMe ? " \u2B50" : ""}
              </span>
              <div style={{ flex: 1, display: "flex", gap: 4, alignItems: "center" }}>
                <div
                  style={{
                    width: `${sellPct}%`,
                    height: 10,
                    background: "var(--red)",
                    borderRadius: 2,
                    minWidth: t.sellEdge > 0 ? 2 : 0,
                  }}
                  title={`Market overvalues ${t.sellCount} of their players`}
                />
                <span style={{ fontSize: "0.6rem", color: "var(--red)", fontFamily: "var(--mono)", minWidth: 40 }}>
                  {t.sellCount} sell
                </span>
                <div
                  style={{
                    width: `${buyPct}%`,
                    height: 10,
                    background: "var(--green)",
                    borderRadius: 2,
                    minWidth: t.buyEdge > 0 ? 2 : 0,
                  }}
                  title={`Market undervalues ${t.buyCount} of their players`}
                />
                <span style={{ fontSize: "0.6rem", color: "var(--green)", fontFamily: "var(--mono)" }}>
                  {t.buyCount} buy
                </span>
              </div>
            </div>
            {(t.topSells.length > 0 || t.topBuys.length > 0) && (
              <div style={{ fontSize: "0.62rem", color: "var(--subtext)", paddingLeft: 100 }}>
                {t.topSells.length > 0 && (
                  <span style={{ color: "var(--red)" }}>
                    Overvalued: {t.topSells.map((p) => `${p.name} +${p.pct}%`).join(", ")}
                  </span>
                )}
                {t.topSells.length > 0 && t.topBuys.length > 0 && " \u00B7 "}
                {t.topBuys.length > 0 && (
                  <span style={{ color: "var(--green)" }}>
                    Undervalued: {t.topBuys.map((p) => `${p.name} -${p.pct}%`).join(", ")}
                  </span>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function WaiverWireCard({ gems }) {
  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, fontSize: "0.82rem", marginBottom: 6 }}>Waiver Wire Gems</div>
      <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginBottom: 8 }}>
        Players not on any roster with meaningful trade value.
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {gems.map((p) => (
          <div
            key={p.name}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "5px 10px",
              border: "1px solid var(--border)",
              borderRadius: 6,
              fontSize: "0.72rem",
            }}
          >
            <span style={{ color: POS_GROUP_COLORS[p.pos] || "var(--subtext)", fontWeight: 700, fontFamily: "var(--mono)", fontSize: "0.62rem" }}>
              {p.pos}
            </span>
            <span style={{ fontWeight: 600 }}>{p.name}</span>
            <span style={{ fontFamily: "var(--mono)", color: "var(--subtext)" }}>{p.value.toLocaleString()}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

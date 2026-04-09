"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useSettings } from "@/components/useSettings";
import { SubNav, PageHeader, LoadingState, EmptyState } from "@/components/ui";
import {
  POS_GROUPS,
  POS_GROUP_COLORS,
  POS_GROUP_LABELS,
  posGroup,
  buildPlayerMetaMap,
  buildAllTeamSummaries,
  computePositionRanks,
  heatmapColor,
  heatmapTextColor,
  ordinal,
  buildRowLookup,
} from "@/lib/league-analysis";

const SUB_TABS = [
  { key: "power", label: "Power Rankings" },
  { key: "breakdown", label: "Team Breakdown" },
  { key: "compare", label: "Comparison" },
  { key: "tradeDb", label: "Trade DB" },
  { key: "waiverDb", label: "Waiver DB" },
];

export default function LeaguePage() {
  const { rows, rawData, loading, error } = useApp();
  const { settings, update } = useSettings();
  const [activeTab, setActiveTab] = useState("power");

  const sleeperTeams = rawData?.sleeper?.teams || [];

  if (loading) return <LoadingState message="Loading league data..." />;
  if (error) return <div className="card"><EmptyState title="Error" message={error} /></div>;

  return (
    <section>
      <div className="card">
        <PageHeader
          title="League"
          subtitle="League-wide analysis — power rankings, team breakdowns, and comparisons."
        />
        <SubNav items={SUB_TABS} active={activeTab} onChange={setActiveTab} />
      </div>

      {!sleeperTeams.length && (
        <div className="card" style={{ marginTop: "var(--space-md)" }}>
          <EmptyState title="No league data" message="Load dynasty data with a Sleeper league to see league analysis." />
        </div>
      )}

      {sleeperTeams.length > 0 && activeTab === "power" && (
        <PowerRankingsHeatmap rows={rows} rawData={rawData} sleeperTeams={sleeperTeams} settings={settings} onSelectTeam={(name) => { update("selectedTeam", name); setActiveTab("breakdown"); }} />
      )}
      {sleeperTeams.length > 0 && activeTab === "breakdown" && (
        <TeamBreakdown rows={rows} rawData={rawData} sleeperTeams={sleeperTeams} settings={settings} update={update} />
      )}
      {sleeperTeams.length > 0 && activeTab === "compare" && (
        <TeamComparison rows={rows} rawData={rawData} sleeperTeams={sleeperTeams} />
      )}
      {activeTab === "tradeDb" && <KtcTradesView rawData={rawData} rows={rows} />}
      {activeTab === "waiverDb" && <KtcWaiversView rawData={rawData} rows={rows} />}
    </section>
  );
}

// ── Power Rankings Heatmap ──────────────────────────────────────────────
function PowerRankingsHeatmap({ rows, rawData, sleeperTeams, settings, onSelectTeam }) {
  const playerMeta = useMemo(() => buildPlayerMetaMap(rows), [rows]);
  const teams = useMemo(
    () => buildAllTeamSummaries(sleeperTeams, playerMeta, rows, "full"),
    [sleeperTeams, playerMeta, rows],
  );
  const posRanks = useMemo(() => computePositionRanks(teams), [teams]);
  const n = sleeperTeams.length;
  const myTeam = settings.selectedTeam || "";

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div className="table-wrap">
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.74rem" }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left", padding: "8px 6px", fontSize: "0.62rem", color: "var(--subtext)", fontFamily: "var(--mono)" }}>#</th>
              <th style={{ textAlign: "left", padding: "8px 6px", fontSize: "0.62rem", color: "var(--subtext)" }}>Team</th>
              <th style={{ textAlign: "right", padding: "8px 6px", fontSize: "0.62rem", color: "var(--subtext)", fontFamily: "var(--mono)" }}>Total</th>
              {POS_GROUPS.map((g) => (
                <th key={g} style={{ textAlign: "center", padding: "8px 6px", fontSize: "0.62rem", color: POS_GROUP_COLORS[g], fontFamily: "var(--mono)" }}>{g}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {teams.map((team, idx) => {
              const rk = posRanks[team.name] || {};
              const isMe = team.name === myTeam;
              return (
                <tr
                  key={team.name}
                  style={{ cursor: "pointer", borderBottom: "1px solid var(--border-dim)", ...(isMe ? { background: "rgba(200,56,3,0.06)" } : {}) }}
                  onClick={() => onSelectTeam(team.name)}
                >
                  <td style={{ padding: 6, fontFamily: "var(--mono)", fontWeight: 700, color: "var(--subtext)" }}>{idx + 1}</td>
                  <td style={{ padding: 6, fontWeight: 700, ...(isMe ? { color: "var(--cyan)" } : {}) }}>{team.name}</td>
                  <td style={{ padding: 6, textAlign: "right", fontFamily: "var(--mono)", fontWeight: 600 }}>{Math.round(team.total).toLocaleString()}</td>
                  {POS_GROUPS.map((g) => {
                    const rank = rk[g] || n;
                    const bg = heatmapColor(rank, n);
                    const fg = heatmapTextColor(bg);
                    return (
                      <td key={g} style={{ padding: 6, textAlign: "center" }}>
                        <span
                          title={`${g}: ${Math.round(team.byGroup[g] || 0).toLocaleString()}`}
                          style={{
                            display: "inline-block",
                            minWidth: 32,
                            padding: "4px 8px",
                            borderRadius: 4,
                            background: bg,
                            color: fg,
                            fontFamily: "var(--mono)",
                            fontWeight: 700,
                          }}
                        >
                          {rank}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Team Breakdown ──────────────────────────────────────────────────────
function TeamBreakdown({ rows, rawData, sleeperTeams, settings, update }) {
  const [selectedTeam, setSelectedTeam] = useState(settings.selectedTeam || sleeperTeams[0]?.name || "");
  const [viewMode, setViewMode] = useState("grouped");

  const playerMeta = useMemo(() => buildPlayerMetaMap(rows), [rows]);
  const allTeams = useMemo(
    () => buildAllTeamSummaries(sleeperTeams, playerMeta, rows, "full"),
    [sleeperTeams, playerMeta, rows],
  );
  const posRanks = useMemo(() => computePositionRanks(allTeams), [allTeams]);

  const team = sleeperTeams.find((t) => t.name === selectedTeam);
  const teamSummary = allTeams.find((t) => t.name === selectedTeam);
  const overallRank = allTeams.findIndex((t) => t.name === selectedTeam) + 1;
  const rk = posRanks[selectedTeam] || {};

  // Build full asset list
  const assets = useMemo(() => {
    if (!team) return [];
    const posMap = rawData?.sleeper?.positions || {};
    const rowLookup = buildRowLookup(rows);
    const players = [];

    for (const pName of team.players || []) {
      const key = pName.toLowerCase();
      const pm = playerMeta[key];
      if (pm) {
        players.push(pm);
      }
    }

    // Add picks
    const picks = (teamSummary?.pickDetails || []);
    const all = [...players, ...picks].sort((a, b) => b.meta - a.meta);
    return all;
  }, [team, playerMeta, teamSummary, rawData, rows]);

  if (!team || !teamSummary) return null;

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
        <select className="input" value={selectedTeam} onChange={(e) => setSelectedTeam(e.target.value)} style={{ minWidth: 160 }}>
          {sleeperTeams.map((t) => (
            <option key={t.name} value={t.name}>{t.name}</option>
          ))}
        </select>
        <select className="input" value={viewMode} onChange={(e) => setViewMode(e.target.value)} style={{ minWidth: 120 }}>
          <option value="grouped">By Position</option>
          <option value="value">By Value</option>
        </select>
      </div>

      {/* Rank badge + info */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 14 }}>
        <div style={{
          fontSize: "1.6rem", fontWeight: 800, color: "var(--cyan)",
          width: 48, height: 48, display: "flex", alignItems: "center", justifyContent: "center",
          border: "2px solid var(--cyan)", borderRadius: "var(--radius)", background: "rgba(0,180,216,0.08)",
        }}>
          {overallRank}
        </div>
        <div>
          <div style={{ fontSize: "1.2rem", fontWeight: 700 }}>{selectedTeam}</div>
          <div style={{ fontSize: "0.72rem", color: "var(--subtext)", fontFamily: "var(--mono)" }}>
            {(team.players || []).length} players &middot; {teamSummary.pickCount} picks
          </div>
        </div>
      </div>

      {/* Position rank badges */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14 }}>
        {POS_GROUPS.map((g) => {
          const r = rk[g] || sleeperTeams.length;
          const cl = POS_GROUP_COLORS[g];
          return (
            <span
              key={g}
              style={{
                padding: "4px 12px",
                borderRadius: 20,
                fontSize: "0.68rem",
                fontWeight: 700,
                fontFamily: "var(--mono)",
                color: cl,
                border: `1px solid ${cl}44`,
                background: r <= 3 ? `${cl}22` : "transparent",
              }}
            >
              {g}: {ordinal(r)}
            </span>
          );
        })}
      </div>

      {/* Asset list */}
      {viewMode === "value" ? (
        <div>
          <div style={{ padding: "4px 8px", borderBottom: "1px solid var(--border)", fontWeight: 700, fontSize: "0.78rem" }}>
            All Assets by Value
          </div>
          {assets.filter((p) => p.meta > 0).map((p, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 8px", fontSize: "0.74rem", borderBottom: "1px solid var(--border-dim)" }}>
              <span style={{ width: 22, color: "var(--subtext)", fontFamily: "var(--mono)", fontSize: "0.66rem" }}>{i + 1}</span>
              <span style={{ flex: 1, fontWeight: 600 }}>{p.name}</span>
              <span style={{ fontFamily: "var(--mono)", fontSize: "0.62rem", fontWeight: 700, color: POS_GROUP_COLORS[p.group] || "var(--subtext)", width: 48 }}>
                {p.group === "PICKS" ? "PICK" : (p.pos || "?")}
              </span>
              <span style={{ fontFamily: "var(--mono)", fontWeight: 600, width: 70, textAlign: "right" }}>{Math.round(p.meta).toLocaleString()}</span>
            </div>
          ))}
        </div>
      ) : (
        POS_GROUPS.map((g) => {
          const gp = assets.filter((p) => p.group === g && p.meta > 0).sort((a, b) => b.meta - a.meta);
          if (!gp.length) return null;
          return (
            <div key={g} style={{ marginBottom: 14 }}>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 8px", borderBottom: "1px solid var(--border)" }}>
                <span style={{ fontWeight: 700, color: POS_GROUP_COLORS[g], fontSize: "0.78rem" }}>{POS_GROUP_LABELS[g] || g}</span>
                <span style={{ fontSize: "0.68rem", color: "var(--subtext)", fontFamily: "var(--mono)" }}>
                  {ordinal(rk[g] || sleeperTeams.length)} / {sleeperTeams.length}
                </span>
              </div>
              {gp.map((p, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 8px", fontSize: "0.74rem", borderBottom: "1px solid var(--border-dim)" }}>
                  <span style={{ width: 22, color: "var(--subtext)", fontFamily: "var(--mono)", fontSize: "0.66rem" }}>{i + 1}</span>
                  <span style={{ flex: 1, fontWeight: 600 }}>{p.name}</span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: "0.62rem", fontWeight: 700, color: POS_GROUP_COLORS[g], width: 42 }}>
                    {g === "PICKS" ? "PICK" : (p.pos || "?")}
                  </span>
                  <span style={{ fontFamily: "var(--mono)", fontWeight: 600, width: 70, textAlign: "right" }}>{Math.round(p.meta).toLocaleString()}</span>
                </div>
              ))}
            </div>
          );
        })
      )}
    </div>
  );
}

// ── Team Comparison ─────────────────────────────────────────────────────
function TeamComparison({ rows, rawData, sleeperTeams }) {
  const [teamA, setTeamA] = useState(sleeperTeams[0]?.name || "");
  const [teamB, setTeamB] = useState(sleeperTeams[1]?.name || "");

  const playerMeta = useMemo(() => buildPlayerMetaMap(rows), [rows]);

  const getData = useCallback((name) => {
    const team = sleeperTeams.find((t) => t.name === name);
    if (!team) return { bg: {}, assets: [], total: 0 };
    const posMap = rawData?.sleeper?.positions || {};

    const bg = {};
    POS_GROUPS.forEach((g) => { bg[g] = 0; });
    const playerAssets = [];

    for (const pn of team.players || []) {
      const key = pn.toLowerCase();
      const pm = playerMeta[key];
      if (!pm) continue;
      if (bg[pm.group] !== undefined) bg[pm.group] += pm.meta;
      playerAssets.push(pm);
    }
    playerAssets.sort((a, b) => b.meta - a.meta);

    // Picks
    const rowLookup = buildRowLookup(rows);
    const pickAssets = [];
    for (const pickName of team.picks || []) {
      const row = rowLookup.get(pickName.toLowerCase());
      const val = row ? (row.values?.full || 0) : 0;
      if (val > 0) {
        bg.PICKS = (bg.PICKS || 0) + val;
        pickAssets.push({ name: pickName, meta: val, pos: "PICK", group: "PICKS", isPick: true });
      }
    }
    pickAssets.sort((a, b) => b.meta - a.meta);

    const total = POS_GROUPS.reduce((s, g) => s + (bg[g] || 0), 0);
    return { bg, playerAssets, pickAssets, total };
  }, [sleeperTeams, playerMeta, rows, rawData]);

  const dA = useMemo(() => getData(teamA), [getData, teamA]);
  const dB = useMemo(() => getData(teamB), [getData, teamB]);

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div className="filter-bar" style={{ marginBottom: 14, marginTop: 0 }}>
        <select className="input" value={teamA} onChange={(e) => setTeamA(e.target.value)} style={{ flex: 1 }}>
          {sleeperTeams.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
        </select>
        <span style={{ fontWeight: 700, color: "var(--subtext)" }}>vs</span>
        <select className="input" value={teamB} onChange={(e) => setTeamB(e.target.value)} style={{ flex: 1 }}>
          {sleeperTeams.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
        </select>
      </div>

      <div className="grid-responsive" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {[
          { name: teamA, d: dA, color: "rgba(100,180,220,0.8)" },
          { name: teamB, d: dB, color: "rgba(220,100,120,0.8)" },
        ].map((side) => (
          <div key={side.name}>
            <div style={{ fontWeight: 700, fontSize: "0.82rem", marginBottom: 8, color: side.color }}>{side.name}</div>
            <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginBottom: 6 }}>
              Total: <span style={{ fontFamily: "var(--mono)", fontWeight: 700, color: "var(--text)" }}>{Math.round(side.d.total).toLocaleString()}</span>
            </div>

            {/* Position totals */}
            {POS_GROUPS.map((g) => (
              <div key={g} style={{ fontSize: "0.68rem", color: "var(--subtext)", marginBottom: 2 }}>
                {g}: <span style={{ color: POS_GROUP_COLORS[g], fontWeight: 600 }}>{Math.round(side.d.bg[g] || 0).toLocaleString()}</span>
              </div>
            ))}

            {/* Top Players */}
            <div style={{ marginTop: 8 }}>
              <div style={{ margin: "8px 0 4px", fontSize: "0.66rem", color: "var(--subtext)", fontWeight: 700 }}>Top Players</div>
              {side.d.playerAssets.slice(0, 25).map((p, i) => (
                <div key={i} style={{ display: "flex", gap: 6, alignItems: "center", padding: "3px 6px", fontSize: "0.72rem", borderBottom: "1px solid var(--border-dim)" }}>
                  <span style={{ width: 18, color: "var(--subtext)", fontFamily: "var(--mono)", fontSize: "0.62rem" }}>{i + 1}</span>
                  <span style={{ fontWeight: 600, flex: 1 }}>{p.name}</span>
                  <span style={{ color: POS_GROUP_COLORS[p.group] || "#9b59b6", fontFamily: "var(--mono)", fontSize: "0.6rem", fontWeight: 700 }}>{p.pos || "?"}</span>
                  <span style={{ fontFamily: "var(--mono)", fontWeight: 600, width: 64, textAlign: "right" }}>{Math.round(p.meta).toLocaleString()}</span>
                </div>
              ))}
              {side.d.pickAssets.length > 0 && (
                <>
                  <div style={{ margin: "10px 0 4px", paddingTop: 6, borderTop: "1px solid var(--border)", fontSize: "0.66rem", color: POS_GROUP_COLORS.PICKS, fontWeight: 700 }}>
                    Draft Picks ({side.d.pickAssets.length})
                  </div>
                  {side.d.pickAssets.map((p, i) => (
                    <div key={i} style={{ display: "flex", gap: 6, alignItems: "center", padding: "3px 6px", fontSize: "0.72rem", borderBottom: "1px solid var(--border-dim)" }}>
                      <span style={{ width: 18, color: "var(--subtext)", fontFamily: "var(--mono)", fontSize: "0.62rem" }}>{i + 1}</span>
                      <span style={{ fontWeight: 600, flex: 1 }}>{p.name}</span>
                      <span style={{ color: POS_GROUP_COLORS.PICKS, fontFamily: "var(--mono)", fontSize: "0.6rem", fontWeight: 700 }}>PICK</span>
                      <span style={{ fontFamily: "var(--mono)", fontWeight: 600, width: 64, textAlign: "right" }}>{Math.round(p.meta).toLocaleString()}</span>
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── KTC Trade Database ──────────────────────────────────────────────────
function KtcTradesView({ rawData, rows }) {
  const [search, setSearch] = useState("");
  const trades = rawData?.ktcCrowd?.trades || [];
  const rowLookup = useMemo(() => buildRowLookup(rows), [rows]);

  const filtered = useMemo(() => {
    if (!search.trim()) return trades;
    const q = search.toLowerCase().trim();
    return trades.filter((t) =>
      t.sides?.some((s) => s.players?.some((p) => p.toLowerCase().includes(q))),
    );
  }, [trades, search]);

  function quickVal(name) {
    const row = rowLookup.get((name || "").toLowerCase());
    return row ? Math.round(row.values?.full || 0) : 0;
  }

  if (!trades.length) {
    return (
      <div className="card" style={{ marginTop: "var(--space-md)" }}>
        <EmptyState title="No KTC trade data" message="Run scraper with KTC enabled to populate the trade database." />
      </div>
    );
  }

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ marginBottom: 10 }}>
        <input
          className="input"
          placeholder="Search by player name..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ maxWidth: 300 }}
        />
      </div>
      <div style={{ fontSize: "0.66rem", color: "var(--subtext)", marginBottom: 8 }}>
        {filtered.length.toLocaleString()} trades
      </div>
      <div className="table-wrap">
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.74rem" }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left", padding: 6, fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Date</th>
              <th style={{ textAlign: "left", padding: 6, fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Side A</th>
              <th style={{ textAlign: "right", padding: 6, fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em" }}>A Value</th>
              <th style={{ textAlign: "left", padding: 6, fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Side B</th>
              <th style={{ textAlign: "right", padding: 6, fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em" }}>B Value</th>
              <th style={{ textAlign: "left", padding: 6, fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Format</th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 50).map((t, idx) => {
              if (!t.sides || t.sides.length < 2) return null;
              const sideA = t.sides[0]?.players || [];
              const sideB = t.sides[1]?.players || [];
              const sideAVal = sideA.reduce((sum, p) => sum + quickVal(p), 0);
              const sideBVal = sideB.reduce((sum, p) => sum + quickVal(p), 0);
              const s = t.settings || {};
              const parts = [];
              if (s.teams) parts.push(`${s.teams} Teams`);
              if (s.sf) parts.push("SF");
              if (s.tep) parts.push("TE+");
              const fmt = parts.join(" \u00B7 ") || "\u2014";
              const dt = String(t.date || "").slice(0, 10) || "\u2014";

              return (
                <tr key={idx} style={{ borderBottom: "1px solid var(--border-dim)" }}>
                  <td style={{ padding: 6, fontFamily: "var(--mono)", color: "var(--subtext)", whiteSpace: "nowrap" }}>{dt}</td>
                  <td style={{ padding: 6, minWidth: 200 }}>
                    {sideA.map((p, i) => {
                      const v = quickVal(p);
                      return (
                        <div key={i}>
                          <span style={{ fontWeight: 600 }}>{p}</span>
                          {v > 0 && <span style={{ fontFamily: "var(--mono)", fontSize: "0.64rem", color: "var(--subtext)" }}> {v.toLocaleString()}</span>}
                        </div>
                      );
                    })}
                  </td>
                  <td style={{ padding: 6, textAlign: "right", fontFamily: "var(--mono)", fontWeight: 600 }}>{sideAVal > 0 ? sideAVal.toLocaleString() : "\u2014"}</td>
                  <td style={{ padding: 6, minWidth: 200 }}>
                    {sideB.map((p, i) => {
                      const v = quickVal(p);
                      return (
                        <div key={i}>
                          <span style={{ fontWeight: 600 }}>{p}</span>
                          {v > 0 && <span style={{ fontFamily: "var(--mono)", fontSize: "0.64rem", color: "var(--subtext)" }}> {v.toLocaleString()}</span>}
                        </div>
                      );
                    })}
                  </td>
                  <td style={{ padding: 6, textAlign: "right", fontFamily: "var(--mono)", fontWeight: 600 }}>{sideBVal > 0 ? sideBVal.toLocaleString() : "\u2014"}</td>
                  <td style={{ padding: 6, fontSize: "0.66rem", color: "var(--muted)", fontFamily: "var(--mono)", whiteSpace: "nowrap" }}>{fmt}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {filtered.length > 50 && (
        <div style={{ textAlign: "center", padding: 10, color: "var(--subtext)", fontSize: "0.72rem" }}>
          Showing 50 of {filtered.length}
        </div>
      )}
    </div>
  );
}

// ── KTC Waiver Database ─────────────────────────────────────────────────
function KtcWaiversView({ rawData, rows }) {
  const [search, setSearch] = useState("");
  const waivers = rawData?.ktcCrowd?.waivers || [];
  const rowLookup = useMemo(() => buildRowLookup(rows), [rows]);

  const filtered = useMemo(() => {
    if (!search.trim()) return waivers;
    const q = search.toLowerCase().trim();
    return waivers.filter(
      (w) => (w.added || "").toLowerCase().includes(q) || (w.dropped || "").toLowerCase().includes(q),
    );
  }, [waivers, search]);

  function quickVal(name) {
    const row = rowLookup.get((name || "").toLowerCase());
    return row ? Math.round(row.values?.full || 0) : 0;
  }

  if (!waivers.length) {
    return (
      <div className="card" style={{ marginTop: "var(--space-md)" }}>
        <EmptyState title="No KTC waiver data" message="Run scraper with KTC enabled to populate the waiver database." />
      </div>
    );
  }

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ marginBottom: 10 }}>
        <input
          className="input"
          placeholder="Search by player name..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ maxWidth: 300 }}
        />
      </div>
      <div style={{ fontSize: "0.66rem", color: "var(--subtext)", marginBottom: 8 }}>
        {filtered.length.toLocaleString()} waivers
      </div>
      <div className="table-wrap">
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.74rem" }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left", padding: 6, fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Date</th>
              <th style={{ textAlign: "left", padding: 6, fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Added</th>
              <th style={{ textAlign: "right", padding: 6, fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Bid</th>
              <th style={{ textAlign: "left", padding: 6, fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Dropped</th>
              <th style={{ textAlign: "left", padding: 6, fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Format</th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 50).map((w, idx) => {
              const av = quickVal(w.added || "");
              const bidDisplay = w.bidPct ? w.bidPct : w.bid ? `$${w.bid}` : "\u2014";
              const dt = String(w.date || "").slice(0, 10) || "\u2014";
              const s = w.settings || {};
              const parts = [];
              if (s.teams) parts.push(`${s.teams} Teams`);
              if (s.sf) parts.push("SF");
              if (s.tep) parts.push("TE+");
              const fmt = parts.join(" \u00B7 ") || "\u2014";

              return (
                <tr key={idx} style={{ borderBottom: "1px solid var(--border-dim)" }}>
                  <td style={{ padding: 6, fontFamily: "var(--mono)", color: "var(--subtext)", whiteSpace: "nowrap" }}>{dt}</td>
                  <td style={{ padding: 6, fontWeight: 700 }}>
                    {w.added || "\u2014"}
                    {av > 0 && <span style={{ fontFamily: "var(--mono)", fontSize: "0.62rem", color: "var(--subtext)" }}> {av.toLocaleString()}</span>}
                  </td>
                  <td style={{ padding: 6, textAlign: "right", fontFamily: "var(--mono)", color: "var(--green)", fontWeight: 600, whiteSpace: "nowrap" }}>{bidDisplay}</td>
                  <td style={{ padding: 6, color: "var(--subtext)" }}>{w.dropped || "\u2014"}</td>
                  <td style={{ padding: 6, fontSize: "0.66rem", color: "var(--muted)", fontFamily: "var(--mono)", whiteSpace: "nowrap" }}>{fmt}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {filtered.length > 50 && (
        <div style={{ textAlign: "center", padding: 10, color: "var(--subtext)", fontSize: "0.72rem" }}>
          Showing 50 of {filtered.length}
        </div>
      )}
    </div>
  );
}

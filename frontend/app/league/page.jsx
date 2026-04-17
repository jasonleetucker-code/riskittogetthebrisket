"use client";

// PUBLIC /league page.
//
// Critical isolation rules (enforced by AppShell.PUBLIC_ONLY_ROUTE_PREFIXES):
//   * NO imports from @/components/AppShell.useApp — the public route
//     runs inside PublicAppShell, which refuses to hydrate
//     useDynastyData.  Calling useApp here would still return empty
//     arrays, but importing the hook anywhere public makes it
//     trivially easy to accidentally leak private state later.
//   * NO imports from @/lib/league-analysis — that module operates on
//     the private canonical contract.  Everything here fetches the
//     public contract shape defined in src/public_league/public_contract.py.
//   * NO imports from @/lib/dynasty-data, @/lib/trade-logic, @/lib/edge-helpers.
//
// Data source: /api/public/league → fetchPublicLeague().

import { useEffect, useMemo, useState } from "react";
import {
  SubNav,
  PageHeader,
  LoadingState,
  EmptyState,
} from "@/components/ui";
import {
  PUBLIC_SECTION_KEYS,
  fetchPublicLeague,
} from "@/lib/public-league-data";

const SUB_TABS = [
  { key: "history", label: "History" },
  { key: "rivalries", label: "Rivalries" },
  { key: "awards", label: "Awards" },
  { key: "records", label: "Records" },
  { key: "franchise", label: "Franchises" },
  { key: "activity", label: "Trades" },
  { key: "draft", label: "Draft" },
  { key: "weekly", label: "Weekly" },
  { key: "superlatives", label: "Superlatives" },
  { key: "archives", label: "Archives" },
];

export default function LeaguePage() {
  const [activeTab, setActiveTab] = useState("history");
  const [state, setState] = useState({ loading: true, error: "", contract: null });

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const contract = await fetchPublicLeague();
        if (!active) return;
        if (
          !contract ||
          typeof contract !== "object" ||
          !contract.sections ||
          !contract.league
        ) {
          setState({ loading: false, error: "Public contract missing required shape.", contract: null });
          return;
        }
        setState({ loading: false, error: "", contract });
      } catch (err) {
        if (!active) return;
        setState({ loading: false, error: err?.message || "Failed to load public league data", contract: null });
      }
    })();
    return () => { active = false; };
  }, []);

  const { loading, error, contract } = state;
  const sections = contract?.sections || {};
  const league = contract?.league || null;

  if (loading) return <LoadingState message="Loading league data..." />;
  if (error) {
    return (
      <div className="card">
        <EmptyState title="League data unavailable" message={error} />
      </div>
    );
  }
  if (!league) {
    return (
      <div className="card">
        <EmptyState title="No public league data" message="Public contract empty." />
      </div>
    );
  }

  return (
    <section>
      <div className="card">
        <PageHeader
          title={league.leagueName || "League"}
          subtitle={
            `Seasons: ${(league.seasonsCovered || []).join(", ") || "\u2014"} \u00B7 ` +
            `${(league.managers || []).length} managers \u00B7 ` +
            `Generated ${String(league.generatedAt || "").replace("T", " ").slice(0, 19)}`
          }
        />
        <SubNav items={SUB_TABS} active={activeTab} onChange={setActiveTab} />
      </div>

      {activeTab === "history" && <HistorySection league={league} data={sections.history} />}
      {activeTab === "rivalries" && <RivalriesSection league={league} data={sections.rivalries} />}
      {activeTab === "awards" && <AwardsSection league={league} data={sections.awards} />}
      {activeTab === "records" && <RecordsSection data={sections.records} />}
      {activeTab === "franchise" && <FranchiseSection data={sections.franchise} />}
      {activeTab === "activity" && <ActivitySection league={league} data={sections.activity} />}
      {activeTab === "draft" && <DraftSection data={sections.draft} />}
      {activeTab === "weekly" && <WeeklySection data={sections.weekly} />}
      {activeTab === "superlatives" && <SuperlativesSection league={league} data={sections.superlatives} />}
      {activeTab === "archives" && <ArchivesSection data={sections.archives} />}
    </section>
  );
}

// Helper: owner_id -> display name lookup from league header.
function buildManagerLookup(league) {
  const map = new Map();
  for (const m of league?.managers || []) {
    map.set(String(m.ownerId), m);
  }
  return map;
}

function nameFor(managers, ownerId) {
  const mgr = managers.get(String(ownerId));
  return mgr?.displayName || mgr?.currentTeamName || ownerId || "Unknown";
}

// ── Sections ─────────────────────────────────────────────────────────────
function HistorySection({ league, data }) {
  const managers = useMemo(() => buildManagerLookup(league), [league]);
  const hof = data?.hallOfFame || [];
  const seasons = data?.seasons || [];
  if (!hof.length && !seasons.length) {
    return <EmptyCard label="Hall of Fame" />;
  }

  return (
    <>
      <div className="card" style={{ marginTop: "var(--space-md)" }}>
        <div style={{ fontWeight: 700, marginBottom: 10 }}>Hall of Fame</div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th style={{ textAlign: "left" }}>Manager</th>
                <th style={{ textAlign: "right" }}>Seasons</th>
                <th style={{ textAlign: "right" }}>Record</th>
                <th style={{ textAlign: "right" }}>Rings</th>
                <th style={{ textAlign: "right" }}>Runner-Ups</th>
                <th style={{ textAlign: "right" }}>Points For</th>
              </tr>
            </thead>
            <tbody>
              {hof.map((row) => (
                <tr key={row.ownerId}>
                  <td style={{ fontWeight: 600 }}>{row.displayName || row.currentTeamName || row.ownerId}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.seasonsPlayed}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {row.wins}-{row.losses}{row.ties ? `-${row.ties}` : ""}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.championships}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.runnerUps}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.pointsFor.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {seasons.map((s) => (
        <div className="card" style={{ marginTop: "var(--space-md)" }} key={s.leagueId}>
          <div style={{ fontWeight: 700, marginBottom: 10 }}>
            {s.season} season {s.champion ? `\u00B7 Champion: ${s.champion.teamName}` : ""}
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Team</th>
                  <th style={{ textAlign: "right" }}>W-L-T</th>
                  <th style={{ textAlign: "right" }}>PF</th>
                  <th style={{ textAlign: "right" }}>PA</th>
                  <th style={{ textAlign: "right" }}>Final</th>
                </tr>
              </thead>
              <tbody>
                {(s.standings || []).map((row) => (
                  <tr key={row.ownerId}>
                    <td style={{ fontWeight: 600 }}>{row.teamName}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.wins}-{row.losses}-{row.ties}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.pointsFor.toLocaleString()}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.pointsAgainst.toLocaleString()}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.finalPlace ?? "\u2014"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </>
  );
}

function RivalriesSection({ league, data }) {
  const managers = useMemo(() => buildManagerLookup(league), [league]);
  const rows = data?.rivalries || [];
  if (!rows.length) return <EmptyCard label="Rivalries" />;

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, marginBottom: 10 }}>Head-to-Head</div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Matchup</th>
              <th style={{ textAlign: "right" }}>Games</th>
              <th style={{ textAlign: "right" }}>Record</th>
              <th style={{ textAlign: "right" }}>Points</th>
              <th style={{ textAlign: "right" }}>Close Score</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const [a, b] = r.ownerIds;
              return (
                <tr key={i}>
                  <td style={{ fontWeight: 600 }}>
                    {nameFor(managers, a)} vs {nameFor(managers, b)}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.games}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {r.winsA}-{r.winsB}{r.ties ? `-${r.ties}` : ""}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {r.pointsA.toFixed(0)} / {r.pointsB.toFixed(0)}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.competitivenessScore}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AwardsSection({ league, data }) {
  const managers = useMemo(() => buildManagerLookup(league), [league]);
  const seasons = data?.bySeason || [];
  if (!seasons.length) return <EmptyCard label="Awards" />;

  return (
    <>
      {seasons.map((s) => (
        <div className="card" style={{ marginTop: "var(--space-md)" }} key={s.leagueId}>
          <div style={{ fontWeight: 700, marginBottom: 10 }}>{s.season} awards</div>
          {(s.awards || []).length === 0 ? (
            <div style={{ color: "var(--subtext)", fontSize: "0.8rem" }}>
              Season still in progress.
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 10 }}>
              {(s.awards || []).map((a) => (
                <div key={a.key} style={{ border: "1px solid var(--border)", borderRadius: 6, padding: 10 }}>
                  <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase" }}>{a.label}</div>
                  <div style={{ fontWeight: 700 }}>{a.teamName}</div>
                  <div style={{ fontSize: "0.68rem", color: "var(--subtext)" }}>{nameFor(managers, a.ownerId)}</div>
                  {a.value && (
                    <div style={{ fontFamily: "var(--mono)", fontSize: "0.7rem", marginTop: 4 }}>
                      {JSON.stringify(a.value)}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </>
  );
}

function RecordsSection({ data }) {
  const high = data?.singleWeekHighest || [];
  const low = data?.singleWeekLowest || [];
  if (!high.length && !low.length) return <EmptyCard label="Records" />;

  return (
    <>
      <RecordTable title="Highest Single-Week Scores" rows={high} />
      <RecordTable title="Lowest Single-Week Scores" rows={low} />
    </>
  );
}

function RecordTable({ title, rows }) {
  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, marginBottom: 10 }}>{title}</div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Team</th>
              <th style={{ textAlign: "right" }}>Season</th>
              <th style={{ textAlign: "right" }}>Week</th>
              <th style={{ textAlign: "right" }}>Points</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td style={{ fontWeight: 600 }}>{r.teamName}</td>
                <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.season}</td>
                <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.week}</td>
                <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.points.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FranchiseSection({ data }) {
  const index = data?.index || [];
  const detail = data?.detail || {};
  const [selected, setSelected] = useState(index[0]?.ownerId || "");
  if (!index.length) return <EmptyCard label="Franchises" />;
  const fr = detail[selected] || null;

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ display: "flex", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
        <select
          className="input"
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          style={{ minWidth: 220 }}
        >
          {index.map((row) => (
            <option key={row.ownerId} value={row.ownerId}>
              {row.displayName} {row.championships ? `\u2b50\u00D7${row.championships}` : ""}
            </option>
          ))}
        </select>
      </div>
      {fr && (
        <div>
          <div style={{ fontWeight: 700, fontSize: "1.1rem" }}>{fr.displayName}</div>
          <div style={{ color: "var(--subtext)", fontSize: "0.74rem", marginBottom: 10 }}>
            Current team: {fr.currentTeamName}
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Season</th>
                  <th style={{ textAlign: "right" }}>W-L-T</th>
                  <th style={{ textAlign: "right" }}>PF</th>
                  <th style={{ textAlign: "right" }}>PA</th>
                  <th style={{ textAlign: "right" }}>Final</th>
                </tr>
              </thead>
              <tbody>
                {(fr.seasonResults || []).map((r, i) => (
                  <tr key={i}>
                    <td>{r.season}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.wins}-{r.losses}-{r.ties}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.pointsFor.toLocaleString()}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.pointsAgainst.toLocaleString()}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.finalPlace ?? "\u2014"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ marginTop: 10, fontSize: "0.72rem", color: "var(--subtext)" }}>
            {`Trades: ${fr.tradeCount} \u00B7 Draft picks used: ${fr.draftPickCount}`}
          </div>
          {(fr.aliases || []).length > 1 && (
            <div style={{ marginTop: 10, fontSize: "0.7rem", color: "var(--subtext)" }}>
              Team-name history: {(fr.aliases || []).map((a) => `${a.teamName} (${a.season})`).join(" \u2192 ")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ActivitySection({ league, data }) {
  const managers = useMemo(() => buildManagerLookup(league), [league]);
  const feed = data?.feed || [];
  if (!feed.length) return <EmptyCard label="Trade activity" />;

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, marginBottom: 10 }}>
        Recent Trades ({data.totalCount} total)
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {feed.map((t) => (
          <div key={t.transactionId} style={{ border: "1px solid var(--border)", borderRadius: 6, padding: 10 }}>
            <div style={{ fontSize: "0.66rem", color: "var(--subtext)" }}>
              {`${t.season} \u00B7 Week ${t.week ?? "\u2014"}`}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: `repeat(${t.sides.length}, 1fr)`, gap: 10, marginTop: 4 }}>
              {t.sides.map((side, i) => (
                <div key={i}>
                  <div style={{ fontWeight: 700 }}>{nameFor(managers, side.ownerId) || side.teamName}</div>
                  <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>
                    Received: {side.receivedPlayerIds.length} players, {side.receivedPicks.length} picks
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function DraftSection({ data }) {
  const drafts = data?.drafts || [];
  if (!drafts.length) return <EmptyCard label="Drafts" />;

  return (
    <>
      {drafts.map((d) => (
        <div className="card" style={{ marginTop: "var(--space-md)" }} key={d.draftId}>
          <div style={{ fontWeight: 700, marginBottom: 10 }}>
            {`${d.season} ${d.type || "draft"} \u00B7 ${d.status}`}
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ textAlign: "right" }}>Pk</th>
                  <th>Player</th>
                  <th>Pos</th>
                  <th>NFL</th>
                  <th>Team</th>
                </tr>
              </thead>
              <tbody>
                {d.picks.slice(0, 48).map((p, i) => (
                  <tr key={i}>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{p.round}.{String(p.pickNo).padStart(2, "0")}</td>
                    <td>{p.playerName || "\u2014"}</td>
                    <td style={{ fontFamily: "var(--mono)" }}>{p.position || ""}</td>
                    <td style={{ fontFamily: "var(--mono)" }}>{p.nflTeam || ""}</td>
                    <td>{p.teamName}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </>
  );
}

function WeeklySection({ data }) {
  const weeks = data?.weeks || [];
  const [selected, setSelected] = useState(weeks[0] ? `${weeks[0].season}:${weeks[0].week}` : "");
  if (!weeks.length) return <EmptyCard label="Weekly recap" />;
  const active = weeks.find((w) => `${w.season}:${w.week}` === selected) || weeks[0];

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <select
        className="input"
        value={`${active.season}:${active.week}`}
        onChange={(e) => setSelected(e.target.value)}
        style={{ minWidth: 220, marginBottom: 10 }}
      >
        {weeks.map((w) => (
          <option key={`${w.season}:${w.week}`} value={`${w.season}:${w.week}`}>
            {w.season} Week {w.week}
          </option>
        ))}
      </select>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Home</th>
              <th style={{ textAlign: "right" }}>Score</th>
              <th style={{ textAlign: "right" }}>Margin</th>
              <th style={{ textAlign: "right" }}>Score</th>
              <th>Away</th>
            </tr>
          </thead>
          <tbody>
            {active.matchups.map((m, i) => (
              <tr key={i}>
                <td style={{ fontWeight: 600 }}>{m.home.teamName}</td>
                <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{m.home.points}</td>
                <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--subtext)" }}>{m.margin}</td>
                <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{m.away.points}</td>
                <td style={{ fontWeight: 600 }}>{m.away.teamName}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SuperlativesSection({ league, data }) {
  const managers = useMemo(() => buildManagerLookup(league), [league]);
  if (!data) return <EmptyCard label="Superlatives" />;

  const blocks = [
    { key: "hardLuck", label: "Hard-Luck Manager (high PF, low wins)" },
    { key: "luckyDuck", label: "Lucky Duck (high wins, low PF)" },
    { key: "tradeMachine", label: "Trade Machine" },
    { key: "mostImproved", label: "Most Improved" },
    { key: "couchCoach", label: "Couch Coach (lowest avg PF)" },
  ];

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      {blocks.map((b) => (
        <div key={b.key} style={{ marginBottom: 14 }}>
          <div style={{ fontWeight: 700, fontSize: "0.82rem", marginBottom: 6 }}>{b.label}</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {(data[b.key] || []).map((row, i) => (
              <div
                key={i}
                style={{ border: "1px solid var(--border)", padding: "6px 10px", borderRadius: 6, fontSize: "0.72rem" }}
              >
                <div style={{ fontWeight: 600 }}>{nameFor(managers, row.ownerId)}</div>
                <div style={{ fontFamily: "var(--mono)", fontSize: "0.66rem", color: "var(--subtext)" }}>
                  {JSON.stringify(
                    Object.fromEntries(Object.entries(row).filter(([k]) => k !== "ownerId")),
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function ArchivesSection({ data }) {
  const [query, setQuery] = useState("");
  if (!data) return <EmptyCard label="Archives" />;

  const allRows = useMemo(() => {
    const rows = [];
    (data.managers || []).forEach((m) => rows.push({ kind: m.kind, label: m.displayName, sub: (m.aliases || []).join(" / "), season: "" }));
    (data.trades || []).forEach((t) => rows.push({ kind: t.kind, label: `Trade ${t.transactionId.slice(0, 8)}`, sub: (t.ownerIds || []).join(" \u2194 "), season: t.season }));
    (data.draftPicks || []).forEach((p) => rows.push({ kind: p.kind, label: `${p.playerName} (${p.position})`, sub: `${p.teamName} \u00B7 ${p.round}.${String(p.pickNo).padStart(2, "0")}`, season: p.season }));
    (data.weekScores || []).forEach((w) => rows.push({ kind: w.kind, label: `${w.teamName} \u00B7 ${w.points}`, sub: `W${w.week}`, season: w.season }));
    return rows;
  }, [data]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return allRows.slice(0, 200);
    return allRows.filter(
      (r) => r.label.toLowerCase().includes(q) || r.sub.toLowerCase().includes(q) || String(r.season).toLowerCase().includes(q),
    ).slice(0, 200);
  }, [allRows, query]);

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <input
        className="input"
        placeholder="Search managers, trades, drafts, weeks..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        style={{ maxWidth: 340, marginBottom: 10 }}
      />
      <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginBottom: 6 }}>
        Showing {filtered.length} of {allRows.length} indexed records.
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Kind</th>
              <th>Label</th>
              <th>Details</th>
              <th>Season</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r, i) => (
              <tr key={i}>
                <td style={{ fontFamily: "var(--mono)", fontSize: "0.66rem", color: "var(--subtext)" }}>{r.kind}</td>
                <td style={{ fontWeight: 600 }}>{r.label}</td>
                <td style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>{r.sub}</td>
                <td style={{ fontFamily: "var(--mono)" }}>{r.season}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EmptyCard({ label }) {
  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <EmptyState
        title={`${label} coming online`}
        message="Sleeper fetch returned nothing for this section yet. Sections hydrate as soon as the league has completed games / trades / drafts."
      />
    </div>
  );
}

// Expose available section keys for external consumers / tests.
export const LEAGUE_PAGE_SECTIONS = PUBLIC_SECTION_KEYS;

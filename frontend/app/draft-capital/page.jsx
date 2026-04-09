"use client";

import { useEffect, useMemo, useState } from "react";
import { PageHeader, LoadingState, EmptyState } from "@/components/ui";

/**
 * Draft Capital — auction-dollar pick values from the dynasty draft curve.
 * Pick ownership from Sleeper. Public page (no auth required).
 */
export default function DraftCapitalPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        setLoading(true);
        const res = await fetch("/api/draft-capital");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (!active) return;
        if (json.error) {
          setError(json.error);
        } else {
          setData(json);
        }
      } catch (err) {
        if (active) setError(err.message || "Failed to load draft capital.");
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => { active = false; };
  }, []);

  if (loading) return <LoadingState message="Loading draft capital..." />;
  if (error) return <div className="card"><EmptyState title="Error" message={error} /></div>;
  if (!data) return <div className="card"><EmptyState title="No data" message="No draft capital data available." /></div>;

  return (
    <section>
      <div className="card">
        <PageHeader
          title="Draft Capital"
          subtitle={`${data.season} draft · ${data.numTeams} teams · ${data.draftRounds} rounds · $${data.totalBudget} total budget`}
        />

        {/* Team totals bar chart */}
        <TeamTotalsChart teamTotals={data.teamTotals} picks={data.picks} totalBudget={data.totalBudget} numTeams={data.numTeams} draftRounds={data.draftRounds} season={data.season} />
      </div>

      {/* Picks by round */}
      <div className="card" style={{ marginTop: "var(--space-md)" }}>
        <PicksByRound picks={data.picks} draftRounds={data.draftRounds} />
      </div>
    </section>
  );
}

function TeamTotalsChart({ teamTotals, picks, totalBudget, numTeams, draftRounds, season }) {
  const maxDollars = Math.max(...(teamTotals || []).map((t) => t.auctionDollars), 1);

  return (
    <div>
      <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
        {(teamTotals || []).map((team) => {
          const pct = (team.auctionDollars / maxDollars) * 100;
          const teamPicks = (picks || []).filter((p) => p.currentOwner === team.team);
          const pickLabels = teamPicks.map((p) => p.isTraded ? `${p.pick}*` : p.pick).join(", ");

          return (
            <div key={team.team}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span className="truncate" style={{ minWidth: 70, maxWidth: 110, fontSize: "0.78rem", fontWeight: 600 }}>{team.team}</span>
                <div style={{ flex: 1, background: "var(--bg-soft)", borderRadius: 4, height: 24, position: "relative", overflow: "hidden" }}>
                  <div style={{ width: `${pct}%`, height: "100%", background: "var(--cyan)", borderRadius: 4, transition: "width 0.3s" }} />
                </div>
                <span style={{ minWidth: 40, textAlign: "right", fontFamily: "var(--mono)", fontSize: "0.78rem", fontWeight: 700 }}>${team.auctionDollars}</span>
                <span style={{ minWidth: 30, textAlign: "right", fontFamily: "var(--mono)", fontSize: "0.68rem", color: "var(--subtext)" }}>{teamPicks.length}pk</span>
              </div>
              <div style={{ fontSize: "0.62rem", color: "var(--muted)", marginLeft: 80, marginTop: -4 }}>{pickLabels}</div>
            </div>
          );
        })}
      </div>
      <div style={{ marginTop: 12, fontSize: "0.68rem", color: "var(--subtext)" }}>
        Total budget: ${totalBudget} across {numTeams} teams, {draftRounds} rounds ({season}). * = traded pick.
      </div>
    </div>
  );
}

function PicksByRound({ picks, draftRounds }) {
  const rounds = [];
  for (let round = 1; round <= (draftRounds || 4); round++) {
    const roundPicks = (picks || []).filter((p) => p.round === round);
    const roundTotal = roundPicks.reduce((s, p) => s + (p.adjustedDollarValue || p.dollarValue || 0), 0);
    rounds.push({ round, picks: roundPicks, total: roundTotal });
  }

  return (
    <div>
      {rounds.map(({ round, picks: roundPicks, total }) => (
        <div key={round} style={{ marginBottom: 16 }}>
          <div style={{ fontWeight: 700, fontSize: "0.78rem", marginBottom: 6 }}>
            Round {round}{" "}
            <span style={{ color: "var(--subtext)", fontWeight: 400 }}>
              (${total})
            </span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 60 }}>Pick</th>
                  <th style={{ width: 40 }}>$</th>
                  <th>Owner</th>
                  <th>From</th>
                </tr>
              </thead>
              <tbody>
                {roundPicks.map((pick, idx) => (
                  <tr key={idx} style={pick.isTraded ? { background: "rgba(255,180,50,0.08)" } : undefined}>
                    <td style={{ fontFamily: "var(--mono)", fontWeight: 600 }}>{pick.pick}</td>
                    <td style={{ fontFamily: "var(--mono)", fontWeight: 700, color: "var(--green)" }}>${pick.dollarValue}</td>
                    <td style={{ fontWeight: 600 }}>{pick.currentOwner}</td>
                    <td>
                      {pick.isTraded ? (
                        <span style={{ color: "var(--amber)", fontWeight: 600 }}>{pick.originalOwner}</span>
                      ) : (
                        <span style={{ color: "var(--muted)" }}>&mdash;</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}

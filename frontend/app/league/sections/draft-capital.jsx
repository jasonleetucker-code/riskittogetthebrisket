"use client";

// DraftCapitalSection — public /league tab view.
// Shows the live auction-dollar draft capital board from /api/draft-capital.
// Purely public data (same endpoint powered the old /draft-capital page).
// When this tab is the default, /league mobile users land here.

import { useEffect, useState } from "react";
import { LoadingState, EmptyState } from "@/components/ui";
import { EmptyCard } from "../shared.jsx";

function fmtDollar(v) {
  if (v == null) return "$0";
  return `$${Math.round(v)}`;
}

export default function DraftCapitalSection() {
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
        if (active) setError(err?.message || "Failed to load draft capital.");
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => {
      active = false;
    };
  }, []);

  if (loading) return <LoadingState message="Loading draft capital..." />;
  if (error) {
    return (
      <div className="card" style={{ marginTop: "var(--space-md)" }}>
        <EmptyState title="Draft capital unavailable" message={error} />
      </div>
    );
  }
  if (!data) return <EmptyCard label="Draft capital" />;

  return (
    <>
      <div className="card" style={{ marginTop: "var(--space-md)" }}>
        <div style={{ fontWeight: 700, marginBottom: 4 }}>Draft Capital</div>
        <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginBottom: 10 }}>
          {data.season} draft · {data.numTeams} teams · {data.draftRounds} rounds · ${data.totalBudget} total budget
        </div>
        <TeamTotalsChart
          teamTotals={data.teamTotals}
          picks={data.picks}
          totalBudget={data.totalBudget}
          numTeams={data.numTeams}
          draftRounds={data.draftRounds}
          season={data.season}
        />
      </div>

      <PickValueGrid picks={data.picks} draftRounds={data.draftRounds} numTeams={data.numTeams} />

      <PicksByRound picks={data.picks} draftRounds={data.draftRounds} />
    </>
  );
}

/* ── Team totals bar chart ─────────────────────────────────────────────── */
function TeamTotalsChart({ teamTotals, picks, totalBudget, numTeams, draftRounds, season }) {
  const maxDollars = Math.max(...(teamTotals || []).map((t) => t.auctionDollars), 1);

  return (
    <div style={{ marginTop: "var(--space-md)" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-sm)" }}>
        {(teamTotals || []).map((team, i) => {
          const pct = (team.auctionDollars / maxDollars) * 100;
          const teamPicks = (picks || []).filter((p) => p.currentOwner === team.team);
          const tradedCount = teamPicks.filter((p) => p.isTraded).length;

          return (
            <div
              key={team.team}
              style={{
                padding: "var(--space-sm) var(--space-md)",
                borderRadius: "var(--radius-sm)",
                background: i % 2 === 0 ? "rgba(255,255,255,0.02)" : "transparent",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "var(--space-sm)" }}>
                <span
                  className="font-mono"
                  style={{
                    width: 22,
                    fontSize: "0.68rem",
                    color: "var(--muted)",
                    textAlign: "right",
                    flexShrink: 0,
                  }}
                >
                  {i + 1}
                </span>

                <span
                  className="truncate"
                  style={{ minWidth: 100, maxWidth: 140, fontSize: "0.82rem", fontWeight: 600 }}
                >
                  {team.team}
                </span>

                <div
                  style={{
                    flex: 1,
                    background: "var(--bg-soft)",
                    borderRadius: "var(--radius-sm)",
                    height: 20,
                    overflow: "hidden",
                    border: "1px solid rgba(255,255,255,0.04)",
                  }}
                >
                  <div
                    style={{
                      width: `${pct}%`,
                      height: "100%",
                      background: "linear-gradient(90deg, var(--cyan), rgba(255, 199, 4,0.6))",
                      borderRadius: "var(--radius-sm)",
                      transition: "width 0.4s ease-out",
                      boxShadow: pct > 30 ? "0 0 12px rgba(255, 199, 4,0.15)" : "none",
                    }}
                  />
                </div>

                <span
                  className="font-mono"
                  style={{
                    minWidth: 48,
                    textAlign: "right",
                    fontSize: "0.82rem",
                    fontWeight: 700,
                    color: "var(--green)",
                  }}
                >
                  {fmtDollar(team.auctionDollars)}
                </span>

                <span className="badge badge-cyan" style={{ fontSize: "0.64rem", padding: "1px 6px" }}>
                  {teamPicks.length}pk
                </span>
              </div>

              <div
                style={{
                  marginTop: 3,
                  marginLeft: 30,
                  fontSize: "0.68rem",
                  color: "var(--muted)",
                  lineHeight: 1.6,
                }}
              >
                {teamPicks.map((p, j) => (
                  <span key={j}>
                    {j > 0 && <span style={{ margin: "0 2px", opacity: 0.3 }}>·</span>}
                    <span style={p.isTraded ? { color: "var(--amber)" } : undefined}>
                      {p.pick}{p.isTraded ? "*" : ""}
                    </span>
                  </span>
                ))}
                {tradedCount > 0 && (
                  <span style={{ marginLeft: 6, color: "var(--amber)", opacity: 0.7 }}>
                    ({tradedCount} traded)
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div
        style={{
          marginTop: "var(--space-md)",
          padding: "var(--space-sm) var(--space-md)",
          fontSize: "0.72rem",
          color: "var(--muted)",
          borderTop: "1px solid var(--border)",
        }}
      >
        ${totalBudget} total budget across {numTeams} teams, {draftRounds} rounds ({season}).{" "}
        <span style={{ color: "var(--amber)" }}>*</span> = traded pick.
      </div>
    </div>
  );
}

function PickValueGrid({ picks, draftRounds, numTeams }) {
  if (!picks || !picks.length) return null;
  const rounds = [];
  for (let r = 1; r <= (draftRounds || 6); r++) {
    rounds.push((picks || []).filter((p) => p.round === r));
  }
  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "var(--space-sm)", marginBottom: "var(--space-sm)" }}>
        <span style={{ fontWeight: 700, fontSize: "0.88rem" }}>Pick Values</span>
        <span className="text-xs muted">Adjusted values used for team totals (expansion picks 1 &amp; 2 averaged)</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 70 }}>Round</th>
              {Array.from({ length: numTeams || 12 }, (_, i) => (
                <th key={i} style={{ textAlign: "right", fontSize: "0.72rem", minWidth: 44 }}>Pk {i + 1}</th>
              ))}
              <th style={{ textAlign: "right", fontWeight: 700, minWidth: 50 }}>Total</th>
            </tr>
          </thead>
          <tbody>
            {rounds.map((rp, ri) => {
              const total = rp.reduce((s, p) => s + (p.adjustedDollarValue ?? p.dollarValue ?? 0), 0);
              return (
                <tr key={ri}>
                  <td className="font-mono font-bold">R{ri + 1}</td>
                  {rp.map((p, j) => (
                    <td
                      key={j}
                      className="font-mono"
                      style={{
                        textAlign: "right",
                        fontSize: "0.76rem",
                        color: p.isExpansion ? "var(--amber)" : undefined,
                      }}
                    >
                      {fmtDollar(p.adjustedDollarValue ?? p.dollarValue)}
                    </td>
                  ))}
                  <td className="font-mono font-bold text-green" style={{ textAlign: "right" }}>
                    {fmtDollar(total)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PicksByRound({ picks, draftRounds }) {
  const rounds = [];
  for (let round = 1; round <= (draftRounds || 4); round++) {
    const roundPicks = (picks || []).filter((p) => p.round === round);
    const roundTotal = roundPicks.reduce(
      (s, p) => s + (p.adjustedDollarValue ?? p.dollarValue ?? 0),
      0,
    );
    rounds.push({ round, picks: roundPicks, total: roundTotal });
  }

  return (
    <>
      {rounds.map(({ round, picks: roundPicks, total }) => (
        <div key={round} className="card" style={{ marginTop: "var(--space-md)" }}>
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: "var(--space-sm)",
              marginBottom: "var(--space-sm)",
            }}
          >
            <span style={{ fontWeight: 700, fontSize: "0.88rem" }}>Round {round}</span>
            <span className="badge badge-green" style={{ fontSize: "0.64rem" }}>
              {fmtDollar(total)}
            </span>
            <span className="text-xs muted">{roundPicks.length} picks</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 70 }}>Pick</th>
                  <th style={{ width: 60 }}>Value</th>
                  <th>Owner</th>
                  <th>Original</th>
                </tr>
              </thead>
              <tbody>
                {roundPicks.map((pick, idx) => (
                  <tr key={idx}>
                    <td className="font-mono font-bold">{pick.pick}</td>
                    <td className="font-mono font-bold text-green">
                      {fmtDollar(pick.adjustedDollarValue ?? pick.dollarValue)}
                    </td>
                    <td style={{ fontWeight: 600 }}>{pick.currentOwner}</td>
                    <td>
                      {pick.isTraded ? (
                        <span className="badge badge-amber" style={{ fontSize: "0.64rem" }}>
                          {pick.originalOwner}
                        </span>
                      ) : (
                        <span className="muted">&mdash;</span>
                      )}
                    </td>
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

"use client";

// DraftCapitalSection — public /league tab view.
// Shows the live auction-dollar draft capital board from /api/draft-capital.
// Purely public data (same endpoint powered the old /draft-capital page).
// When this tab is the default, /league mobile users land here.

import { useEffect, useMemo, useState } from "react";
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

      <TradeSimulator picks={data.picks} teamTotals={data.teamTotals} />

      <PicksByRound picks={data.picks} draftRounds={data.draftRounds} />
    </>
  );
}

/* ── Trade simulator ───────────────────────────────────────────────────── */
// What-if calculator: pick two teams, toggle which picks each sends,
// see post-trade auction-dollar totals.  Pure client math — no backend
// state, nothing persisted.  Pre-trade totals come from the visible
// teamTotals (so they always match the chart above), and post-trade =
// pre - sum(sent) + sum(received).  Net stays constant across teams.
function TradeSimulator({ picks, teamTotals }) {
  const teams = useMemo(
    () => (teamTotals || []).map((t) => t.team).filter(Boolean),
    [teamTotals],
  );
  const totalsByTeam = useMemo(() => {
    const m = new Map();
    for (const t of teamTotals || []) m.set(t.team, t.auctionDollars || 0);
    return m;
  }, [teamTotals]);

  const [teamA, setTeamA] = useState(teams[0] || "");
  const [teamB, setTeamB] = useState(teams[1] || "");
  const [sentFromA, setSentFromA] = useState(() => new Set());
  const [sentFromB, setSentFromB] = useState(() => new Set());

  // Default both selectors once team list arrives.
  useEffect(() => {
    if (!teams.length) return;
    setTeamA((prev) => (prev && teams.includes(prev) ? prev : teams[0]));
    setTeamB((prev) => (prev && teams.includes(prev) ? prev : teams[1] || teams[0]));
  }, [teams]);

  // Reset selections when either team changes.
  useEffect(() => {
    setSentFromA(new Set());
    setSentFromB(new Set());
  }, [teamA, teamB]);

  const picksA = useMemo(
    () => (picks || []).filter((p) => p.currentOwner === teamA)
                       .sort((a, b) => a.overallPick - b.overallPick),
    [picks, teamA],
  );
  const picksB = useMemo(
    () => (picks || []).filter((p) => p.currentOwner === teamB)
                       .sort((a, b) => a.overallPick - b.overallPick),
    [picks, teamB],
  );

  const pickValue = (p) => p.adjustedDollarValue ?? p.dollarValue ?? 0;
  const sumSelected = (list, selected) =>
    list.filter((p) => selected.has(p.pick)).reduce((s, p) => s + pickValue(p), 0);

  const sumOutA = sumSelected(picksA, sentFromA);
  const sumOutB = sumSelected(picksB, sentFromB);

  const preA = totalsByTeam.get(teamA) || 0;
  const preB = totalsByTeam.get(teamB) || 0;
  const postA = preA - sumOutA + sumOutB;
  const postB = preB - sumOutB + sumOutA;
  const deltaA = postA - preA;
  const deltaB = postB - preB;

  const togglePick = (side, pickId) => {
    if (side === "A") {
      setSentFromA((prev) => {
        const next = new Set(prev);
        if (next.has(pickId)) next.delete(pickId);
        else next.add(pickId);
        return next;
      });
    } else {
      setSentFromB((prev) => {
        const next = new Set(prev);
        if (next.has(pickId)) next.delete(pickId);
        else next.add(pickId);
        return next;
      });
    }
  };

  const swapTeams = () => {
    setTeamA(teamB);
    setTeamB(teamA);
  };
  const reset = () => {
    setSentFromA(new Set());
    setSentFromB(new Set());
  };

  const sameTeam = teamA && teamB && teamA === teamB;
  const anySelected = sentFromA.size > 0 || sentFromB.size > 0;

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: "var(--space-sm)",
          marginBottom: "var(--space-sm)",
          flexWrap: "wrap",
        }}
      >
        <span style={{ fontWeight: 700, fontSize: "0.88rem" }}>Trade Simulator</span>
        <span className="text-xs muted">
          Pick two teams, toggle the picks each sends, and see how the auction dollars shake out.
        </span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <button
            type="button"
            onClick={swapTeams}
            disabled={!teamA || !teamB || sameTeam}
            style={simBtnStyle}
          >
            Swap
          </button>
          <button
            type="button"
            onClick={reset}
            disabled={!anySelected}
            style={simBtnStyle}
          >
            Reset
          </button>
        </div>
      </div>

      <div className="trade-sim-grid">
        <TradeSimulatorSide
          label="Team A"
          team={teamA}
          onTeamChange={setTeamA}
          teams={teams}
          picks={picksA}
          selected={sentFromA}
          onTogglePick={(id) => togglePick("A", id)}
          incoming={picksB.filter((p) => sentFromB.has(p.pick))}
          pre={preA}
          post={postA}
          delta={deltaA}
          sumOut={sumOutA}
          sumIn={sumOutB}
          sameTeam={sameTeam}
        />
        <TradeSimulatorSide
          label="Team B"
          team={teamB}
          onTeamChange={setTeamB}
          teams={teams}
          picks={picksB}
          selected={sentFromB}
          onTogglePick={(id) => togglePick("B", id)}
          incoming={picksA.filter((p) => sentFromA.has(p.pick))}
          pre={preB}
          post={postB}
          delta={deltaB}
          sumOut={sumOutB}
          sumIn={sumOutA}
          sameTeam={sameTeam}
        />
      </div>

      <style jsx>{`
        .trade-sim-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: var(--space-md);
        }
        @media (max-width: 720px) {
          .trade-sim-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
}

const simBtnStyle = {
  background: "transparent",
  border: "1px solid var(--border-bright)",
  borderRadius: 6,
  color: "var(--cyan)",
  padding: "3px 10px",
  fontSize: "0.7rem",
  cursor: "pointer",
};

function TradeSimulatorSide({
  label,
  team,
  onTeamChange,
  teams,
  picks,
  selected,
  onTogglePick,
  incoming,
  pre,
  post,
  delta,
  sumOut,
  sumIn,
  sameTeam,
}) {
  const deltaColor =
    delta > 0 ? "var(--green)" : delta < 0 ? "var(--red, #f87171)" : "var(--subtext)";
  const deltaSign = delta > 0 ? "+" : "";

  return (
    <div
      style={{
        background: "rgba(255,255,255,0.02)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-sm)",
        padding: "var(--space-sm)",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span
          style={{
            fontSize: "0.62rem",
            color: "var(--muted)",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
          }}
        >
          {label}
        </span>
        <select
          className="input"
          value={team}
          onChange={(e) => onTeamChange(e.target.value)}
          style={{ flex: 1, fontSize: "0.78rem", padding: "3px 6px" }}
          aria-label={`Select ${label}`}
        >
          {teams.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>

      {sameTeam ? (
        <div
          style={{
            fontSize: "0.72rem",
            color: "var(--amber)",
            padding: "var(--space-sm) 0",
          }}
        >
          Pick a different team on each side.
        </div>
      ) : (
        <>
          <div style={{ fontSize: "0.66rem", color: "var(--muted)", marginTop: 2 }}>
            Send picks (click to toggle):
          </div>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 2,
              maxHeight: 280,
              overflowY: "auto",
            }}
          >
            {picks.length === 0 && (
              <div className="muted" style={{ fontSize: "0.72rem" }}>
                No picks owned.
              </div>
            )}
            {picks.map((p) => {
              const isSel = selected.has(p.pick);
              return (
                <button
                  key={p.pick}
                  type="button"
                  onClick={() => onTogglePick(p.pick)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "4px 8px",
                    border: `1px solid ${isSel ? "var(--cyan)" : "var(--border)"}`,
                    borderRadius: 4,
                    background: isSel ? "rgba(34,211,238,0.10)" : "transparent",
                    color: "inherit",
                    cursor: "pointer",
                    textAlign: "left",
                    fontSize: "0.74rem",
                  }}
                >
                  <span
                    aria-hidden
                    style={{
                      width: 14,
                      height: 14,
                      borderRadius: 3,
                      border: "1px solid var(--border-bright)",
                      background: isSel ? "var(--cyan)" : "transparent",
                      flexShrink: 0,
                    }}
                  />
                  <span className="font-mono font-bold" style={{ minWidth: 42 }}>
                    {p.pick}
                  </span>
                  <span
                    className="font-mono"
                    style={{
                      marginLeft: "auto",
                      fontWeight: 700,
                      color: "var(--green)",
                    }}
                  >
                    {fmtDollar(p.adjustedDollarValue ?? p.dollarValue)}
                  </span>
                  {p.isTraded && (
                    <span
                      className="badge badge-amber"
                      style={{ fontSize: "0.6rem", padding: "0 4px" }}
                      title={`Originally ${p.originalOwner}`}
                    >
                      *
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {incoming.length > 0 && (
            <>
              <div
                style={{
                  fontSize: "0.66rem",
                  color: "var(--muted)",
                  marginTop: 6,
                }}
              >
                Receiving:
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {incoming.map((p) => (
                  <span
                    key={p.pick}
                    className="font-mono"
                    style={{
                      fontSize: "0.7rem",
                      padding: "2px 6px",
                      border: "1px solid var(--border-bright)",
                      borderRadius: 4,
                      background: "rgba(255,199,4,0.08)",
                    }}
                  >
                    {p.pick}{" "}
                    <span style={{ color: "var(--green)", fontWeight: 700 }}>
                      {fmtDollar(p.adjustedDollarValue ?? p.dollarValue)}
                    </span>
                  </span>
                ))}
              </div>
            </>
          )}

          <div
            style={{
              marginTop: 8,
              paddingTop: 8,
              borderTop: "1px solid var(--border)",
              display: "grid",
              gridTemplateColumns: "1fr auto",
              rowGap: 2,
              columnGap: 12,
              fontSize: "0.74rem",
            }}
          >
            <span className="muted">Pre-trade</span>
            <span className="font-mono" style={{ textAlign: "right" }}>
              {fmtDollar(pre)}
            </span>
            <span className="muted">Sending</span>
            <span className="font-mono" style={{ textAlign: "right", color: "var(--red, #f87171)" }}>
              -{fmtDollar(sumOut)}
            </span>
            <span className="muted">Receiving</span>
            <span className="font-mono" style={{ textAlign: "right", color: "var(--green)" }}>
              +{fmtDollar(sumIn)}
            </span>
            <span style={{ fontWeight: 700 }}>Post-trade</span>
            <span
              className="font-mono"
              style={{ textAlign: "right", fontWeight: 700, color: "var(--green)" }}
            >
              {fmtDollar(post)}
            </span>
            <span className="muted">Net change</span>
            <span
              className="font-mono"
              style={{ textAlign: "right", fontWeight: 700, color: deltaColor }}
            >
              {deltaSign}
              {fmtDollar(delta)}
            </span>
          </div>
        </>
      )}
    </div>
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

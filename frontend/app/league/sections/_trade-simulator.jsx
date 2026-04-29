"use client";

// Draft-capital trade simulator — split out of draft-capital.jsx and
// dynamically imported so its weight doesn't count against the
// /league page-bundle budget.  Pure client math: pre-trade totals
// come from the visible teamTotals (so they always match the chart
// above), and post-trade = pre - sum(sent) + sum(received).  Net
// stays constant across the league.

import { useEffect, useMemo, useState } from "react";

function fmtDollar(v) {
  if (v == null) return "$0";
  return `$${Math.round(v)}`;
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

export default function TradeSimulator({ picks, teamTotals }) {
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

  useEffect(() => {
    if (!teams.length) return;
    setTeamA((prev) => (prev && teams.includes(prev) ? prev : teams[0]));
    setTeamB((prev) => (prev && teams.includes(prev) ? prev : teams[1] || teams[0]));
  }, [teams]);

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
    const setter = side === "A" ? setSentFromA : setSentFromB;
    setter((prev) => {
      const next = new Set(prev);
      if (next.has(pickId)) next.delete(pickId);
      else next.add(pickId);
      return next;
    });
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
              <div style={{ fontSize: "0.66rem", color: "var(--muted)", marginTop: 6 }}>
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

"use client";

import { useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useSettings } from "@/components/useSettings";
import { PageHeader, LoadingState, EmptyState } from "@/components/ui";
import { TRADE_ALPHA } from "@/lib/trade-logic";
import {
  analyzeSleeperTradeHistory,
  analyzeTradeTendencies,
  POS_GROUP_COLORS,
} from "@/lib/league-analysis";

const POS_COLORS = {
  QB: "#e74c3c", RB: "#27ae60", WR: "#3498db", TE: "#e67e22",
  PICK: "var(--amber)", DL: "#9b59b6", LB: "#8e44ad", DB: "#16a085",
};

export default function TradesPage() {
  const { rows, rawData, loading, error } = useApp();
  const { settings } = useSettings();
  const [teamFilter, setTeamFilter] = useState("");

  const alpha = settings.alpha || TRADE_ALPHA;
  const windowDays = settings.tradeHistoryWindowDays || 365;

  const analysis = useMemo(
    () => analyzeSleeperTradeHistory(rawData, rows, windowDays, alpha),
    [rawData, rows, windowDays, alpha],
  );

  const teams = useMemo(() => {
    const set = new Set();
    for (const a of analysis.analyzed) {
      for (const s of a.sides) set.add(s.team);
    }
    return [...set].sort();
  }, [analysis]);

  const filtered = useMemo(() => {
    if (!teamFilter) return analysis.analyzed;
    return analysis.analyzed.filter((a) =>
      a.sides.some((s) => s.team === teamFilter),
    );
  }, [analysis, teamFilter]);

  const tendencies = useMemo(
    () => analyzeTradeTendencies(rawData, rows),
    [rawData, rows],
  );

  if (loading) return <LoadingState message="Loading trade data..." />;
  if (error) return <div className="card"><EmptyState title="Error" message={error} /></div>;

  const hasTrades = analysis.analyzed.length > 0;

  return (
    <section>
      <div className="card">
        <PageHeader
          title="Trade History"
          subtitle={`Analyzing ${analysis.analyzed.length} trades in the last ${windowDays} days using alpha=${alpha}`}
          actions={
            teams.length > 0 && (
              <select
                className="input"
                value={teamFilter}
                onChange={(e) => setTeamFilter(e.target.value)}
                style={{ minWidth: 160 }}
              >
                <option value="">All teams</option>
                {teams.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            )
          }
        />
      </div>

      {!hasTrades && (
        <div className="card">
          <EmptyState
            title="No trades found"
            message="Load dynasty data with a Sleeper league to see trade history."
          />
        </div>
      )}

      {/* Winners & Losers stats card */}
      {hasTrades && <TeamScoresCard teamScores={analysis.teamScores} alpha={alpha} />}

      {/* Trade tendencies */}
      {hasTrades && tendencies.length > 0 && <TradeTendenciesCard tendencies={tendencies} />}

      {/* Trade list */}
      {filtered.length > 0 && (
        <div className="list" style={{ marginTop: "var(--space-md)" }}>
          {filtered.map((a, idx) => (
            <TradeCard key={idx} analysis={a} />
          ))}
        </div>
      )}

      {teamFilter && filtered.length === 0 && (
        <div className="card">
          <EmptyState title="No trades match" message={`No trades found for ${teamFilter}.`} />
        </div>
      )}
    </section>
  );
}

function TeamScoresCard({ teamScores, alpha }) {
  const sorted = useMemo(
    () => Object.values(teamScores).sort((a, b) => b.totalGain - a.totalGain),
    [teamScores],
  );

  if (!sorted.length) return null;

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, fontSize: "0.82rem", marginBottom: 10 }}>
        Trade Winners & Losers
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 8 }}>
        {sorted.map((s) => {
          const teamName = s.displayName || "Unknown";
          const netVal = Math.round(Math.pow(Math.abs(s.totalGain), 1 / alpha));
          const netSign = s.totalGain >= 0 ? "+" : "-";
          const netColor = s.totalGain >= 0 ? "var(--green)" : "var(--red)";
          const borderColor = s.totalGain >= 0 ? "var(--green)" : s.totalGain < -50 ? "var(--red)" : "var(--border)";

          return (
            <div
              key={s.rosterId != null ? `rid:${s.rosterId}` : `name:${teamName}`}
              style={{
                border: "1px solid var(--border)",
                borderLeft: `3px solid ${borderColor}`,
                borderRadius: 6,
                padding: "10px 14px",
              }}
            >
              <div style={{ fontWeight: 700, fontSize: "0.78rem" }}>{teamName}</div>
              <div style={{ fontFamily: "var(--mono)", fontSize: "0.68rem", color: "var(--subtext)", margin: "2px 0" }}>
                {s.trades} trades &middot; {s.won}W-{s.lost}L
              </div>
              <div style={{ fontFamily: "var(--mono)", fontSize: "0.75rem", fontWeight: 700, color: netColor }}>
                {netSign}{netVal.toLocaleString()} net value
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TradeTendenciesCard({ tendencies }) {
  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, fontSize: "0.82rem", marginBottom: 10 }}>
        Trade Tendencies
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Manager</th>
              <th style={{ textAlign: "right" }}>Trades</th>
              <th style={{ textAlign: "right" }}>Avg Given</th>
              <th style={{ textAlign: "right" }}>Avg Got</th>
              <th style={{ textAlign: "right" }}>Net</th>
              <th>Tendency</th>
            </tr>
          </thead>
          <tbody>
            {tendencies.map((t) => {
              const netColor = t.net >= 0 ? "var(--green)" : "var(--red)";
              const netSign = t.net >= 0 ? "+" : "";
              return (
                <tr key={t.manager}>
                  <td style={{ fontWeight: 600 }}>{t.manager}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{t.trades}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{t.avgGiven.toLocaleString()}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{t.avgGot.toLocaleString()}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)", fontWeight: 700, color: netColor }}>
                    {netSign}{t.net.toLocaleString()}
                  </td>
                  <td style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>{t.tendency}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TradeCard({ analysis: a }) {
  return (
    <div
      className="card"
      style={{
        borderLeft: a.pctGap >= 3
          ? `3px solid ${a.winner === a.sides[0] ? "var(--green)" : "var(--red)"}`
          : "3px solid var(--green)",
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{ fontSize: "0.68rem", color: "var(--subtext)" }}>
          Week {a.trade.week} &middot; {a.date}
        </span>
        {a.pctGap >= 3 ? (
          <span className="badge" style={{ background: "var(--green-soft)", color: "var(--green)" }}>
            {a.winner.team} won by {a.pctGap.toFixed(1)}%
          </span>
        ) : (
          <span className="badge" style={{ background: "var(--green-soft)", color: "var(--green)" }}>
            Fair trade
          </span>
        )}
      </div>

      {/* Sides */}
      <div className="grid-responsive" style={{ display: "grid", gridTemplateColumns: a.sides.length > 2 ? "1fr 1fr 1fr" : "1fr 1fr", gap: 12 }}>
        {a.sides.map((side, i) => {
          const isWinner = side === a.winner && a.pctGap >= 3;
          const isLoser = side === a.loser && a.pctGap >= 3;
          const grade = isWinner ? a.winnerGrade : isLoser ? a.loserGrade : { grade: "A", color: "var(--green)", label: "Fair" };

          return (
            <div key={i}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                <span style={{ fontWeight: 600, fontSize: "0.74rem" }}>{side.team}</span>
                {grade && (
                  <>
                    <span style={{ fontSize: "0.72rem", fontWeight: 800, color: grade.color }}>{grade.grade}</span>
                    <span style={{ fontSize: "0.52rem", color: "var(--subtext)" }}>{grade.label}</span>
                  </>
                )}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 4 }}>
                {side.items.map((item, j) => {
                  const posLabel = item.isPick ? "PICK" : item.pos;
                  const posColor = item.isPick ? POS_COLORS.PICK : (POS_COLORS[item.pos] || "#9b59b6");
                  return (
                    <span
                      key={j}
                      style={{
                        fontSize: "0.66rem",
                        padding: "2px 6px",
                        border: "1px solid var(--border)",
                        borderRadius: 4,
                        background: "var(--bg-soft)",
                      }}
                    >
                      <span style={{ color: posColor, fontWeight: 700, fontSize: "0.58rem" }}>{posLabel}</span>{" "}
                      {item.name}{" "}
                      <span style={{ fontFamily: "var(--mono)", color: "var(--subtext)" }}>{item.val.toLocaleString()}</span>
                    </span>
                  );
                })}
              </div>
              <div style={{ fontFamily: "var(--mono)", fontSize: "0.62rem", color: "var(--subtext)" }}>
                Total: {Math.round(side.weighted).toLocaleString()}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

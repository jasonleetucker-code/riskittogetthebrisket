"use client";

import { useMemo, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { useApp } from "@/components/AppShell";

export default function FinderPage() {
  const { loading, error, rawData } = useDynastyData();
  const { openPlayerPopup, rows } = useApp();
  const rowByName = useMemo(() => new Map(rows.map((r) => [r.name, r])), [rows]);

  const [myTeam, setMyTeam] = useState("");
  const [running, setRunning] = useState(false);
  const [trades, setTrades] = useState(null);
  const [meta, setMeta] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const [apiError, setApiError] = useState("");
  const [filterShape, setFilterShape] = useState("all");

  const sleeperTeams = useMemo(() => {
    const teams = rawData?.sleeper?.teams;
    return Array.isArray(teams) && teams.length > 0 ? teams : null;
  }, [rawData]);

  async function runFinder() {
    if (!myTeam) return;
    setRunning(true);
    setApiError("");
    setTrades(null);
    setMeta(null);
    setWarnings([]);
    try {
      const res = await fetch("/api/trade/finder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ myTeam, opponentTeams: ["all"] }),
      });
      const data = await res.json();
      if (!res.ok) {
        setApiError(data.error || `Error ${res.status}`);
        return;
      }
      setTrades(data.trades || []);
      setMeta(data.metadata || null);
      setWarnings(data.warnings || []);
    } catch (e) {
      setApiError(e.message || "Network error");
    } finally {
      setRunning(false);
    }
  }

  const filtered = useMemo(() => {
    if (!trades) return [];
    if (filterShape === "all") return trades;
    return trades.filter((t) => t.packageSize === filterShape);
  }, [trades, filterShape]);

  const shapes = useMemo(() => {
    if (!trades) return [];
    const s = new Set(trades.map((t) => t.packageSize));
    return ["all", ...Array.from(s).sort()];
  }, [trades]);

  function edgeBadge(label) {
    const cls = (label || "").includes("Strong")
      ? { bg: "rgba(39,174,96,0.2)", color: "var(--green)" }
      : (label || "").includes("Moderate")
        ? { bg: "rgba(230,126,34,0.2)", color: "var(--amber, orange)" }
        : { bg: "rgba(140,140,140,0.15)", color: "var(--subtext, gray)" };
    return <span className="badge" style={{ background: cls.bg, color: cls.color, fontWeight: 700 }}>{label || "Edge"}</span>;
  }

  function confBadge(tier) {
    const color = tier === "high" ? "var(--green)" : tier === "moderate" ? "var(--amber, orange)" : "var(--subtext, gray)";
    return <span style={{ color, fontWeight: 600, fontSize: "0.76rem", textTransform: "capitalize" }}>{tier}</span>;
  }

  function playerChip(p) {
    const r = rowByName.get(p.name);
    return (
      <span
        key={p.name}
        style={{ cursor: r ? "pointer" : "default", fontWeight: 600 }}
        onClick={() => r && openPlayerPopup?.(r)}
      >
        <span className="badge" style={{ fontSize: "0.64rem", marginRight: 4 }}>{p.position}</span>
        {p.name}
        <span className="muted" style={{ marginLeft: 4, fontSize: "0.72rem" }}>
          ({(p.modelValue || 0).toLocaleString()})
        </span>
      </span>
    );
  }

  return (
    <section className="card">
      <h1 style={{ margin: 0 }}>Trade Finder</h1>
      <p className="muted" style={{ marginTop: 4 }}>
        Finds board-arbitrage trades: good for you on our model, plausible for them on KTC market values.
      </p>

      {loading && <p style={{ marginTop: 16 }}>Loading data...</p>}
      {!!error && <p style={{ color: "var(--red)", marginTop: 16 }}>{error}</p>}

      {!loading && !error && (
        <>
          {!sleeperTeams ? (
            <p className="muted" style={{ marginTop: 16 }}>
              No Sleeper league data available. Trade Finder requires Sleeper rosters to find trades.
            </p>
          ) : (
            <>
              <div className="row" style={{ marginTop: 14, gap: 10 }}>
                <select
                  className="select"
                  value={myTeam}
                  onChange={(e) => setMyTeam(e.target.value)}
                  style={{ minWidth: 200 }}
                >
                  <option value="">Select your team...</option>
                  {sleeperTeams.map((t) => (
                    <option key={t.name} value={t.name}>{t.name}</option>
                  ))}
                </select>
                <button
                  className="button"
                  onClick={runFinder}
                  disabled={!myTeam || running}
                >
                  {running ? "Searching..." : "Find Trades"}
                </button>
              </div>

              {!!apiError && <p style={{ color: "var(--red)", marginTop: 12 }}>{apiError}</p>}
              {warnings.map((w, i) => (
                <p key={i} className="muted" style={{ marginTop: 8, fontSize: "0.78rem", color: "var(--amber, orange)" }}>{w}</p>
              ))}

              {meta && (
                <div className="muted" style={{ marginTop: 12, fontSize: "0.78rem" }}>
                  Analyzed {meta.opponentsAnalyzed} opponents · {meta.totalCandidatesEvaluated?.toLocaleString()} candidates ·{" "}
                  {meta.totalQualified} qualified · Showing {meta.returned}
                  {meta.ktcCoveragePercent != null && ` · KTC coverage: ${meta.ktcCoveragePercent}%`}
                </div>
              )}

              {trades && trades.length > 0 && (
                <>
                  <div className="row" style={{ marginTop: 10, gap: 8 }}>
                    <select className="select" value={filterShape} onChange={(e) => setFilterShape(e.target.value)}>
                      {shapes.map((s) => (
                        <option key={s} value={s}>{s === "all" ? "All shapes" : s}</option>
                      ))}
                    </select>
                    <span className="muted" style={{ fontSize: "0.78rem", alignSelf: "center" }}>
                      {filtered.length} trades
                    </span>
                  </div>

                  <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 12 }}>
                    {filtered.map((t, i) => (
                      <div key={i} className="card" style={{ padding: 14 }}>
                        {/* Header */}
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                            {edgeBadge(t.edgeLabel)}
                            {confBadge(t.confidenceTier)}
                            <span className="badge" style={{ fontSize: "0.68rem" }}>{t.packageSize}</span>
                          </div>
                          <span style={{ fontWeight: 700, color: "var(--green)", fontFamily: "var(--mono, monospace)" }}>
                            +{t.boardDelta?.toLocaleString()} edge
                          </span>
                        </div>

                        {/* Give / Receive */}
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                          <div>
                            <div className="muted" style={{ fontSize: "0.72rem", marginBottom: 4 }}>You Give</div>
                            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                              {t.give.map((p) => <div key={p.name}>{playerChip(p)}</div>)}
                            </div>
                            <div className="muted" style={{ fontSize: "0.72rem", marginTop: 4 }}>
                              Model: {t.giveModelTotal?.toLocaleString()} · KTC: {t.giveKtcTotal?.toLocaleString()}
                            </div>
                          </div>
                          <div>
                            <div className="muted" style={{ fontSize: "0.72rem", marginBottom: 4 }}>You Get</div>
                            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                              {t.receive.map((p) => <div key={p.name}>{playerChip(p)}</div>)}
                            </div>
                            <div className="muted" style={{ fontSize: "0.72rem", marginTop: 4 }}>
                              Model: {t.receiveModelTotal?.toLocaleString()} · KTC: {t.receiveKtcTotal?.toLocaleString()}
                            </div>
                          </div>
                        </div>

                        {/* Summary */}
                        {t.summary && (
                          <p className="muted" style={{ fontSize: "0.76rem", marginTop: 8, marginBottom: 0 }}>{t.summary}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}

              {trades && trades.length === 0 && (
                <p className="muted" style={{ marginTop: 16 }}>
                  No arbitrage trades found. This means the market is efficient relative to your roster, or KTC coverage is too low.
                </p>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}

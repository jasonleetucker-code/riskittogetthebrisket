"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { RANKING_SOURCES } from "@/lib/dynasty-data";
import {
  VALUE_MODES,
  STORAGE_KEY,
  RECENT_KEY,
  verdictFromGap,
  colorFromGap,
  verdictBarPosition,
  powerWeightedTotal,
  sideTotal,
  effectiveValue,
  getPlayerEdge,
  findBalancers,
} from "@/lib/trade-logic";
import { useSettings } from "@/components/useSettings";
import { useApp } from "@/components/AppShell";

const ROSTER_KEY = "next_trade_roster_v1";
const TEAM_KEY = "next_trade_team_v1";
const SUGG_TYPES = [
  { key: "sellHigh", label: "Sell High" },
  { key: "buyLow", label: "Buy Low" },
  { key: "consolidation", label: "Consolidation" },
  { key: "positionalUpgrades", label: "Upgrades" },
];

function fairnessColor(f) {
  if (f === "even") return "var(--green)";
  if (f === "lean") return "var(--cyan)";
  return "var(--red)";
}

function fairnessLabel(f) {
  if (f === "even") return "Even value";
  if (f === "lean") return "Slight lean";
  return "Stretch";
}

function confidenceBadge(c) {
  if (c === "high") return { label: "High consensus", bg: "rgba(52,211,153,0.15)", border: "rgba(52,211,153,0.4)", color: "var(--green)" };
  if (c === "medium") return { label: "Moderate consensus", bg: "rgba(86,214,255,0.12)", border: "rgba(86,214,255,0.35)", color: "var(--cyan)" };
  return { label: "Low consensus", bg: "rgba(153,166,200,0.1)", border: "var(--border)", color: "var(--muted)" };
}

function edgeBadge(edge) {
  if (!edge) return null;
  if (edge === "market_discount") return { text: "Buy Low", bg: "rgba(52,211,153,0.15)", color: "var(--green)" };
  if (edge === "market_premium") return { text: "Sell High", bg: "rgba(248,113,113,0.15)", color: "var(--red)" };
  if (edge === "high_dispersion") return { text: "Sources Disagree", bg: "rgba(251,191,36,0.15)", color: "#fbbf24" };
  return null;
}

export default function TradePage() {
  const { loading, error, rows, rawData } = useDynastyData();
  const { settings } = useSettings();
  const { openPlayerPopup, registerAddToTrade } = useApp();
  const [valueMode, setValueMode] = useState("full");
  const [pickerSortCol, setPickerSortCol] = useState("rank");
  const [pickerSortAsc, setPickerSortAsc] = useState(true);
  const [sideA, setSideA] = useState([]);
  const [sideB, setSideB] = useState([]);
  const [activeSide, setActiveSide] = useState("A");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const [pickerFilter, setPickerFilter] = useState("all");
  const [recentNames, setRecentNames] = useState([]);
  const [hydrated, setHydrated] = useState(false);
  const pickerInputRef = useRef(null);

  // Suggestions state
  const [rosterInput, setRosterInput] = useState("");
  const [suggestions, setSuggestions] = useState(null);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [suggestionsError, setSuggestionsError] = useState(null);
  const [suggestionTab, setSuggestionTab] = useState("sellHigh");

  // Sleeper team selection state
  const [selectedTeamIdx, setSelectedTeamIdx] = useState(-1);
  const [leagueRosters, setLeagueRosters] = useState(null);

  // Extract Sleeper teams from dynasty data
  const sleeperTeams = useMemo(() => {
    const teams = rawData?.sleeper?.teams;
    return Array.isArray(teams) && teams.length > 0 ? teams : null;
  }, [rawData]);

  const rowByName = useMemo(() => {
    const m = new Map();
    rows.forEach((r) => m.set(r.name, r));
    return m;
  }, [rows]);

  // Hydrate roster input, team selection, and recent names from localStorage
  useEffect(() => {
    try {
      const saved = localStorage.getItem(ROSTER_KEY);
      if (saved) setRosterInput(saved);
    } catch { /* ignore */ }
    try {
      const savedTeam = localStorage.getItem(TEAM_KEY);
      if (savedTeam !== null) setSelectedTeamIdx(Number(savedTeam));
    } catch { /* ignore */ }
    try {
      const rawRecent = localStorage.getItem(RECENT_KEY);
      if (rawRecent) {
        const parsed = JSON.parse(rawRecent);
        if (Array.isArray(parsed)) setRecentNames(parsed.filter((x) => typeof x === "string").slice(0, 20));
      }
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (!rows.length || hydrated) return;
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === "object") {
          const nextMode = String(parsed.valueMode || "full");
          if (VALUE_MODES.some((m) => m.key === nextMode)) setValueMode(nextMode);
          setActiveSide(parsed.activeSide === "B" ? "B" : "A");
          const a = Array.isArray(parsed.sideA) ? parsed.sideA.map((n) => rowByName.get(n)).filter(Boolean) : [];
          const b = Array.isArray(parsed.sideB) ? parsed.sideB.map((n) => rowByName.get(n)).filter(Boolean) : [];
          setSideA(a);
          setSideB(b);
        }
      }
    } catch { /* ignore */ } finally { setHydrated(true); }
  }, [rows, hydrated, rowByName]);

  useEffect(() => {
    if (!hydrated) return;
    const payload = { valueMode, activeSide, sideA: sideA.map((r) => r.name), sideB: sideB.map((r) => r.name) };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  }, [hydrated, valueMode, activeSide, sideA, sideB]);

  useEffect(() => {
    if (pickerOpen && pickerInputRef.current) pickerInputRef.current.focus();
  }, [pickerOpen]);

  const pwTotalA = useMemo(() => powerWeightedTotal(sideA, valueMode, undefined, settings), [sideA, valueMode, settings]);
  const pwTotalB = useMemo(() => powerWeightedTotal(sideB, valueMode, undefined, settings), [sideB, valueMode, settings]);
  const linTotalA = useMemo(() => sideTotal(sideA, valueMode, settings), [sideA, valueMode, settings]);
  const linTotalB = useMemo(() => sideTotal(sideB, valueMode, settings), [sideB, valueMode, settings]);
  const pwGap = pwTotalA - pwTotalB;
  const linGap = linTotalA - linTotalB;
  // Percentage gap for proportional verdict
  const pctGap = Math.max(pwTotalA, pwTotalB) > 0 ? Math.round(Math.abs(pwGap) / Math.max(pwTotalA, pwTotalB) * 100) : 0;
  // Balancing suggestions for the losing side
  const balancers = useMemo(() => {
    if (Math.abs(pwGap) < 350) return [];
    const losingRows = pwGap > 0 ? rows.filter((r) => !sideA.some((a) => a.name === r.name) && !sideB.some((b) => b.name === r.name)) : rows.filter((r) => !sideA.some((a) => a.name === r.name) && !sideB.some((b) => b.name === r.name));
    return findBalancers(pwGap, losingRows, valueMode);
  }, [pwGap, rows, sideA, sideB, valueMode]);

  const pickerRows = useMemo(() => {
    const q = pickerQuery.trim().toLowerCase();
    const isInTrade = new Set([...sideA, ...sideB].map((r) => r.name));
    let list = rows.filter((r) => !isInTrade.has(r.name));
    if (pickerFilter !== "all") list = list.filter((r) => r.assetClass === pickerFilter);
    if (q) list = list.filter((r) => r.name.toLowerCase().includes(q));
    // Sort by selected column
    const dir = pickerSortAsc ? 1 : -1;
    list = [...list].sort((a, b) => {
      let va, vb;
      switch (pickerSortCol) {
        case "rank":
          va = a.blendedSourceRank ?? Infinity; vb = b.blendedSourceRank ?? Infinity;
          return (va - vb) * dir;
        case "name":
          return a.name.localeCompare(b.name) * dir;
        case "pos":
          return (a.pos || "").localeCompare(b.pos || "") * dir;
        case "value":
          va = a.rankDerivedValue || a.values?.full || 0; vb = b.rankDerivedValue || b.values?.full || 0;
          return (va - vb) * dir;
        default: {
          // Dynamic per-source sort column: "src:<sourceKey>".  Keeps
          // the picker column set self-describing so newly registered
          // sources appear automatically.
          if (typeof pickerSortCol === "string" && pickerSortCol.startsWith("src:")) {
            const key = pickerSortCol.slice(4);
            va = Number(a.canonicalSites?.[key]) || 0;
            vb = Number(b.canonicalSites?.[key]) || 0;
            return (va - vb) * dir;
          }
          va = a.blendedSourceRank ?? Infinity; vb = b.blendedSourceRank ?? Infinity;
          return (va - vb) * dir;
        }
      }
    });
    return list.slice(0, 100);
  }, [rows, sideA, sideB, pickerQuery, pickerFilter, pickerSortCol, pickerSortAsc]);

  const recentRows = useMemo(() => recentNames.map((n) => rowByName.get(n)).filter(Boolean), [recentNames, rowByName]);

  function addRecent(name) {
    setRecentNames((prev) => {
      const next = [name, ...prev.filter((x) => x !== name)].slice(0, 20);
      localStorage.setItem(RECENT_KEY, JSON.stringify(next));
      return next;
    });
  }

  function addToSide(row, side) {
    if (!row) return;
    if (sideA.some((r) => r.name === row.name) || sideB.some((r) => r.name === row.name)) return;
    if (side === "A") setSideA((prev) => (prev.some((r) => r.name === row.name) ? prev : [...prev, row]));
    else setSideB((prev) => (prev.some((r) => r.name === row.name) ? prev : [...prev, row]));
    addRecent(row.name);
  }

  function addToActiveSide(row) { addToSide(row, activeSide); }

  // Register add-to-trade callback so popup/search can add players
  useEffect(() => {
    registerAddToTrade?.(addToActiveSide);
    return () => registerAddToTrade?.(null);
  }, [registerAddToTrade, activeSide]); // eslint-disable-line react-hooks/exhaustive-deps

  function removeFromSide(name, side) {
    if (side === "A") setSideA((prev) => prev.filter((r) => r.name !== name));
    else setSideB((prev) => prev.filter((r) => r.name !== name));
  }

  function clearTrade() { setSideA([]); setSideB([]); }

  function swapSides() {
    setSideA(sideB);
    setSideB(sideA);
    setActiveSide((s) => (s === "A" ? "B" : "A"));
  }

  function openPickerFor(side) { setActiveSide(side); setPickerOpen(true); }

  // ── Suggestions logic ─────────────────────────────────────────────
  const parseRoster = useCallback(() => {
    return rosterInput
      .split(/[,\n]+/)
      .map((s) => s.trim())
      .filter(Boolean);
  }, [rosterInput]);

  function selectTeam(idx) {
    const i = Number(idx);
    setSelectedTeamIdx(i);
    localStorage.setItem(TEAM_KEY, String(i));

    if (i < 0 || !sleeperTeams || !sleeperTeams[i]) {
      setLeagueRosters(null);
      return;
    }

    const team = sleeperTeams[i];
    // Combine players + picks (picks stripped of provenance suffixes)
    const picks = (team.picks || []).map((p) => {
      // "2026 1.06 (from Pop Trunk)" → "2026 1st" style normalization
      const m = p.match(/^(\d{4})\s+(\d)\./);
      if (m) {
        const round = { "1": "1st", "2": "2nd", "3": "3rd", "4": "4th" }[m[2]] || `${m[2]}th`;
        return `${m[1]} ${round}`;
      }
      return p.replace(/\s*\(.*\)/, "").trim();
    });
    // Deduplicate picks (team may own multiple of the same round)
    const rosterNames = [...(team.players || []), ...picks];
    const newInput = rosterNames.join("\n");
    setRosterInput(newInput);
    localStorage.setItem(ROSTER_KEY, newInput);

    // Build opponent rosters for opponent-aware suggestions
    const opponents = sleeperTeams
      .filter((_, oi) => oi !== i)
      .map((t) => ({ team_name: t.name, players: t.players || [] }));
    setLeagueRosters(opponents);
  }

  async function fetchSuggestions() {
    const roster = parseRoster();
    if (roster.length < 3) {
      setSuggestionsError("Enter at least 3 player names to get suggestions.");
      return;
    }
    setSuggestionsLoading(true);
    setSuggestionsError(null);
    setSuggestions(null);
    localStorage.setItem(ROSTER_KEY, rosterInput);
    try {
      const res = await fetch("/api/trade/suggestions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(leagueRosters ? { roster, league_rosters: leagueRosters } : { roster }),
      });
      const data = await res.json();
      if (!res.ok) {
        setSuggestionsError(data.error || `Server error (${res.status})`);
        return;
      }
      setSuggestions(data);
    } catch (err) {
      setSuggestionsError("Could not reach suggestion service.");
    } finally {
      setSuggestionsLoading(false);
    }
  }

  function applySuggestion(s) {
    const giveRows = s.give.map((p) => rowByName.get(p.name)).filter(Boolean);
    const recvRows = s.receive.map((p) => rowByName.get(p.name)).filter(Boolean);
    setSideA(giveRows);
    setSideB(recvRows);
  }

  // Count per category
  const suggestionCounts = useMemo(() => {
    if (!suggestions) return {};
    return Object.fromEntries(SUGG_TYPES.map((t) => [t.key, (suggestions[t.key] || []).length]));
  }, [suggestions]);

  return (
    <section className="card">
      <h1 style={{ marginTop: 0 }}>Trade Builder</h1>
      <p className="muted" style={{ marginTop: 4 }}>Persistent mobile workspace with live verdict and fast add/remove flow.</p>

      {loading && <p>Loading player pool...</p>}
      {!!error && <p style={{ color: "var(--red)" }}>{error}</p>}

      {!loading && !error && (
        <>
          <div className="row" style={{ marginBottom: 10 }}>
            <select className="select" value={valueMode} onChange={(e) => setValueMode(e.target.value)}>
              {VALUE_MODES.map((m) => (<option key={m.key} value={m.key}>{m.label}</option>))}
            </select>
            <button className="button" onClick={swapSides}>Swap Sides</button>
            <button className="button" onClick={clearTrade}>Clear Trade</button>
          </div>

          <div className="row mobile-stack" style={{ alignItems: "stretch", paddingBottom: 78 }}>
            {/* Side A */}
            <div className="card" style={{ flex: 1 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <h3 style={{ margin: 0 }}>Side A</h3>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div>
                    <div className="value">{Math.round(pwTotalA).toLocaleString()}</div>
                    <div className="muted" style={{ fontSize: "0.64rem" }}>Linear: {Math.round(linTotalA).toLocaleString()}</div>
                  </div>
                  <button className="button" onClick={() => openPickerFor("A")}>+ Add</button>
                </div>
              </div>
              <div className="list" style={{ marginTop: 10 }}>
                {sideA.map((r) => {
                  const edge = getPlayerEdge(r);
                  return (
                    <div className="asset-row" key={`A-${r.name}`}>
                      <div>
                        <div className="asset-name">
                          <span style={{ cursor: "pointer", textDecoration: "underline dotted" }} onClick={() => openPlayerPopup?.(r)}>{r.name}</span>
                          {edge.signal && (
                            <span className="badge" style={{ marginLeft: 6, fontSize: "0.6rem", padding: "1px 4px",
                              color: edge.signal === "BUY" ? "var(--green)" : "var(--red)",
                              borderColor: edge.signal === "BUY" ? "var(--green)" : "var(--red)" }}>
                              {edge.signal} {edge.edgePct}%
                            </span>
                          )}
                        </div>
                        <div className="asset-meta">{r.pos} · Consensus {r.blendedSourceRank != null ? r.blendedSourceRank.toFixed(1) : "—"} · {Math.round(effectiveValue(r, valueMode, settings)).toLocaleString()}</div>
                      </div>
                      <button className="button" onClick={() => removeFromSide(r.name, "A")}>Remove</button>
                    </div>
                  );
                })}
                {sideA.length === 0 && <div className="muted">No assets yet.</div>}
              </div>
              {/* Balancers for Side A (shown when B is ahead) */}
              {pwGap < -350 && balancers.length > 0 && (
                <div style={{ marginTop: 8, padding: "6px 8px", background: "rgba(86,214,255,0.06)", borderRadius: 6 }}>
                  <div className="label" style={{ fontSize: "0.68rem", marginBottom: 4 }}>To balance, consider adding:</div>
                  {balancers.map((b) => (
                    <button key={b.name} className="button-reset muted" style={{ display: "block", fontSize: "0.72rem", cursor: "pointer" }}
                      onClick={() => { const row = rowByName.get(b.name); if (row) addToSide(row, "A"); }}>
                      {b.name} ({b.pos}) · {b.value.toLocaleString()}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Side B */}
            <div className="card" style={{ flex: 1 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <h3 style={{ margin: 0 }}>Side B</h3>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div>
                    <div className="value">{Math.round(pwTotalB).toLocaleString()}</div>
                    <div className="muted" style={{ fontSize: "0.64rem" }}>Linear: {Math.round(linTotalB).toLocaleString()}</div>
                  </div>
                  <button className="button" onClick={() => openPickerFor("B")}>+ Add</button>
                </div>
              </div>
              <div className="list" style={{ marginTop: 10 }}>
                {sideB.map((r) => {
                  const edge = getPlayerEdge(r);
                  return (
                    <div className="asset-row" key={`B-${r.name}`}>
                      <div>
                        <div className="asset-name">
                          <span style={{ cursor: "pointer", textDecoration: "underline dotted" }} onClick={() => openPlayerPopup?.(r)}>{r.name}</span>
                          {edge.signal && (
                            <span className="badge" style={{ marginLeft: 6, fontSize: "0.6rem", padding: "1px 4px",
                              color: edge.signal === "BUY" ? "var(--green)" : "var(--red)",
                              borderColor: edge.signal === "BUY" ? "var(--green)" : "var(--red)" }}>
                              {edge.signal} {edge.edgePct}%
                            </span>
                          )}
                        </div>
                        <div className="asset-meta">{r.pos} · Consensus {r.blendedSourceRank != null ? r.blendedSourceRank.toFixed(1) : "—"} · {Math.round(effectiveValue(r, valueMode, settings)).toLocaleString()}</div>
                      </div>
                      <button className="button" onClick={() => removeFromSide(r.name, "B")}>Remove</button>
                    </div>
                  );
                })}
                {sideB.length === 0 && <div className="muted">No assets yet.</div>}
              </div>
              {/* Balancers for Side B (shown when A is ahead) */}
              {pwGap > 350 && balancers.length > 0 && (
                <div style={{ marginTop: 8, padding: "6px 8px", background: "rgba(86,214,255,0.06)", borderRadius: 6 }}>
                  <div className="label" style={{ fontSize: "0.68rem", marginBottom: 4 }}>To balance, consider adding:</div>
                  {balancers.map((b) => (
                    <button key={b.name} className="button-reset muted" style={{ display: "block", fontSize: "0.72rem", cursor: "pointer" }}
                      onClick={() => { const row = rowByName.get(b.name); if (row) addToSide(row, "B"); }}>
                      {b.name} ({b.pos}) · {b.value.toLocaleString()}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* ── Suggestions Panel ─────────────────────────────────── */}
          <div className="card" style={{ marginTop: 12 }}>
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Trade Suggestions</h2>
            <p className="muted" style={{ margin: "4px 0 10px", fontSize: "0.76rem" }}>
              {sleeperTeams
                ? "Select your team from the league, or enter a roster manually."
                : "Enter your roster to get roster-aware trade ideas."}
            </p>

            {/* Team selector from Sleeper league */}
            {sleeperTeams && (
              <div className="row" style={{ marginBottom: 8, alignItems: "center" }}>
                <select
                  className="select"
                  value={selectedTeamIdx}
                  onChange={(e) => selectTeam(e.target.value)}
                  style={{ flex: 1, maxWidth: 320 }}
                >
                  <option value={-1}>Select your team...</option>
                  {sleeperTeams.map((t, i) => (
                    <option key={i} value={i}>
                      {t.name} ({(t.players || []).length} players, {(t.picks || []).length} picks)
                    </option>
                  ))}
                </select>
                {selectedTeamIdx >= 0 && sleeperTeams[selectedTeamIdx] && (
                  <span className="muted" style={{ fontSize: "0.72rem" }}>
                    Loaded {(sleeperTeams[selectedTeamIdx].players || []).length} players + {(sleeperTeams[selectedTeamIdx].picks || []).length} picks
                    {leagueRosters ? ` · ${leagueRosters.length} opponents` : ""}
                  </span>
                )}
              </div>
            )}

            <textarea
              className="input"
              placeholder="Enter roster (comma or newline separated): Josh Allen, Bijan Robinson, Ja'Marr Chase, ..."
              value={rosterInput}
              onChange={(e) => { setRosterInput(e.target.value); setSelectedTeamIdx(-1); setLeagueRosters(null); }}
              rows={3}
              style={{ width: "100%", resize: "vertical", fontFamily: "inherit", fontSize: "0.82rem" }}
            />

            <div className="row" style={{ marginTop: 8, alignItems: "center" }}>
              <button
                className="button"
                onClick={fetchSuggestions}
                disabled={suggestionsLoading}
                style={{ fontWeight: 700, borderColor: "var(--cyan)", color: "var(--cyan)" }}
              >
                {suggestionsLoading ? "Analyzing..." : "Get Suggestions"}
              </button>
              {suggestions && (
                <span className="muted" style={{ fontSize: "0.76rem" }}>
                  {suggestions.totalSuggestions} suggestions · {suggestions.metadata?.rosterMatched || 0}/{parseRoster().length} matched
                  {(suggestions.metadata?.opponentRostersAnalyzed || 0) > 0
                    ? ` · ${suggestions.metadata.opponentRostersAnalyzed} opponents analyzed`
                    : ""}
                </span>
              )}
            </div>

            {suggestionsError && (
              <p style={{ color: "var(--red)", fontSize: "0.82rem", margin: "8px 0 0" }}>{suggestionsError}</p>
            )}

            {/* Roster analysis summary */}
            {suggestions?.rosterAnalysis && (
              <div style={{ marginTop: 10, display: "flex", gap: 16, flexWrap: "wrap", fontSize: "0.78rem" }}>
                {suggestions.rosterAnalysis.surplusPositions.length > 0 && (
                  <span>
                    <span className="label">Can trade from </span>
                    <span style={{ color: "var(--green)", fontWeight: 600 }}>
                      {suggestions.rosterAnalysis.surplusPositions.join(", ")}
                    </span>
                  </span>
                )}
                {suggestions.rosterAnalysis.needPositions.length > 0 && (
                  <span>
                    <span className="label">Should target </span>
                    <span style={{ color: "var(--red)", fontWeight: 600 }}>
                      {suggestions.rosterAnalysis.needPositions.join(", ")}
                    </span>
                  </span>
                )}
                {suggestions.rosterAnalysis.surplusPositions.length === 0 &&
                 suggestions.rosterAnalysis.needPositions.length === 0 && (
                  <span className="muted">Roster is balanced — no clear surplus or need detected.</span>
                )}
              </div>
            )}

            {/* Category tabs */}
            {suggestions && suggestions.totalSuggestions > 0 && (
              <>
                <div style={{ display: "flex", gap: 6, marginTop: 12, flexWrap: "wrap" }}>
                  {SUGG_TYPES.map((t) => {
                    const count = suggestionCounts[t.key] || 0;
                    const isActive = suggestionTab === t.key;
                    const isEmpty = count === 0;
                    return (
                      <button
                        key={t.key}
                        className="button"
                        onClick={() => setSuggestionTab(t.key)}
                        style={{
                          fontSize: "0.76rem",
                          padding: "5px 10px",
                          borderColor: isActive ? "var(--cyan)" : "var(--border)",
                          color: isActive ? "var(--cyan)" : isEmpty ? "var(--border)" : "var(--muted)",
                          background: isActive ? "rgba(86,214,255,0.08)" : undefined,
                          opacity: isEmpty && !isActive ? 0.5 : 1,
                        }}
                      >
                        {t.label}{count > 0 ? ` (${count})` : ""}
                      </button>
                    );
                  })}
                </div>

                {/* Suggestion cards */}
                <div className="list" style={{ marginTop: 10 }}>
                  {(suggestions[suggestionTab] || []).map((s, i) => {
                    const eb = edgeBadge(s.edge);
                    const cb = confidenceBadge(s.confidence);
                    const rs = s.rankScore;
                    const isTopPick = i === 0 && rs && rs.total >= 12;
                    return (
                      <div
                        key={`${suggestionTab}-${i}`}
                        className="card"
                        style={{
                          padding: 10,
                          borderColor: isTopPick ? "rgba(52,211,153,0.5)" : s.edge ? "rgba(86,214,255,0.3)" : undefined,
                          borderWidth: isTopPick ? 2 : undefined,
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                          <div style={{ flex: 1 }}>
                            {/* Rank + Give / Get */}
                            <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                              <span style={{
                                fontSize: "0.68rem", fontWeight: 700, color: i === 0 ? "var(--green)" : "var(--muted)",
                                minWidth: 18,
                              }}>#{i + 1}</span>
                              <div style={{ flex: 1 }}>
                                <div style={{ fontSize: "0.82rem" }}>
                                  <span style={{ color: "var(--red)", fontWeight: 600 }}>Give </span>
                                  {s.give.map((p, pi) => (
                                    <span key={pi}>
                                      {pi > 0 && <span className="muted"> + </span>}
                                      <span style={{ fontWeight: 600 }}>{p.name}</span>
                                      <span className="muted"> {p.position} {p.displayValue.toLocaleString()}</span>
                                    </span>
                                  ))}
                                </div>
                                <div style={{ fontSize: "0.82rem", marginTop: 3 }}>
                                  <span style={{ color: "var(--green)", fontWeight: 600 }}>Get </span>
                                  {s.receive.map((p, pi) => (
                                    <span key={pi}>
                                      {pi > 0 && <span className="muted"> + </span>}
                                      <span style={{ fontWeight: 600 }}>{p.name}</span>
                                      <span className="muted"> {p.position} {p.displayValue.toLocaleString()}</span>
                                    </span>
                                  ))}
                                </div>
                              </div>
                            </div>

                            {/* Badges row */}
                            <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap", marginLeft: 24 }}>
                              <span className="badge" style={{ color: fairnessColor(s.fairness), borderColor: fairnessColor(s.fairness) }}>
                                {fairnessLabel(s.fairness)}
                                {s.gap !== 0 && ` (${s.gap > 0 ? "+" : ""}${s.gap.toLocaleString()})`}
                              </span>
                              <span className="badge" style={{ color: cb.color, borderColor: cb.border, background: cb.bg }}>
                                {cb.label}
                              </span>
                              {s.strategy !== "neutral" && (
                                <span className="badge" style={{ textTransform: "capitalize" }}>
                                  {s.strategy === "contender" ? "Contender move" : "Rebuilder move"}
                                </span>
                              )}
                              {eb && (
                                <span className="badge" style={{ color: eb.color, background: eb.bg, borderColor: eb.color }}>
                                  {eb.text}
                                </span>
                              )}
                            </div>

                            {/* Rationale */}
                            <div style={{ marginLeft: 24 }}>
                              <div className="muted" style={{ fontSize: "0.74rem", marginTop: 5 }}>{s.rationale}</div>
                              {s.whyThisHelps && (
                                <div style={{ fontSize: "0.74rem", marginTop: 2, color: "var(--cyan)" }}>{s.whyThisHelps}</div>
                              )}
                              {s.edgeExplanation && (
                                <div style={{ fontSize: "0.72rem", marginTop: 2, fontStyle: "italic", color: "#fbbf24" }}>{s.edgeExplanation}</div>
                              )}

                              {/* Balancers */}
                              {s.suggestedBalancers?.length > 0 && (
                                <div className="muted" style={{ fontSize: "0.72rem", marginTop: 4 }}>
                                  To even it out, add: {s.suggestedBalancers.map((b) => `${b.name} (${b.displayValue.toLocaleString()})`).join(", ")}
                                </div>
                              )}

                              {/* Opponent fit */}
                              {s.opponentFit && (
                                <div style={{ fontSize: "0.72rem", marginTop: 3, color: "var(--cyan)" }}>
                                  {s.opponentFit}
                                </div>
                              )}

                              {/* Rank score transparency (collapsed by default) */}
                              {rs && (
                                <details style={{ marginTop: 4 }}>
                                  <summary className="muted" style={{ fontSize: "0.66rem", cursor: "pointer" }}>
                                    Why #{i + 1}? Score {rs.total}
                                  </summary>
                                  <div className="muted" style={{ fontSize: "0.66rem", marginTop: 2, lineHeight: 1.5 }}>
                                    Value {rs.base_value} + Fairness {rs.fairness} + Consensus {rs.confidence}
                                    {rs.need_severity > 0 && ` + Need ${rs.need_severity}`}
                                    {rs.edge > 0 && ` + Edge ${rs.edge}`}
                                    {rs.opponent_fit > 0 && ` + Partner ${rs.opponent_fit}`}
                                    {" "}= {rs.total}
                                  </div>
                                </details>
                              )}
                            </div>
                          </div>

                          {/* Apply button */}
                          <button
                            className="button"
                            style={{ fontSize: "0.72rem", padding: "4px 8px", whiteSpace: "nowrap" }}
                            onClick={() => applySuggestion(s)}
                          >
                            Load Trade
                          </button>
                        </div>
                      </div>
                    );
                  })}
                  {(suggestions[suggestionTab] || []).length === 0 && (
                    <div className="muted" style={{ fontSize: "0.82rem", padding: "8px 0" }}>
                      {suggestionTab === "sellHigh"
                        ? "No sell-high opportunities found. You may not have enough depth at any position to move a piece."
                        : suggestionTab === "buyLow"
                        ? "No buy-low targets found. Your surplus positions may not have tradeable pieces in the right value range."
                        : suggestionTab === "consolidation"
                        ? "No consolidation trades found. This requires 2+ depth pieces that combine into a single upgrade."
                        : "No positional upgrades found. Your starters may already be top-tier, or no upgrade targets match your depth value."}
                    </div>
                  )}
                </div>
              </>
            )}

            {suggestions && suggestions.totalSuggestions === 0 && (
              <div style={{ marginTop: 12, padding: "10px 12px", border: "1px solid var(--border)", borderRadius: 8, fontSize: "0.82rem" }}>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>No trade suggestions found</div>
                <div className="muted" style={{ fontSize: "0.76rem", lineHeight: 1.5 }}>
                  {suggestions.metadata?.rosterMatched < 5
                    ? `Only ${suggestions.metadata?.rosterMatched || 0} of ${parseRoster().length} players matched our database. Check spelling or try adding more players.`
                    : suggestions.rosterAnalysis?.surplusPositions?.length === 0
                    ? "Your roster has no clear positional surplus. The engine needs at least one position with depth beyond starters to suggest trades."
                    : "Your roster appears well-balanced. No actionable trades met our quality threshold."}
                </div>
              </div>
            )}
          </div>

          {/* Sticky verdict tray */}
          <div className="trade-sticky-tray">
            <div className="trade-tray-main">
              <div>
                <div className="label">Side A</div>
                <div className="value" style={{ fontSize: "1.0rem" }}>{Math.round(pwTotalA).toLocaleString()}</div>
              </div>
              <div style={{ flex: 1, maxWidth: 220 }}>
                {/* Verdict bar */}
                <div style={{ position: "relative", height: 10, background: "var(--border)", borderRadius: 5, overflow: "hidden", margin: "6px 0" }}>
                  <div style={{ position: "absolute", inset: 0, background: "linear-gradient(to right, var(--green), transparent 40%, transparent 60%, var(--red))", opacity: 0.3, borderRadius: 5 }} />
                  <div style={{
                    position: "absolute", top: -1, width: 12, height: 12, borderRadius: "50%",
                    background: colorFromGap(pwGap) === "green" ? "var(--green)" : colorFromGap(pwGap) === "red" ? "var(--red)" : "var(--cyan)",
                    border: "2px solid var(--bg)", left: `calc(${verdictBarPosition(pwGap)}% - 6px)`, transition: "left 0.3s",
                  }} />
                </div>
                <div className={`verdict ${colorFromGap(pwGap)}`} style={{ textAlign: "center", fontSize: "0.82rem" }}>
                  {verdictFromGap(pwGap)}{pctGap > 0 ? ` (${pctGap}%)` : ""}
                </div>
                <div className="muted" style={{ fontSize: "0.66rem", textAlign: "center" }}>
                  Gap {Math.round(pwGap).toLocaleString()}
                </div>
              </div>
              <div>
                <div className="label">Side B</div>
                <div className="value" style={{ fontSize: "1.0rem" }}>{Math.round(pwTotalB).toLocaleString()}</div>
              </div>
            </div>
          </div>

          {/* Picker overlay */}
          {pickerOpen && (
            <div className="picker-overlay" onClick={() => setPickerOpen(false)}>
              <div className="picker-sheet" onClick={(e) => e.stopPropagation()}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
                  <div>
                    <h3 style={{ margin: 0 }}>Add Asset to Side {activeSide}</h3>
                    <p className="muted" style={{ margin: "4px 0 0 0", fontSize: "0.76rem" }}>Tap a player/pick to add instantly.</p>
                  </div>
                  <button className="button" onClick={() => setPickerOpen(false)}>Close</button>
                </div>
                <div className="row" style={{ marginTop: 10 }}>
                  <input
                    ref={pickerInputRef}
                    className="input"
                    placeholder="Search player or pick"
                    value={pickerQuery}
                    onChange={(e) => setPickerQuery(e.target.value)}
                    style={{ flex: 1 }}
                  />
                  <select className="select" value={pickerFilter} onChange={(e) => setPickerFilter(e.target.value)}>
                    <option value="all">All</option>
                    <option value="offense">OFF</option>
                    <option value="idp">IDP</option>
                    <option value="pick">Picks</option>
                  </select>
                </div>
                {!pickerQuery && recentRows.length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    <div className="label" style={{ marginBottom: 6 }}>Recent</div>
                    <div className="list">
                      {recentRows.slice(0, 8).map((r) => (
                        <button key={`recent-${r.name}`} className="asset-row button-reset" onClick={() => addToActiveSide(r)}>
                          <div>
                            <div className="asset-name">{r.name}</div>
                            <div className="asset-meta">{r.pos} · Consensus {r.blendedSourceRank != null ? r.blendedSourceRank.toFixed(1) : "—"} · {Math.round(effectiveValue(r, valueMode, settings)).toLocaleString()}</div>
                          </div>
                          <span className="badge">Add</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                <div className="table-wrap" style={{ marginTop: 10, maxHeight: "52vh", overflow: "auto" }}>
                  <table style={{ width: "100%", fontSize: "0.78rem" }}>
                    <thead>
                      <tr>
                        {[
                          { col: "rank", label: "Our Rank", style: { width: 70, textAlign: "center" } },
                          { col: "name", label: "Player" },
                          { col: "pos", label: "Pos", style: { width: 50 } },
                          { col: "value", label: "Our Value", style: { width: 80, textAlign: "right" } },
                          // One sortable column per registered ranking source,
                          // enumerated from the shared RANKING_SOURCES registry
                          // so newly-added sources (DLF, etc.) surface here
                          // without touching this component.
                          ...RANKING_SOURCES.map((src) => ({
                            col: `src:${src.key}`,
                            label: src.columnLabel,
                            style: { width: 65, textAlign: "right" },
                          })),
                        ].map(({ col, label, style }) => (
                          <th key={col} style={{ cursor: "pointer", userSelect: "none", whiteSpace: "nowrap", ...style }}
                            onClick={() => {
                              if (pickerSortCol === col) setPickerSortAsc((p) => !p);
                              else { setPickerSortCol(col); setPickerSortAsc(["rank", "name", "pos"].includes(col)); }
                            }}>
                            {label}{pickerSortCol === col ? (pickerSortAsc ? " ▲" : " ▼") : ""}
                          </th>
                        ))}
                        <th style={{ width: 40 }}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {pickerRows.map((r) => (
                        <tr key={`pick-${r.name}`} style={{ cursor: "pointer" }} onClick={() => addToActiveSide(r)}>
                          <td style={{ textAlign: "center", fontFamily: "var(--mono, monospace)", fontWeight: 600, color: "var(--cyan)" }}>
                            {r.blendedSourceRank != null ? r.blendedSourceRank.toFixed(1) : "—"}
                          </td>
                          <td style={{ fontWeight: 600 }}>{r.name}</td>
                          <td><span className="badge">{r.pos}</span></td>
                          <td style={{ textAlign: "right", fontFamily: "var(--mono, monospace)", fontWeight: 600 }}>
                            {Math.round(r.rankDerivedValue || r.values?.full || 0).toLocaleString()}
                          </td>
                          {RANKING_SOURCES.map((src) => {
                            const raw = r.canonicalSites?.[src.key];
                            const hasVal = raw != null && Number.isFinite(Number(raw));
                            return (
                              <td key={src.key} style={{ textAlign: "right", fontFamily: "var(--mono, monospace)", fontSize: "0.74rem" }}>
                                {hasVal ? Math.round(Number(raw)).toLocaleString() : "—"}
                              </td>
                            );
                          })}
                          <td><span className="badge" style={{ fontSize: "0.6rem" }}>Add</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {pickerRows.length === 0 && <div className="muted" style={{ padding: 8 }}>No assets match.</div>}
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

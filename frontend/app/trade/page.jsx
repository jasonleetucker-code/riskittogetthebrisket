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
  adjustedSideTotals,
  tradeGapAdjusted,
  sideTotal,
  effectiveValue,
  getPlayerEdge,
  findBalancers,
  meterVerdict,
  percentageGap,
  multiTeamAnalysis,
  createSide,
  serializeWorkspaceMulti,
  deserializeWorkspaceMulti,
  SIDE_LABELS,
  MAX_SIDES,
  MIN_SIDES,
} from "@/lib/trade-logic";
import { useSettings } from "@/components/useSettings";
import TradeDeltaHistogram from "@/components/graphs/TradeDeltaHistogram";
import { useApp } from "@/components/AppShell";
import { posBadgeClass } from "@/lib/display-helpers";

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

/* ── Trade Meter Component ───────────────────────────────────────────── */

function TradeMeter({ sides, sideTotals, valueMode, settings }) {
  const sideCount = sides.length;

  if (sideCount === 2) {
    return <TradeMeterTwoTeam sides={sides} sideTotals={sideTotals} />;
  }
  return <TradeMeterMultiTeam sides={sides} sideTotals={sideTotals} />;
}

function TradeMeterTwoTeam({ sides, sideTotals }) {
  const pwA = sideTotals[0]?.adjusted || 0;
  const pwB = sideTotals[1]?.adjusted || 0;
  const gap = pwA - pwB;
  const absGap = Math.abs(gap);
  const pctGap = percentageGap(pwA, pwB);
  const verdict = meterVerdict(absGap);
  const maxVal = Math.max(pwA, pwB);
  const total = pwA + pwB;

  // Fill percentages for the bar
  const shareA = total > 0 ? (pwA / total) * 100 : 50;
  const shareB = total > 0 ? (pwB / total) * 100 : 50;

  // Winner label
  let winnerText = "Even";
  if (pctGap >= 3) {
    winnerText = gap > 0
      ? `Side A wins by ${pctGap}%`
      : `Side B wins by ${pctGap}%`;
  }

  return (
    <div className="trade-meter">
      {/* Value comparison */}
      <div className="trade-meter-values">
        <span className="trade-meter-side-val">{Math.round(pwA).toLocaleString()}</span>
        <span className="trade-meter-vs">vs</span>
        <span className="trade-meter-side-val">{Math.round(pwB).toLocaleString()}</span>
        <span className="trade-meter-gap">Gap: {Math.round(absGap).toLocaleString()}</span>
      </div>

      {/* Horizontal balance bar */}
      <div className="trade-meter-bar">
        <div
          className="trade-meter-fill trade-meter-fill-a"
          style={{ width: `${shareA}%` }}
        />
        <div
          className="trade-meter-fill trade-meter-fill-b"
          style={{ width: `${shareB}%` }}
        />
        <div className="trade-meter-center" />
      </div>
      <div className="trade-meter-bar-labels">
        <span className="muted" style={{ fontSize: "0.66rem" }}>Side A</span>
        <span className="muted" style={{ fontSize: "0.66rem" }}>Side B</span>
      </div>

      {/* Verdict badge + percentage */}
      <div className="trade-meter-bottom">
        <span className={`trade-meter-verdict trade-meter-verdict-${verdict.level}`}>
          {verdict.label}
        </span>
        <span className="trade-meter-pct">{winnerText}</span>
      </div>
    </div>
  );
}

function TradeMeterMultiTeam({ sides, sideTotals }) {
  const totals = sideTotals.map((t) => t.adjusted);
  const analysis = multiTeamAnalysis(totals);
  const grandTotal = totals.reduce((a, b) => a + b, 0);

  // Color cycle for multi-team segments
  const segColors = [
    "var(--green)", "var(--cyan)", "var(--amber)", "var(--red)", "#a78bfa",
  ];

  return (
    <div className="trade-meter">
      {/* Value comparison row */}
      <div className="trade-meter-multi-values">
        {sides.map((s, i) => (
          <div key={s.id} className="trade-meter-multi-val">
            <span className="label">Side {s.label}</span>
            <span className="trade-meter-side-val">{Math.round(totals[i]).toLocaleString()}</span>
            <span className="muted" style={{ fontSize: "0.64rem" }}>
              {analysis.shares[i]}% - {analysis.perTeam[i]}
            </span>
          </div>
        ))}
      </div>

      {/* Segmented bar */}
      <div className="trade-meter-bar">
        {sides.map((s, i) => {
          const pct = grandTotal > 0 ? (totals[i] / grandTotal) * 100 : 100 / sides.length;
          return (
            <div
              key={s.id}
              className="trade-meter-fill"
              style={{
                width: `${pct}%`,
                background: segColors[i % segColors.length],
                opacity: 0.7,
              }}
              title={`Side ${s.label}: ${analysis.shares[i]}%`}
            />
          );
        })}
        {/* Equal-share markers */}
        {sides.length > 2 && sides.slice(1).map((_, i) => (
          <div
            key={`marker-${i}`}
            className="trade-meter-equal-marker"
            style={{ left: `${((i + 1) / sides.length) * 100}%` }}
          />
        ))}
      </div>
      <div className="trade-meter-bar-labels">
        {sides.map((s, i) => (
          <span key={s.id} className="muted" style={{ fontSize: "0.62rem", flex: 1, textAlign: "center" }}>
            {s.label}: {analysis.shares[i]}%
          </span>
        ))}
      </div>

      {/* Overall verdict */}
      <div className="trade-meter-bottom">
        <span className={`trade-meter-verdict ${analysis.overall === "Balanced" ? "trade-meter-verdict-fair" : "trade-meter-verdict-unfair"}`}>
          {analysis.overall}
        </span>
      </div>
    </div>
  );
}

/* ── Main Trade Page ─────────────────────────────────────────────────── */

export default function TradePage() {
  const { loading, error, rows, rawData } = useDynastyData();
  const { settings } = useSettings();
  const { openPlayerPopup, registerAddToTrade } = useApp();
  const [valueMode, setValueMode] = useState("full");
  const [pickerSortCol, setPickerSortCol] = useState("rank");
  const [pickerSortAsc, setPickerSortAsc] = useState(true);

  // Multi-team state: array of { id, label, assets }
  const [sides, setSides] = useState([
    createSide(0),
    createSide(1),
  ]);
  const [activeSide, setActiveSide] = useState(0); // index into sides
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

  // Hydrate trade workspace from localStorage (with migration)
  useEffect(() => {
    if (!rows.length || hydrated) return;
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        const restored = deserializeWorkspaceMulti(parsed, rowByName);
        if (restored) {
          const nextMode = String(restored.valueMode || "full");
          if (VALUE_MODES.some((m) => m.key === nextMode)) setValueMode(nextMode);
          setActiveSide(restored.activeSide);
          setSides(restored.sides);
        }
      }
    } catch { /* ignore */ } finally { setHydrated(true); }
  }, [rows, hydrated, rowByName]);

  // Persist trade workspace to localStorage
  useEffect(() => {
    if (!hydrated) return;
    const payload = serializeWorkspaceMulti(sides, valueMode, activeSide);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  }, [hydrated, valueMode, activeSide, sides]);

  useEffect(() => {
    if (pickerOpen && pickerInputRef.current) pickerInputRef.current.focus();
  }, [pickerOpen]);

  // ── Computed totals for all sides ────────────────────────────────────
  // Both 2-team and N-team trades use the KTC-style Value Adjustment.
  // For N ≥ 3, each side's VA is computed against the merged opposition
  // (every other side's assets flattened) — see
  // ``computeMultiSideAdjustments`` in trade-logic.js.
  const sideTotals = useMemo(() => {
    if (sides.length === 2) {
      const [a, b] = adjustedSideTotals(sides[0].assets, sides[1].assets, valueMode, settings);
      return [a, b];
    }
    if (sides.length > 2) {
      return multiAdjustedSideTotals(sides.map((s) => s.assets), valueMode, settings);
    }
    return sides.map((s) => {
      const raw = sideTotal(s.assets, valueMode, settings);
      return { raw, adjustment: 0, adjusted: raw };
    });
  }, [sides, valueMode, settings]);

  // Legacy 2-team gap computations (for sticky tray + 2-team balancers)
  const pwTotalA = sideTotals[0]?.adjusted || 0;
  const pwTotalB = sideTotals[1]?.adjusted || 0;
  const linTotalA = sideTotals[0]?.raw || 0;
  const linTotalB = sideTotals[1]?.raw || 0;
  const pwGap = pwTotalA - pwTotalB;
  const pctGap = Math.max(pwTotalA, pwTotalB) > 0 ? Math.round(Math.abs(pwGap) / Math.max(pwTotalA, pwTotalB) * 100) : 0;

  // Balancing suggestions (2-team mode only)
  const balancers = useMemo(() => {
    if (sides.length !== 2) return [];
    if (Math.abs(pwGap) < 350) return [];
    const allInTrade = new Set(sides.flatMap((s) => s.assets.map((a) => a.name)));
    const available = rows.filter((r) => !allInTrade.has(r.name));
    return findBalancers(pwGap, available, valueMode);
  }, [pwGap, rows, sides, valueMode]);

  // For 3+ teams, find balancers for the team overpaying
  const multiBalancers = useMemo(() => {
    if (sides.length <= 2) return null;
    const totals = sideTotals.map((t) => t.adjusted);
    const maxIdx = totals.indexOf(Math.max(...totals));
    const minIdx = totals.indexOf(Math.min(...totals));
    const gap = totals[maxIdx] - totals[minIdx];
    if (gap < 350) return null;
    const allInTrade = new Set(sides.flatMap((s) => s.assets.map((a) => a.name)));
    const available = rows.filter((r) => !allInTrade.has(r.name));
    const suggestions = findBalancers(gap, available, valueMode);
    return { overpayingIdx: maxIdx, underpayingIdx: minIdx, gap, suggestions };
  }, [sides, sideTotals, rows, valueMode]);

  // All assets currently in any side (for picker exclusion)
  const allTradeNames = useMemo(() => {
    return new Set(sides.flatMap((s) => s.assets.map((r) => r.name)));
  }, [sides]);

  const pickerRows = useMemo(() => {
    const q = pickerQuery.trim().toLowerCase();
    let list = rows.filter((r) => !allTradeNames.has(r.name));
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
  }, [rows, allTradeNames, pickerQuery, pickerFilter, pickerSortCol, pickerSortAsc]);

  const recentRows = useMemo(() => recentNames.map((n) => rowByName.get(n)).filter(Boolean), [recentNames, rowByName]);

  function addRecent(name) {
    setRecentNames((prev) => {
      const next = [name, ...prev.filter((x) => x !== name)].slice(0, 20);
      localStorage.setItem(RECENT_KEY, JSON.stringify(next));
      return next;
    });
  }

  // ── Side management ─────────────────────────────────────────────────
  function addToSide(row, sideIdx) {
    if (!row) return;
    // Check all sides for duplicates
    if (allTradeNames.has(row.name)) return;
    setSides((prev) => prev.map((s, i) => {
      if (i !== sideIdx) return s;
      if (s.assets.some((r) => r.name === row.name)) return s;
      return { ...s, assets: [...s.assets, row] };
    }));
    addRecent(row.name);
  }

  function addToActiveSide(row) { addToSide(row, activeSide); }

  // Register add-to-trade callback so popup/search can add players
  useEffect(() => {
    registerAddToTrade?.(addToActiveSide);
    return () => registerAddToTrade?.(null);
  }, [registerAddToTrade, activeSide]); // eslint-disable-line react-hooks/exhaustive-deps

  function removeFromSide(name, sideIdx) {
    setSides((prev) => prev.map((s, i) => {
      if (i !== sideIdx) return s;
      return { ...s, assets: s.assets.filter((r) => r.name !== name) };
    }));
  }

  function clearTrade() {
    setSides((prev) => prev.map((s) => ({ ...s, assets: [] })));
  }

  function swapSides() {
    if (sides.length === 2) {
      setSides((prev) => [
        { ...prev[1], id: 0, label: "A" },
        { ...prev[0], id: 1, label: "B" },
      ]);
      setActiveSide((s) => s === 0 ? 1 : 0);
    } else {
      // Rotate: A->B, B->C, ..., last->A
      setSides((prev) => {
        const rotated = prev.map((s, i) => {
          const newIdx = i === 0 ? prev.length - 1 : i - 1;
          return { ...prev[newIdx === prev.length ? 0 : (newIdx + 1) % prev.length], id: i, label: SIDE_LABELS[i] };
        });
        // Actually rotate assets: each side gets the previous side's assets
        return prev.map((s, i) => ({
          id: i,
          label: SIDE_LABELS[i],
          assets: prev[(i + prev.length - 1) % prev.length].assets,
        }));
      });
    }
  }

  function addTeam() {
    if (sides.length >= MAX_SIDES) return;
    setSides((prev) => [...prev, createSide(prev.length)]);
  }

  function removeTeam(idx) {
    if (sides.length <= MIN_SIDES) return;
    setSides((prev) => {
      const next = prev.filter((_, i) => i !== idx);
      // Reletter remaining sides
      return next.map((s, i) => ({ ...s, id: i, label: SIDE_LABELS[i] }));
    });
    // Fix activeSide if it's out of bounds
    setActiveSide((prev) => Math.min(prev, sides.length - 2));
  }

  function openPickerFor(sideIdx) { setActiveSide(sideIdx); setPickerOpen(true); }

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
    const picks = (team.picks || []).map((p) => {
      const m = p.match(/^(\d{4})\s+(\d)\./);
      if (m) {
        const round = { "1": "1st", "2": "2nd", "3": "3rd", "4": "4th" }[m[2]] || `${m[2]}th`;
        return `${m[1]} ${round}`;
      }
      return p.replace(/\s*\(.*\)/, "").trim();
    });
    const rosterNames = [...(team.players || []), ...picks];
    const newInput = rosterNames.join("\n");
    setRosterInput(newInput);
    localStorage.setItem(ROSTER_KEY, newInput);

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
    // Apply to first two sides, reset others
    setSides((prev) => {
      const next = prev.map((side, i) => {
        if (i === 0) return { ...side, assets: giveRows };
        if (i === 1) return { ...side, assets: recvRows };
        return { ...side, assets: [] };
      });
      return next;
    });
  }

  // Count per category
  const suggestionCounts = useMemo(() => {
    if (!suggestions) return {};
    return Object.fromEntries(SUGG_TYPES.map((t) => [t.key, (suggestions[t.key] || []).length]));
  }, [suggestions]);

  // Determine grid columns class for the sides container
  const sidesGridClass = sides.length === 2
    ? "trade-sides-grid trade-sides-2"
    : sides.length === 3
      ? "trade-sides-grid trade-sides-3"
      : "trade-sides-grid trade-sides-multi";

  return (
    <section className="card">
      <h1 style={{ marginTop: 0 }}>Trade Builder</h1>
      <p className="muted" style={{ marginTop: 4 }}>Multi-team trade calculator with live fairness visualization.</p>

      {loading && <p>Loading player pool...</p>}
      {!!error && <p style={{ color: "var(--red)" }}>{error}</p>}

      {!loading && !error && (
        <>
          <div className="row trade-controls" style={{ marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
            <select className="select" value={valueMode} onChange={(e) => setValueMode(e.target.value)}>
              {VALUE_MODES.map((m) => (<option key={m.key} value={m.key}>{m.label}</option>))}
            </select>
            <button className="button" onClick={swapSides}>
              {sides.length === 2 ? "Swap Sides" : "Rotate Sides"}
            </button>
            <button className="button" onClick={clearTrade}>Clear Trade</button>
            {sides.length < MAX_SIDES && (
              <button className="button" onClick={addTeam} style={{ borderColor: "var(--green)", color: "var(--green)" }}>
                + Add Team
              </button>
            )}
          </div>

          {/* ── Trade Meter (inline fairness visualization) ──────── */}
          <TradeMeter sides={sides} sideTotals={sideTotals} valueMode={valueMode} settings={settings} />

          {/* ── Value delta histogram (graphical complement to meter) ──── */}
          {sides.length === 2 ? (
            <div className="card" style={{ padding: "var(--space-sm) var(--space-md)" }}>
              <TradeDeltaHistogram
                sides={[
                  {
                    label: `Side ${sides[0]?.label || "A"}`,
                    total: sideTotals[0]?.adjusted || 0,
                  },
                  {
                    label: `Side ${sides[1]?.label || "B"}`,
                    total: sideTotals[1]?.adjusted || 0,
                  },
                ]}
              />
            </div>
          ) : null}

          {/* ── Side Cards ──────────────────────────────────────── */}
          <div className={sidesGridClass} style={{ paddingBottom: 78 }}>
            {sides.map((side, sideIdx) => {
              const total = sideTotals[sideIdx] || { raw: 0, adjustment: 0, adjusted: 0 };
              const isOverpaying = sides.length === 2
                ? (sideIdx === 0 ? pwGap > 350 : pwGap < -350)
                : false;
              const isUnderpaying = sides.length === 2
                ? (sideIdx === 0 ? pwGap < -350 : pwGap > 350)
                : false;

              return (
                <div className="card" key={side.id} style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <h3 style={{ margin: 0 }}>Side {side.label}</h3>
                      {sides.length > MIN_SIDES && (
                        <button
                          className="button button-danger"
                          style={{ fontSize: "0.66rem", padding: "2px 6px", minHeight: "unset" }}
                          onClick={() => removeTeam(sideIdx)}
                          title={`Remove Side ${side.label}`}
                        >
                          X
                        </button>
                      )}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <div style={{ textAlign: "right" }}>
                        <div className="value">{Math.round(total.adjusted).toLocaleString()}</div>
                        {total.adjustment > 0 ? (
                          <div
                            className="muted"
                            style={{ fontSize: "0.64rem", color: "var(--cyan)" }}
                            title="Consolidation / roster-spot premium: the side with fewer pieces frees up a roster spot, so KTC-style math adds this bonus on top of the raw total."
                          >
                            Raw {Math.round(total.raw).toLocaleString()} + VA {Math.round(total.adjustment).toLocaleString()}
                          </div>
                        ) : (
                          <div className="muted" style={{ fontSize: "0.64rem" }}>Raw: {Math.round(total.raw).toLocaleString()}</div>
                        )}
                      </div>
                      <button className="button trade-add-btn" onClick={() => openPickerFor(sideIdx)}>+ Add</button>
                    </div>
                  </div>
                  <div className="list" style={{ marginTop: 10 }}>
                    {side.assets.map((r) => {
                      const edge = getPlayerEdge(r);
                      return (
                        <div className="asset-row" key={`${side.label}-${r.name}`}>
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
                          <button className="button trade-remove-btn" onClick={() => removeFromSide(r.name, sideIdx)}>Remove</button>
                        </div>
                      );
                    })}
                    {side.assets.length === 0 && <div className="muted">No assets yet.</div>}
                  </div>
                  {/* Balancers (2-team mode only) */}
                  {sides.length === 2 && isUnderpaying && balancers.length > 0 && (
                    <div style={{ marginTop: 8, padding: "6px 8px", background: "rgba(86,214,255,0.06)", borderRadius: 6 }}>
                      <div className="label" style={{ fontSize: "0.68rem", marginBottom: 4 }}>To balance, consider adding:</div>
                      {balancers.map((b) => (
                        <button key={b.name} className="button-reset muted" style={{ display: "block", fontSize: "0.72rem", cursor: "pointer" }}
                          onClick={() => { const row = rowByName.get(b.name); if (row) addToSide(row, sideIdx); }}>
                          {b.name} ({b.pos}) · {b.value.toLocaleString()}
                        </button>
                      ))}
                    </div>
                  )}
                  {/* Balancers (3+ team mode) - show on the underpaying team */}
                  {multiBalancers && sideIdx === multiBalancers.underpayingIdx && multiBalancers.suggestions.length > 0 && (
                    <div style={{ marginTop: 8, padding: "6px 8px", background: "rgba(86,214,255,0.06)", borderRadius: 6 }}>
                      <div className="label" style={{ fontSize: "0.68rem", marginBottom: 4 }}>
                        To balance (Side {sides[multiBalancers.overpayingIdx]?.label} overpays by {Math.round(multiBalancers.gap).toLocaleString()}):
                      </div>
                      {multiBalancers.suggestions.map((b) => (
                        <button key={b.name} className="button-reset muted" style={{ display: "block", fontSize: "0.72rem", cursor: "pointer" }}
                          onClick={() => { const row = rowByName.get(b.name); if (row) addToSide(row, sideIdx); }}>
                          {b.name} ({b.pos}) · {b.value.toLocaleString()}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
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

          {/* Sticky verdict tray (kept for scroll context, 2-team only) */}
          {sides.length === 2 && (
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
          )}

          {/* Picker overlay */}
          {pickerOpen && (
            <div className="picker-overlay" onClick={() => setPickerOpen(false)}>
              <div className="picker-sheet" onClick={(e) => e.stopPropagation()}>
                <div className="picker-header">
                  <div style={{ minWidth: 0 }}>
                    <h3 style={{ margin: 0 }}>Add to Side {sides[activeSide]?.label || "?"}</h3>
                    <p className="muted picker-subtitle">Tap a player/pick to add instantly.</p>
                  </div>
                  <button className="picker-close" onClick={() => setPickerOpen(false)} aria-label="Close picker">&times;</button>
                </div>
                <div className="picker-search-row">
                  <input
                    ref={pickerInputRef}
                    className="input"
                    placeholder="Search player or pick..."
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
                  <div className="picker-recent">
                    <div className="label" style={{ marginBottom: 6 }}>Recent</div>
                    <div className="list">
                      {recentRows.slice(0, 8).map((r) => (
                        <button key={`recent-${r.name}`} className="asset-row button-reset" onClick={() => addToActiveSide(r)}>
                          <div>
                            <div className="asset-name">{r.name}</div>
                            <div className="asset-meta">{r.pos} · {Math.round(effectiveValue(r, valueMode, settings)).toLocaleString()}</div>
                          </div>
                          <span className="badge">Add</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                <div className="picker-table-wrap">
                  <table style={{ width: "100%", fontSize: "0.78rem" }}>
                    <thead>
                      <tr>
                        {[
                          { col: "rank", label: "Rank", className: "picker-rank-col", style: { width: 55, textAlign: "center" } },
                          { col: "name", label: "Player" },
                          { col: "pos", label: "Pos", style: { width: 46 } },
                          { col: "value", label: "Value", style: { width: 70, textAlign: "right" } },
                          ...RANKING_SOURCES.map((src) => ({
                            col: `src:${src.key}`,
                            label: src.columnLabel,
                            className: "picker-source-col",
                            style: { width: 65, textAlign: "right" },
                          })),
                        ].map(({ col, label, style, className }) => (
                          <th key={col} className={className || undefined} style={{ cursor: "pointer", userSelect: "none", whiteSpace: "nowrap", ...style }}
                            onClick={() => {
                              if (pickerSortCol === col) setPickerSortAsc((p) => !p);
                              else { setPickerSortCol(col); setPickerSortAsc(["rank", "name", "pos"].includes(col)); }
                            }}>
                            {label}{pickerSortCol === col ? (pickerSortAsc ? " \u25B2" : " \u25BC") : ""}
                          </th>
                        ))}
                        <th className="picker-add-col" style={{ width: 40 }}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {pickerRows.map((r) => (
                        <tr key={`pick-${r.name}`} className="picker-row" onClick={() => addToActiveSide(r)}>
                          <td className="picker-rank-col" style={{ textAlign: "center", fontFamily: "var(--mono, monospace)", fontWeight: 600, color: "var(--cyan)" }}>
                            {r.blendedSourceRank != null ? r.blendedSourceRank.toFixed(1) : "\u2014"}
                          </td>
                          <td style={{ fontWeight: 600 }}>{r.name}</td>
                          <td><span className={posBadgeClass(r)}>{r.pos}</span></td>
                          <td style={{ textAlign: "right", fontFamily: "var(--mono, monospace)", fontWeight: 600 }}>
                            {Math.round(r.rankDerivedValue || r.values?.full || 0).toLocaleString()}
                          </td>
                          {RANKING_SOURCES.map((src) => {
                            const raw = r.canonicalSites?.[src.key];
                            const hasVal = raw != null && Number.isFinite(Number(raw));
                            return (
                              <td key={src.key} className="picker-source-col" style={{ textAlign: "right", fontFamily: "var(--mono, monospace)", fontSize: "0.74rem" }}>
                                {hasVal ? Math.round(Number(raw)).toLocaleString() : "\u2014"}
                              </td>
                            );
                          })}
                          <td className="picker-add-col"><span className="badge" style={{ fontSize: "0.6rem" }}>Add</span></td>
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

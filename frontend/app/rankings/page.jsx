"use client";

import { Fragment, useMemo, useState, useCallback } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { resolvedRank } from "@/lib/dynasty-data";
import { useSettings } from "@/components/useSettings";
import { useApp } from "@/components/AppShell";
import {
  tierLabel,
  effectiveTierId,
  valueBand,
  rowChips,
  DEFAULT_ROW_LIMIT,
} from "@/lib/rankings-helpers";

// ── UNIFIED RANKINGS PAGE ────────────────────────────────────────────
// Trust-forward blended board: offense + IDP sorted by unified rank.
// Shows tiers, player context, confidence, value bands, and fast-scan chips.
//
// Default experience decisions (see item 5 in spec):
//   • Sort: by rank ascending (the most intentional view)
//   • Rows shown: 200 initially (covers starters + depth in 12-team)
//   • Tier grouping: ON by default (visual hierarchy is the point)
//   • Flagged rows: shown inline (not hidden) — flags make them visible
//   • Quarantined rows: shown but dimmed — transparency over hiding

const POS_FILTERS = [
  { key: "all", label: "All" },
  { key: "offense", label: "OFF" },
  { key: "idp", label: "IDP" },
  { key: "QB", label: "QB" },
  { key: "RB", label: "RB" },
  { key: "WR", label: "WR" },
  { key: "TE", label: "TE" },
  { key: "DL", label: "DL" },
  { key: "LB", label: "LB" },
  { key: "DB", label: "DB" },
];

const CONFIDENCE_FILTERS = [
  { key: "all", label: "Any confidence" },
  { key: "high", label: "High" },
  { key: "medium", label: "Medium" },
  { key: "low", label: "Low" },
];

const SOURCE_FILTERS = [
  { key: "all", label: "Any sources" },
  { key: "multi", label: "2+ sources" },
  { key: "single", label: "Single source" },
];

function posMatchesFilter(pos, assetClass, filter) {
  if (filter === "all") return true;
  if (filter === "offense") return assetClass === "offense";
  if (filter === "idp") return assetClass === "idp";
  return pos === filter;
}

// ── Inline badge helpers ─────────────────────────────────────────────

function confidenceBadgeClass(bucket) {
  switch (bucket) {
    case "high": return "badge badge-green";
    case "medium": return "badge badge-amber";
    case "low": return "badge badge-red";
    default: return "badge";
  }
}

function confidenceBadgeLabel(bucket) {
  switch (bucket) {
    case "high": return "High";
    case "medium": return "Med";
    case "low": return "Low";
    default: return "\u2014";
  }
}

function marketGapLabel(row) {
  if (!row.sourceRanks) return null;
  const ktcRank = row.sourceRanks.ktc;
  const idpRank = row.sourceRanks.idpTradeCalc;
  if (ktcRank && idpRank) {
    const diff = Math.abs(ktcRank - idpRank);
    if (diff < 10) return null;
    const higher = ktcRank < idpRank ? "KTC" : "IDPTC";
    return `${higher} +${diff}`;
  }
  return null;
}

// ── Methodology content ──────────────────────────────────────────────

function MethodologySection() {
  return (
    <div className="rankings-methodology-body">
      <h3 style={{ margin: "0 0 8px", fontSize: "0.88rem" }}>How rankings work</h3>
      <ol style={{ margin: 0, paddingLeft: 18, fontSize: "0.78rem", lineHeight: 1.7, color: "var(--subtext)" }}>
        <li><strong>Source ingestion</strong> — Raw values from Keep Trade Cut (offense) and IDP Trade Calculator (IDP).</li>
        <li><strong>Per-source ranking</strong> — Each player ranked within each source by raw value (highest = rank 1).</li>
        <li><strong>Rank normalization</strong> — Per-source ranks converted to 1–9,999 values via Hill-curve formula so sources are comparable.</li>
        <li><strong>Blended ranking</strong> — Multi-source players get averaged normalized values. Single-source players keep their one value.</li>
        <li><strong>Unified sort</strong> — All players sorted by blended value into one board. Top 800 get a consensus rank.</li>
        <li><strong>Tier detection</strong> — Natural value clusters are detected via gap analysis. Tier breaks appear where adjacent players have unusually large value gaps.</li>
        <li><strong>Confidence scoring</strong> — High = 2+ sources, spread {"<"} 30. Medium = 2+ sources, spread {"<"} 80. Low = single source or wide disagreement.</li>
        <li><strong>Identity validation</strong> — Post-ranking pass checks for entity resolution problems. Flagged rows are quarantined (confidence degraded, not removed).</li>
      </ol>
      <p style={{ margin: "8px 0 0", fontSize: "0.72rem", color: "var(--muted)", fontFamily: "var(--mono)" }}>
        value = max(1, min(9999, round(1 + 9998 / (1 + ((rank-1)/45)^1.10))))
      </p>
    </div>
  );
}

export default function RankingsPage() {
  const { loading, error, source, rows, rawData } = useDynastyData();
  const { settings } = useSettings();
  const { openPlayerPopup } = useApp();
  const [query, setQuery] = useState("");
  const [posFilter, setPosFilter] = useState("all");
  const [confFilter, setConfFilter] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [showAnomalies, setShowAnomalies] = useState(false);
  const [showTiers, setShowTiers] = useState(true);
  const [rowLimit, setRowLimit] = useState(DEFAULT_ROW_LIMIT);
  const [sortCol, setSortCol] = useState("rank");
  const [sortAsc, setSortAsc] = useState(true);
  const [copyStatus, setCopyStatus] = useState("");
  const [showMethodology, setShowMethodology] = useState(false);

  const handleSort = useCallback((col) => {
    if (sortCol === col) {
      setSortAsc((prev) => !prev);
    } else {
      setSortCol(col);
      setSortAsc(["rank", "name", "pos"].includes(col));
    }
  }, [sortCol]);

  // ── Trust summary stats ──────────────────────────────────────────
  const trustStats = useMemo(() => {
    const eligible = rows.filter((r) => r.pos && r.pos !== "?" && r.pos !== "PICK");
    const high = eligible.filter((r) => r.confidenceBucket === "high").length;
    const medium = eligible.filter((r) => r.confidenceBucket === "medium").length;
    const low = eligible.filter((r) => r.confidenceBucket === "low" || r.confidenceBucket === "none").length;
    const quarantined = eligible.filter((r) => r.quarantined).length;
    const multiSource = eligible.filter((r) => (r.sourceCount || 0) >= 2).length;
    const withAnomalies = eligible.filter((r) => (r.anomalyFlags || []).length > 0).length;
    return { total: eligible.length, high, medium, low, quarantined, multiSource, withAnomalies };
  }, [rows]);

  // ── Filtered + sorted list ──────────────────────────────────────
  const ranked = useMemo(() => {
    const q = query.trim().toLowerCase();
    let list = rows.filter((r) => r.pos && r.pos !== "?" && r.pos !== "PICK");

    if (posFilter !== "all") {
      list = list.filter((r) => posMatchesFilter(r.pos, r.assetClass, posFilter));
    }
    if (confFilter !== "all") {
      list = list.filter((r) => {
        if (confFilter === "low") return r.confidenceBucket === "low" || r.confidenceBucket === "none";
        return r.confidenceBucket === confFilter;
      });
    }
    if (sourceFilter === "multi") {
      list = list.filter((r) => (r.sourceCount || 0) >= 2);
    } else if (sourceFilter === "single") {
      list = list.filter((r) => (r.sourceCount || 0) <= 1);
    }
    if (showAnomalies) {
      list = list.filter((r) => (r.anomalyFlags || []).length > 0);
    }
    if (q) {
      list = list.filter((r) => r.name.toLowerCase().includes(q));
    }

    const sorted = [...list];
    const dir = sortAsc ? 1 : -1;
    sorted.sort((a, b) => {
      let va, vb;
      switch (sortCol) {
        case "rank":
          va = resolvedRank(a);
          vb = resolvedRank(b);
          return (va - vb) * dir;
        case "name":
          return a.name.localeCompare(b.name) * dir;
        case "pos":
          return a.pos.localeCompare(b.pos) * dir || resolvedRank(a) - resolvedRank(b);
        case "value":
          va = a.rankDerivedValue || a.values?.full || 0;
          vb = b.rankDerivedValue || b.values?.full || 0;
          return (va - vb) * dir;
        case "confidence": {
          const order = { high: 0, medium: 1, low: 2, none: 3 };
          va = order[a.confidenceBucket] ?? 3;
          vb = order[b.confidenceBucket] ?? 3;
          return (va - vb) * dir;
        }
        default:
          return resolvedRank(a) - resolvedRank(b);
      }
    });
    return sorted;
  }, [rows, posFilter, confFilter, sourceFilter, showAnomalies, query, sortCol, sortAsc]);

  // Apply row limit — search/filter bypasses the limit so results aren't hidden
  const hasActiveFilter = query || posFilter !== "all" || confFilter !== "all" || sourceFilter !== "all" || showAnomalies;
  const displayRows = hasActiveFilter ? ranked : ranked.slice(0, rowLimit);
  const hasMore = !hasActiveFilter && ranked.length > rowLimit;

  function SortHeader({ col, children, style, className }) {
    const active = sortCol === col;
    const arrow = active ? (sortAsc ? " \u25B2" : " \u25BC") : "";
    return (
      <th
        className={className}
        style={{ cursor: "pointer", userSelect: "none", whiteSpace: "nowrap", ...style }}
        onClick={() => handleSort(col)}
        title={`Sort by ${children}${active ? (sortAsc ? " (ascending)" : " (descending)") : ""}`}
      >
        {children}{arrow}
      </th>
    );
  }

  // ── Copy/Export (includes tier, team, value band, confidence) ───
  async function copyValues() {
    const lines = ["Rank\tPlayer\tPos\tTeam\tTier\tValue\tValue Band\tConfidence\tSources\tKTC\tKTC Rank\tIDPTC\tIDPTC Rank"];
    displayRows.forEach((row) => {
      const ktcVal = row.canonicalSites?.ktc != null ? Math.round(Number(row.canonicalSites.ktc)) : "";
      const idpVal = row.canonicalSites?.idpTradeCalc != null ? Math.round(Number(row.canonicalSites.idpTradeCalc)) : "";
      const val = Math.round(row.rankDerivedValue || row.values.full);
      const band = valueBand(val);
      lines.push(
        `${row.rank}\t${row.name}\t${row.pos}\t${row.team || ""}\t` +
        `${tierLabel(row)}\t${val}\t${band.label}\t` +
        `${row.confidenceBucket || ""}\t${row.sourceCount || 0}\t` +
        `${ktcVal}\t${row.ktcRank || ""}\t${idpVal}\t${row.idpRank || ""}`
      );
    });
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopyStatus(`Copied ${displayRows.length.toLocaleString()} rows`);
      setTimeout(() => setCopyStatus(""), 1800);
    } catch {
      setCopyStatus("Copy failed");
      setTimeout(() => setCopyStatus(""), 1800);
    }
  }

  // ── Freshness timestamp ────────────────────────────────────────────
  const freshness = rawData?.dataFreshness;
  const timestamp = freshness?.generatedAt || rawData?.date || null;

  // ── Tier separator logic ───────────────────────────────────────────
  // When tier grouping is on and sort is by rank ascending, inject
  // visual tier breaks between rows with different effective tier IDs.
  const tierGroupingActive = showTiers && sortCol === "rank" && sortAsc && !hasActiveFilter;

  // ── Render ─────────────────────────────────────────────────────────
  return (
    <section className="card">
      {/* ── Header ──────────────────────────────────────────────────── */}
      <div className="rankings-header">
        <div>
          <h1 className="page-title">Rankings</h1>
          <p className="page-subtitle muted" style={{ marginTop: 4 }}>
            Unified dynasty board &mdash; offense + IDP blended by consensus rank
          </p>
        </div>
        <div className="page-header-actions">
          <button
            className={`button ${showMethodology ? "button-primary" : ""}`}
            onClick={() => setShowMethodology((v) => !v)}
          >
            {showMethodology ? "Hide methodology" : "How this works"}
          </button>
          <button className="button" onClick={copyValues}>
            Copy
          </button>
          {copyStatus && <span className="muted text-sm">{copyStatus}</span>}
        </div>
      </div>

      {/* ── Trust bar ───────────────────────────────────────────────── */}
      {!loading && !error && rows.length > 0 && (
        <div className="rankings-trust-bar">
          <div className="rankings-trust-stat">
            <span className="rankings-trust-value">{trustStats.total.toLocaleString()}</span>
            <span className="rankings-trust-label">Players</span>
          </div>
          <div className="rankings-trust-stat">
            <span className="rankings-trust-value text-green">{trustStats.high.toLocaleString()}</span>
            <span className="rankings-trust-label">High conf</span>
          </div>
          <div className="rankings-trust-stat">
            <span className="rankings-trust-value text-amber">{trustStats.medium.toLocaleString()}</span>
            <span className="rankings-trust-label">Medium</span>
          </div>
          <div className="rankings-trust-stat">
            <span className="rankings-trust-value">{trustStats.low.toLocaleString()}</span>
            <span className="rankings-trust-label">Low</span>
          </div>
          <div className="rankings-trust-stat">
            <span className="rankings-trust-value text-green">{trustStats.multiSource.toLocaleString()}</span>
            <span className="rankings-trust-label">Multi-src</span>
          </div>
          {trustStats.quarantined > 0 && (
            <div className="rankings-trust-stat">
              <span className="rankings-trust-value text-red">{trustStats.quarantined}</span>
              <span className="rankings-trust-label">Quarantined</span>
            </div>
          )}
          {timestamp && (
            <div className="rankings-trust-stat" style={{ marginLeft: "auto" }}>
              <span className="rankings-trust-label">Updated {timestamp}</span>
            </div>
          )}
        </div>
      )}

      {/* ── Methodology (expandable) ────────────────────────────────── */}
      {showMethodology && <MethodologySection />}

      {/* ── Loading / error / empty states ──────────────────────────── */}
      {loading && (
        <div className="loading-state">
          <div className="loading-spinner" />
          <span className="muted text-sm">Loading rankings&hellip;</span>
        </div>
      )}
      {!!error && <p className="error-state-message" style={{ marginTop: 16 }}>{error}</p>}
      {!loading && !error && rows.length === 0 && (
        <div className="empty-state">
          <p className="empty-state-title">No player data available</p>
          <p className="muted text-sm">The backend may still be initializing.</p>
        </div>
      )}

      {/* ── Controls ────────────────────────────────────────────────── */}
      {!loading && !error && rows.length > 0 && (
        <>
          <div className="filter-bar">
            <input
              className="input"
              placeholder="Search player..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ flex: 1, minWidth: 140 }}
            />
            <select className="select" value={posFilter} onChange={(e) => setPosFilter(e.target.value)}>
              {POS_FILTERS.map((f) => (
                <option key={f.key} value={f.key}>{f.label}</option>
              ))}
            </select>
            <select className="select hide-mobile" value={confFilter} onChange={(e) => setConfFilter(e.target.value)}>
              {CONFIDENCE_FILTERS.map((f) => (
                <option key={f.key} value={f.key}>{f.label}</option>
              ))}
            </select>
            <select className="select hide-mobile" value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
              {SOURCE_FILTERS.map((f) => (
                <option key={f.key} value={f.key}>{f.label}</option>
              ))}
            </select>
            <button
              className={`button hide-mobile ${showTiers ? "button-primary" : ""}`}
              onClick={() => setShowTiers((v) => !v)}
              title="Toggle tier grouping"
            >
              Tiers
            </button>
            {trustStats.withAnomalies > 0 && (
              <button
                className={`button ${showAnomalies ? "button-primary" : ""}`}
                onClick={() => setShowAnomalies((v) => !v)}
                title="Show only rows with anomaly flags"
              >
                Flagged ({trustStats.withAnomalies})
              </button>
            )}
          </div>

          <p className="muted text-xs" style={{ margin: "6px 0 0" }}>
            {displayRows.length.toLocaleString()}{hasMore ? ` of ${ranked.length.toLocaleString()}` : ""} shown
            {confFilter !== "all" && ` \u00B7 ${confFilter} confidence`}
            {sourceFilter !== "all" && ` \u00B7 ${sourceFilter === "multi" ? "multi-source" : "single-source"}`}
            {showAnomalies && " \u00B7 flagged only"}
            {tierGroupingActive && " \u00B7 grouped by tier"}
          </p>

          {/* ── Table ───────────────────────────────────────────────── */}
          <div className="table-wrap" style={{ marginTop: 10 }}>
            <table>
              <thead>
                <tr>
                  <SortHeader col="rank" style={{ width: 50, textAlign: "center" }}>Rank</SortHeader>
                  <th className="hide-mobile" style={{ width: 90 }}>Tier</th>
                  <SortHeader col="name">Player</SortHeader>
                  <SortHeader col="pos" style={{ width: 54 }}>Pos</SortHeader>
                  <SortHeader col="value" style={{ textAlign: "right" }}>Value</SortHeader>
                  <SortHeader col="confidence" style={{ textAlign: "center" }} className="hide-mobile">Conf</SortHeader>
                  <th className="hide-mobile" style={{ textAlign: "center", width: 90 }}>Gap</th>
                </tr>
              </thead>
              <tbody>
                {displayRows.map((row, idx) => {
                  const flags = row.anomalyFlags || [];
                  const isQuarantined = row.quarantined;
                  const gap = marketGapLabel(row);
                  const chips = rowChips(row);
                  const val = Math.round(row.rankDerivedValue || row.values.full);
                  const band = valueBand(val);
                  const tier = tierLabel(row);
                  const tierId = effectiveTierId(row);

                  // Tier separator: insert when tier changes between adjacent rows
                  const prevTierId = idx > 0 ? effectiveTierId(displayRows[idx - 1]) : null;
                  const showTierBreak = tierGroupingActive && idx > 0 && tierId !== prevTierId && tierId != null;

                  return (
                    <Fragment key={row.name}>
                      {showTierBreak && (
                        <tr className="rankings-tier-separator">
                          <td colSpan={7}>
                            <span className="rankings-tier-separator-label">{tier}</span>
                          </td>
                        </tr>
                      )}
                      <tr className={isQuarantined ? "rankings-row-quarantined" : undefined}>
                        {/* Rank */}
                        <td style={{ textAlign: "center", fontWeight: 700, color: "var(--cyan)", fontFamily: "var(--mono)" }}>
                          {row.rank || "\u2014"}
                        </td>

                        {/* Tier label */}
                        <td className="hide-mobile">
                          <span className={`rankings-tier-badge ${band.css}`}>{tier}</span>
                        </td>

                        {/* Player: name, team, age, chips */}
                        <td>
                          <div className="rankings-player-cell">
                            <span
                              className="rankings-player-name"
                              onClick={() => openPlayerPopup?.(row)}
                            >
                              {row.name}
                            </span>
                            {/* Context: team + age inline */}
                            {(row.team || row.age) && (
                              <span className="rankings-player-meta">
                                {row.team || ""}{row.age ? `, ${row.age}` : ""}
                              </span>
                            )}
                            {/* Fast-scan chips */}
                            {chips.length > 0 && (
                              <span className="rankings-chips">
                                {chips.map((c) => (
                                  <span key={c.label} className={`badge ${c.css} rankings-chip`} title={c.title}>{c.label}</span>
                                ))}
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Position */}
                        <td>
                          <span className={`badge ${row.assetClass === "offense" ? "badge-cyan" : row.assetClass === "idp" ? "badge-amber" : ""}`}>
                            {row.pos}
                          </span>
                        </td>

                        {/* Value + value-band label */}
                        <td style={{ textAlign: "right" }}>
                          <span className="rankings-value">{val.toLocaleString()}</span>
                          <span className={`rankings-value-band ${band.css}`}>{band.label}</span>
                        </td>

                        {/* Confidence */}
                        <td className="hide-mobile" style={{ textAlign: "center" }}>
                          <span className={confidenceBadgeClass(row.confidenceBucket)}>
                            {confidenceBadgeLabel(row.confidenceBucket)}
                          </span>
                        </td>

                        {/* Market gap */}
                        <td className="hide-mobile" style={{ textAlign: "center" }}>
                          {gap ? (
                            <span className="rankings-gap-label">{gap}</span>
                          ) : (
                            <span className="muted">\u2014</span>
                          )}
                        </td>
                      </tr>
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* ── Show more / show all ────────────────────────────────── */}
          {hasMore && (
            <div style={{ textAlign: "center", marginTop: 12 }}>
              <button className="button" onClick={() => setRowLimit((l) => l + 200)}>
                Show more ({(ranked.length - rowLimit).toLocaleString()} remaining)
              </button>
              <button className="button" onClick={() => setRowLimit(Infinity)} style={{ marginLeft: 8 }}>
                Show all
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}


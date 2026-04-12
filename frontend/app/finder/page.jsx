"use client";

import { useMemo, useState, useCallback } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { useApp } from "@/components/AppShell";
import { actionLabel, cautionLabels } from "@/lib/edge-helpers";
import { posBadgeClass, confBadgeClass, confBadgeLabel as confLabel, isEligibleForAnalysis } from "@/lib/display-helpers";
import { rowChips } from "@/lib/rankings-helpers";
import { FINDER_ROW_LIMIT, CONFIDENCE_SPREAD_HIGH } from "@/lib/thresholds";
import { getRetailLabel } from "@/lib/dynasty-data";

// ── Finder Page ────────────────────────────────────────────────────────────
// Filter-driven player discovery tool. Each workflow surfaces a specific type
// of opportunity from the ranking data's source agreement signals.

// ── Workflow presets ─────────────────────────────────────────────────────

const WORKFLOWS = [
  {
    key: "wr-gaps",
    label: "WR Gaps",
    description:
      "Wide receivers where ranking sources disagree most — potential buy-low or sell-high targets depending on which market you trust.",
    filter: (r) =>
      r.pos === "WR" &&
      (r.sourceRankSpread ?? 0) > 15 &&
      (r.rank ?? Infinity) <= 250 &&
      !r.quarantined,
    sort: (a, b) => (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0),
    showSpread: true,
    showGap: true,
  },
  {
    key: "stable-idp",
    label: "Stable IDP",
    description:
      "IDP players with high confidence and tight multi-source agreement. Safest IDP targets for trades — both markets agree on value.",
    filter: (r) =>
      r.assetClass === "idp" &&
      r.confidenceBucket === "high" &&
      (r.sourceCount ?? 0) >= 2 &&
      !r.quarantined,
    sort: (a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity),
    showSpread: true,
    showGap: false,
  },
  {
    key: "single-risk",
    label: "1-Source Risk",
    description:
      "Players valued from only one ranking source. Higher uncertainty — value could shift significantly if another source disagrees.",
    filter: (r) => r.isSingleSource && (r.rank ?? Infinity) <= 300,
    sort: (a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity),
    showSpread: false,
    showGap: false,
  },
  {
    key: "rookie-spread",
    label: "Rookie Spread",
    description:
      "Rookies where ranking sources disagree — upside signal if one market sees value the other doesn't. Worth monitoring through camp.",
    filter: (r) =>
      r.rookie &&
      (r.sourceRankSpread ?? 0) > 10 &&
      (r.rank ?? Infinity) <= 400 &&
      !r.quarantined,
    sort: (a, b) => (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0),
    showSpread: true,
    showGap: true,
  },
  {
    key: "all",
    label: "All Players",
    description: "Browse the full ranked board with your own filters. Use position and confidence filters to narrow results.",
    filter: () => true,
    sort: (a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity),
    showSpread: true,
    showGap: true,
  },
];

const POS_FILTERS = [
  { key: "all", label: "All positions" },
  { key: "offense", label: "Offense" },
  { key: "idp", label: "IDP" },
  { key: "QB", label: "QB" },
  { key: "RB", label: "RB" },
  { key: "WR", label: "WR" },
  { key: "TE", label: "TE" },
  { key: "DL", label: "DL" },
  { key: "LB", label: "LB" },
  { key: "DB", label: "DB" },
];

const CONF_FILTERS = [
  { key: "all", label: "Any confidence" },
  { key: "high", label: "High" },
  { key: "medium", label: "Medium" },
  { key: "low", label: "Low" },
];

function posMatches(row, filter) {
  if (filter === "all") return true;
  if (filter === "offense") return row.assetClass === "offense";
  if (filter === "idp") return row.assetClass === "idp";
  return row.pos === filter;
}

const ROW_LIMIT = FINDER_ROW_LIMIT;

// ── Main component ────────────────────────────────────────────────────────

export default function FinderPage() {
  const { loading, error, rows } = useDynastyData();
  const { openPlayerPopup } = useApp();

  const [activeWorkflow, setActiveWorkflow] = useState("wr-gaps");
  const [query, setQuery] = useState("");
  const [posFilter, setPosFilter] = useState("all");
  const [confFilter, setConfFilter] = useState("all");
  const [expanded, setExpanded] = useState(false);

  const handleWorkflowChange = useCallback((key) => {
    setActiveWorkflow(key);
    setQuery("");
    setPosFilter("all");
    setConfFilter("all");
    setExpanded(false);
  }, []);

  // Eligible: non-pick, ranked players
  const eligible = useMemo(
    () => rows.filter(isEligibleForAnalysis),
    [rows],
  );

  const workflow = WORKFLOWS.find((w) => w.key === activeWorkflow) || WORKFLOWS[0];

  const results = useMemo(() => {
    let list = eligible.filter(workflow.filter);

    // Layer on user filters
    if (posFilter !== "all") list = list.filter((r) => posMatches(r, posFilter));
    if (confFilter !== "all") {
      list = list.filter((r) => {
        if (confFilter === "low") return r.confidenceBucket === "low" || r.confidenceBucket === "none";
        return r.confidenceBucket === confFilter;
      });
    }
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      list = list.filter((r) => r.name.toLowerCase().includes(q));
    }

    return [...list].sort(workflow.sort);
  }, [eligible, workflow, posFilter, confFilter, query]);

  const displayRows = expanded ? results : results.slice(0, ROW_LIMIT);
  const hasMore = results.length > ROW_LIMIT && !expanded;

  return (
    <section>
      {/* ── Header ──────────────────────────────────────────────────── */}
      <div className="card">
        <h1 className="page-title">Finder</h1>
        <p className="page-subtitle muted" style={{ marginTop: 4 }}>
          Player discovery tool &mdash; surface opportunities by source signal patterns
        </p>
        <p className="text-xs muted" style={{ marginTop: 6, lineHeight: 1.5, maxWidth: 680 }}>
          Each workflow filters for a specific type of opportunity derived from how ranking sources agree or disagree.
          Combine presets with position and confidence filters to narrow your search.
        </p>
      </div>

      {loading && (
        <div className="card loading-state">
          <div className="loading-spinner" />
          <span className="muted text-sm">Loading player data&hellip;</span>
        </div>
      )}
      {!!error && <div className="card"><p className="text-red">{error}</p></div>}

      {!loading && !error && rows.length === 0 && (
        <div className="card empty-state">
          <p className="empty-state-title">No player data available</p>
          <p className="muted text-sm">The backend may still be initializing.</p>
        </div>
      )}

      {!loading && !error && eligible.length > 0 && (
        <div className="card">
          {/* ── Workflow tabs ────────────────────────────────────────── */}
          <div className="sub-nav">
            {WORKFLOWS.map((w) => (
              <button
                key={w.key}
                className={`sub-nav-btn ${activeWorkflow === w.key ? "active" : ""}`}
                onClick={() => handleWorkflowChange(w.key)}
              >
                {w.label}
              </button>
            ))}
          </div>

          {/* ── Workflow description ────────────────────────────────── */}
          <p className="muted text-xs" style={{ margin: "0 0 10px", lineHeight: 1.4 }}>
            {workflow.description}
          </p>

          {/* ── Filters ─────────────────────────────────────────────── */}
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
            <select className="select" value={confFilter} onChange={(e) => setConfFilter(e.target.value)}>
              {CONF_FILTERS.map((f) => (
                <option key={f.key} value={f.key}>{f.label}</option>
              ))}
            </select>
          </div>

          <p className="muted text-xs" style={{ margin: "6px 0 0" }}>
            {results.length.toLocaleString()} player{results.length !== 1 ? "s" : ""} match
            {posFilter !== "all" && ` \u00B7 ${posFilter}`}
            {confFilter !== "all" && ` \u00B7 ${confFilter} conf`}
          </p>

          {/* ── Results table ───────────────────────────────────────── */}
          {results.length === 0 ? (
            <div className="empty-state" style={{ margin: "20px 0" }}>
              <p className="empty-state-title">No players match</p>
              <p className="muted text-sm">Try adjusting your filters or switching to a different workflow.</p>
            </div>
          ) : (
            <>
              <div className="table-wrap" style={{ marginTop: 10 }}>
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: 40, textAlign: "center" }}>#</th>
                      <th>Player</th>
                      <th style={{ width: 54 }}>Pos</th>
                      <th style={{ textAlign: "right", width: 70 }}>Value</th>
                      {workflow.showSpread && <th style={{ textAlign: "center", width: 60 }}>Spread</th>}
                      {workflow.showGap && <th style={{ width: 70 }}>Higher</th>}
                      <th style={{ textAlign: "center", width: 55 }}>Conf</th>
                      <th className="hide-mobile" style={{ width: 160 }}>Signal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayRows.map((row) => {
                      const val = Math.round(row.rankDerivedValue || row.values?.full || 0);
                      const action = actionLabel(row);
                      const cautions = cautionLabels(row);
                      const chips = rowChips(row);
                      return (
                        <tr key={row.name} className={row.quarantined ? "rankings-row-quarantined" : undefined}>
                          <td style={{ textAlign: "center", fontWeight: 700, color: "var(--cyan)", fontFamily: "var(--mono)" }}>
                            {row.rank || "\u2014"}
                          </td>
                          <td>
                            <span
                              style={{ fontWeight: 600, cursor: "pointer" }}
                              onClick={() => openPlayerPopup?.(row)}
                            >
                              {row.name}
                            </span>
                            {(row.team || row.age) && (
                              <span className="muted text-xs" style={{ marginLeft: 6 }}>
                                {row.team || ""}{row.age ? `, ${row.age}` : ""}
                              </span>
                            )}
                            {chips.length > 0 && (
                              <span className="rankings-chips">
                                {chips.map((c) => (
                                  <span key={c.label} className={`badge ${c.css} rankings-chip`} title={c.title} style={{ fontSize: "0.6rem" }}>{c.label}</span>
                                ))}
                              </span>
                            )}
                          </td>
                          <td>
                            <span className={posBadgeClass(row)}>{row.pos}</span>
                          </td>
                          <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                            {val > 0 ? val.toLocaleString() : "\u2014"}
                          </td>
                          {workflow.showSpread && (
                            <td style={{ textAlign: "center", fontFamily: "var(--mono)" }}>
                              {row.sourceRankSpread != null ? (
                                <span style={{ color: (row.sourceRankSpread ?? 0) > CONFIDENCE_SPREAD_HIGH ? "var(--amber)" : "inherit" }}>
                                  {`\u00B1${row.sourceRankSpread}`}
                                </span>
                              ) : "\u2014"}
                            </td>
                          )}
                          {workflow.showGap && (
                            <td style={{ fontSize: "0.78rem" }}>
                              {row.marketGapDirection === "retail_premium" ? (
                                <span className="text-cyan">{getRetailLabel()}</span>
                              ) : row.marketGapDirection === "consensus_premium" ? (
                                <span className="text-amber">Consensus</span>
                              ) : (
                                <span className="muted">\u2014</span>
                              )}
                            </td>
                          )}
                          <td style={{ textAlign: "center" }}>
                            <span className={confBadgeClass(row.confidenceBucket)}>
                              {confLabel(row.confidenceBucket)}
                            </span>
                          </td>
                          <td className="hide-mobile">
                            {action && (
                              <span className={`action-label ${action.css}`} title={action.title}>
                                {action.label}
                              </span>
                            )}
                            {cautions.map((c) => (
                              <span key={c.label} className={`action-label ${c.css}`} title={c.title}>
                                {c.label}
                              </span>
                            ))}
                            {!action && cautions.length === 0 && <span className="muted">\u2014</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {hasMore && (
                <div style={{ textAlign: "center", marginTop: 12 }}>
                  <button className="button" onClick={() => setExpanded(true)}>
                    Show all {results.length.toLocaleString()} results
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}

"use client";

import { Fragment, useMemo, useState, useCallback } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { resolvedRank, RANKING_SOURCES, getRetailLabel } from "@/lib/dynasty-data";
import { useSettings } from "@/components/useSettings";
import { useApp } from "@/components/AppShell";
import {
  tierLabel,
  effectiveTierId,
  valueBand,
  rowChips,
  DEFAULT_ROW_LIMIT,
} from "@/lib/rankings-helpers";
import {
  LENSES,
  getLens,
  applyLens,
  actionLabel,
  cautionLabels,
  computeEdgeSummary,
} from "@/lib/edge-helpers";
import {
  posBadgeClass,
  confBadgeClass as confidenceBadgeClass,
  confBadgeLabel as confidenceBadgeLabel,
  marketEdge,
  isEligibleForBoard,
} from "@/lib/display-helpers";

// ── UNIFIED RANKINGS PAGE ────────────────────────────────────────────
// Trust-forward blended board: offense + IDP sorted by unified rank.
// Shows tiers, player context, confidence, value bands, fast-scan chips,
// actionable lenses, and an edge summary rail.
//
// Default experience decisions:
//   • Lens: "consensus" (standard rank view)
//   • Sort: by rank ascending (most intentional view)
//   • Rows shown: 200 initially (starters + depth in 12-team)
//   • Tier grouping: ON by default
//   • Edge rail: visible by default (quick-scan signal)
//   • Flagged rows: shown inline (not hidden)
//   • Quarantined rows: shown but dimmed

const POS_FILTERS = [
  { key: "all", label: "All" },
  { key: "offense", label: "OFF" },
  { key: "idp", label: "IDP" },
  { key: "pick", label: "Picks" },
  { key: "rookie", label: "Rookies" },
  { key: "rookie:QB", label: "R · QB" },
  { key: "rookie:RB", label: "R · RB" },
  { key: "rookie:WR", label: "R · WR" },
  { key: "rookie:TE", label: "R · TE" },
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

function posMatchesFilter(pos, assetClass, filter, row) {
  if (filter === "all") return true;
  if (filter === "offense") return assetClass === "offense";
  if (filter === "idp") return assetClass === "idp";
  if (filter === "pick") return assetClass === "pick";
  if (filter === "rookie") return !!row?.rookie;
  if (filter.startsWith("rookie:")) return !!row?.rookie && pos === filter.split(":")[1];
  return pos === filter;
}

// ── Methodology content ──────────────────────────────────────────────

// ── Source cell formatter ────────────────────────────────────────────
//
// Unified formatting for every per-source cell the rankings table
// renders — both the desktop column cells and the mobile chip strip
// beneath each player row.  Returns:
//
//   hasVal    — true if the source contributed a value for this player
//   primary   — the main label (raw value for value sources, `#rank`
//               for rank-signal sources — per the rank-signal contract
//               described on `RANKING_SOURCES` in dynasty-data.js,
//               which requires UIs to render `sourceOriginalRanks`
//               and never the synthetic value stamped for sort order).
//   rankLabel — the effective rank on the shared board, wrapped with
//               a `#` prefix and the `eff` prefix for rank-signal
//               sources where "primary" is already a rank; this makes
//               the distinction explicit in the cell output.
//   title     — hover tooltip explaining the cell.
//
// Mirror the display format between desktop and mobile by always
// using this helper so both surfaces show `value (#rank)` consistently.
function formatSourceCell(row, src) {
  const rawVal = row?.canonicalSites?.[src.key];
  const hasVal = rawVal != null && Number.isFinite(Number(rawVal));
  const effectiveRank = row?.sourceRanks?.[src.key];
  const origRank = row?.sourceOriginalRanks?.[src.key];

  if (!hasVal) {
    return {
      hasVal: false,
      primary: "\u2014",
      rankLabel: "\u2014",
      title: `${src.displayName} did not list this player`,
    };
  }

  if (src.isRankSignal) {
    // Rank-signal sources (DLF SF, DLF IDP, DN SF-TEP, FP IDP) expose
    // only ordinal rank, not a trade value.  Render the original rank
    // as primary and the effective (shared-market-translated) rank
    // in parentheses, prefixed with `eff` to disambiguate.
    const primary = origRank != null ? `#${origRank}` : "\u2014";
    const rankLabel =
      effectiveRank != null ? `eff #${effectiveRank}` : "eff \u2014";
    return {
      hasVal: true,
      primary,
      rankLabel,
      title: `${src.displayName}: original rank ${primary}, effective rank on blended board ${
        effectiveRank != null ? `#${effectiveRank}` : "\u2014"
      }`,
    };
  }

  // Value source: raw value as primary, effective rank in parens.
  const primary = Math.round(Number(rawVal)).toLocaleString();
  const rankLabel = effectiveRank != null ? `#${effectiveRank}` : "\u2014";
  return {
    hasVal: true,
    primary,
    rankLabel,
    title: `${src.displayName}: value ${primary}${
      effectiveRank != null ? `, effective rank #${effectiveRank}` : ""
    }`,
  };
}

function MethodologySection() {
  const sourceNames = RANKING_SOURCES.map((s) => s.displayName).join(", ");
  return (
    <div className="rankings-methodology-body">
      <h3 style={{ margin: "0 0 8px", fontSize: "0.88rem" }}>How rankings work</h3>
      <ol style={{ margin: 0, paddingLeft: 18, fontSize: "0.78rem", lineHeight: 1.7, color: "var(--subtext)" }}>
        <li><strong>Source ingestion</strong> — Raw values from {sourceNames}.</li>
        <li><strong>Per-source ranking</strong> — Each player ranked within each source by raw value (highest = rank 1).</li>
        <li><strong>Rank normalization</strong> — Per-source ranks converted to 1–9,999 values via Hill-curve formula so sources are comparable.</li>
        <li><strong>Blended ranking</strong> — Multi-source players get averaged normalized values. Single-source players keep their one value.</li>
        <li><strong>Unified sort</strong> — All players sorted by blended value into one board. Top 800 get a consensus rank.</li>
        <li><strong>Tier detection</strong> — Natural value clusters detected via gap analysis. Tier breaks appear where adjacent players have unusually large value gaps.</li>
        <li><strong>Confidence scoring</strong> — High = 2+ sources, spread &le; 30. Medium = 2+ sources, spread &le; 80. Low = single source or spread &gt; 80.</li>
        <li><strong>Identity validation</strong> — Post-ranking pass checks for entity resolution problems. Flagged rows are quarantined (confidence degraded, not removed).</li>
      </ol>
      <p style={{ margin: "8px 0 0", fontSize: "0.72rem", color: "var(--muted)", fontFamily: "var(--mono)" }}>
        value = max(1, min(9999, round(1 + 9998 / (1 + ((rank-1)/45)^1.10))))
      </p>
    </div>
  );
}

// ── Edge rail section ────────────────────────────────────────────────

function EdgeRailSection({ label, items, emptyText, onPlayerClick }) {
  return (
    <div className="edge-rail-section">
      <h4 className="edge-rail-section-title">{label}</h4>
      {items.length === 0 ? (
        <p className="muted text-xs">{emptyText}</p>
      ) : (
        <ul className="edge-rail-list">
          {items.map((item) => (
            <li key={item.name} className="edge-rail-item">
              <span
                className="edge-rail-name"
                onClick={() => onPlayerClick?.(item.row)}
              >
                #{item.rank} {item.name}
              </span>
              <span className="edge-rail-pos badge">{item.pos}</span>
              <span className="edge-rail-detail">{item.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function EdgeRail({ summary, onPlayerClick }) {
  const hasSomething =
    summary.retailPremium.length > 0 ||
    summary.consensusPremium.length > 0 ||
    summary.flaggedCautions.length > 0 ||
    summary.consensusAssets.length > 0;

  if (!hasSomething) return null;

  const retailLabel = getRetailLabel();

  return (
    <div className="edge-rail">
      <div className="edge-rail-header">
        <h3 className="edge-rail-title">Edge Summary</h3>
        <span className="muted text-xs">Derived from source agreement data — not predictions</span>
      </div>
      <div className="edge-rail-grid">
        <EdgeRailSection
          label="Sell Signals"
          items={summary.retailPremium}
          emptyText="No sell signals"
          onPlayerClick={onPlayerClick}
        />
        <EdgeRailSection
          label="Buy Signals"
          items={summary.consensusPremium}
          emptyText="No buy signals"
          onPlayerClick={onPlayerClick}
        />
        <EdgeRailSection
          label="Consensus Assets"
          items={summary.consensusAssets}
          emptyText="No high-confidence consensus assets"
          onPlayerClick={onPlayerClick}
        />
        <EdgeRailSection
          label="Flagged — Needs Caution"
          items={summary.flaggedCautions}
          emptyText="No flagged players in top 300"
          onPlayerClick={onPlayerClick}
        />
      </div>
    </div>
  );
}

// ── Custom Mix badge ─────────────────────────────────────────────────
// Renders next to the page title when the active rankings payload was
// computed from a user-customized source configuration.  Clicking the
// badge toggles a short description listing disabled sources and any
// weights that differ from the registry defaults.  The data comes from
// ``rawData.rankingsOverride`` which the backend stamps on both the
// full-contract and delta-merged responses.
//
// The derivation logic is factored into ``describeCustomMix`` so unit
// tests can pin the business rules without spinning up a DOM.
export function describeCustomMix(rankingsOverride) {
  if (!rankingsOverride || !rankingsOverride.isCustomized) {
    return { active: false, disabled: [], reweighted: [], summary: "" };
  }
  const received = rankingsOverride.received || {};
  const defaults = rankingsOverride.defaults || {};
  const weights = rankingsOverride.weights || {};

  const disabled = [];
  const reweighted = [];
  for (const src of RANKING_SOURCES) {
    const ov = received[src.key];
    if (ov && ov.include === false) {
      disabled.push(src.columnLabel || src.displayName);
      continue;
    }
    const active = Number(weights[src.key]);
    const def = Number(defaults[src.key] ?? src.weight ?? 1);
    if (Number.isFinite(active) && active !== def) {
      reweighted.push(
        `${src.columnLabel || src.displayName} ${def.toFixed(1)}→${active.toFixed(1)}`,
      );
    }
  }

  const parts = [];
  if (disabled.length) parts.push(`${disabled.length} disabled`);
  if (reweighted.length) parts.push(`${reweighted.length} reweighted`);
  const summary = parts.length ? `(${parts.join(", ")})` : "";

  return { active: true, disabled, reweighted, summary };
}

function CustomMixBadge({ rankingsOverride }) {
  const [open, setOpen] = useState(false);
  const { active, disabled, reweighted, summary } = describeCustomMix(rankingsOverride);
  if (!active) return null;

  return (
    <span
      className="custom-mix-badge-wrap"
      aria-label="Custom source mix active"
    >
      <button
        type="button"
        className="badge badge-amber custom-mix-badge"
        onClick={() => setOpen((v) => !v)}
        title={
          open
            ? "Hide custom mix details"
            : "Click to see which sources are customized"
        }
      >
        Custom Mix {summary}
      </button>
      {open && (
        <div className="custom-mix-popover" role="tooltip">
          <p className="custom-mix-popover-title">Custom source configuration</p>
          {disabled.length > 0 && (
            <div className="custom-mix-popover-row">
              <span className="custom-mix-popover-label">Disabled:</span>
              <span className="custom-mix-popover-value">
                {disabled.join(", ")}
              </span>
            </div>
          )}
          {reweighted.length > 0 && (
            <div className="custom-mix-popover-row">
              <span className="custom-mix-popover-label">Reweighted:</span>
              <span className="custom-mix-popover-value">
                {reweighted.join(", ")}
              </span>
            </div>
          )}
          <p className="custom-mix-popover-hint muted">
            Change these on the Settings page.
          </p>
        </div>
      )}
    </span>
  );
}

// ── Main component ───────────────────────────────────────────────────

export default function RankingsPage() {
  const { loading, error, source, rows, rawData } = useDynastyData();
  const { settings } = useSettings();
  const { openPlayerPopup } = useApp();
  const [query, setQuery] = useState("");
  const [posFilter, setPosFilter] = useState("all");
  const [confFilter, setConfFilter] = useState("all");
  const [activeLens, setActiveLens] = useState("consensus");
  const [showTiers, setShowTiers] = useState(true);
  const [showEdgeRail, setShowEdgeRail] = useState(true);
  const [showIdpUncalibrated, setShowIdpUncalibrated] = useState(false);
  const [rowLimit, setRowLimit] = useState(DEFAULT_ROW_LIMIT);
  const [sortCol, setSortCol] = useState("rank");
  const [sortAsc, setSortAsc] = useState(true);
  const [copyStatus, setCopyStatus] = useState("");
  const [showMethodology, setShowMethodology] = useState(false);
  const [expandedRow, setExpandedRow] = useState(null);

  const handleSort = useCallback((col) => {
    if (sortCol === col) {
      setSortAsc((prev) => !prev);
    } else {
      setSortCol(col);
      setSortAsc(["rank", "name", "pos"].includes(col));
    }
  }, [sortCol]);

  // Switch lens: reset sort to default, expand row limit
  const handleLensChange = useCallback((key) => {
    setActiveLens(key);
    const lens = getLens(key);
    if (lens.sort) {
      // Non-consensus lenses have their own sort — disable manual sort
      setSortCol("lens");
      setSortAsc(true);
    } else {
      setSortCol("rank");
      setSortAsc(true);
    }
    // Expand limit for filtered lenses since they show fewer rows
    if (key !== "consensus") {
      setRowLimit(Infinity);
    } else {
      setRowLimit(DEFAULT_ROW_LIMIT);
    }
  }, []);

  // ── Calibration toggle ──────────────────────────────────────
  // When on, swap each row's rank + value with the pre-calibration
  // snapshots the backend already stamped. Because the backend anchors
  // rankDerivedValue onto the Hill curve after every calibration pass,
  // both snapshots are already Hill-curve coherent — this is a pure
  // field swap, not a recomputation. Affects the /rankings view only;
  // the promoted config stays live everywhere else in the app.
  const toggledRows = useMemo(() => {
    if (!showIdpUncalibrated) return rows;
    return rows.map((r) => {
      const uncalValue = Number(r.rankDerivedValueUncalibrated) || null;
      const uncalRank = Number(r.canonicalConsensusRankUncalibrated) || null;
      if (!uncalValue && !uncalRank) return r;
      const next = { ...r };
      if (uncalValue) {
        next.rankDerivedValue = uncalValue;
        next.values = { ...(r.values || {}), full: uncalValue };
      }
      if (uncalRank) {
        next.canonicalConsensusRank = uncalRank;
      }
      return next;
    });
  }, [rows, showIdpUncalibrated]);

  // ── Base eligible list ──────────────────────────────────────────
  const eligible = useMemo(() => {
    return toggledRows.filter(isEligibleForBoard);
  }, [toggledRows]);

  // ── Trust summary stats ──────────────────────────────────────────
  // Single-pass aggregate — six filters would each walk the full
  // eligible array (N = 1000-ish), and the memo re-runs on every
  // lens/filter change. One pass keeps the summary O(N) total instead
  // of O(6N).
  const trustStats = useMemo(() => {
    let high = 0;
    let medium = 0;
    let low = 0;
    let quarantined = 0;
    let multiSource = 0;
    let withAnomalies = 0;
    for (const r of eligible) {
      const bucket = r.confidenceBucket;
      if (bucket === "high") high++;
      else if (bucket === "medium") medium++;
      else if (bucket === "low" || bucket === "none") low++;
      if (r.quarantined) quarantined++;
      if ((r.sourceCount || 0) >= 2) multiSource++;
      if ((r.anomalyFlags || []).length > 0) withAnomalies++;
    }
    return { total: eligible.length, high, medium, low, quarantined, multiSource, withAnomalies };
  }, [eligible]);

  // ── Edge summary ─────────────────────────────────────────────────
  const edgeSummary = useMemo(() => computeEdgeSummary(eligible), [eligible]);

  // ── Filtered + sorted list ──────────────────────────────────────
  const ranked = useMemo(() => {
    const q = query.trim().toLowerCase();

    // Start with lens-filtered list
    let list = applyLens(eligible, activeLens);

    // Additional filters layer on top of lens
    if (posFilter !== "all") {
      list = list.filter((r) => posMatchesFilter(r.pos, r.assetClass, posFilter, r));
    }
    if (confFilter !== "all") {
      list = list.filter((r) => {
        if (confFilter === "low") return r.confidenceBucket === "low" || r.confidenceBucket === "none";
        return r.confidenceBucket === confFilter;
      });
    }
    if (q) {
      list = list.filter((r) => r.name.toLowerCase().includes(q));
    }

    // If lens provides its own sort and user hasn't overridden, use it
    const lens = getLens(activeLens);
    if (sortCol === "lens" && lens.sort) {
      return list; // already sorted by applyLens
    }

    // Manual sort
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
        case "score":
          va = a.blendedSourceRank ?? Infinity;
          vb = b.blendedSourceRank ?? Infinity;
          return (va - vb) * dir;
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
        default: {
          // Dynamic source-column sort: col === `src:${sourceKey}`.
          // Keeps the rankings table self-describing so any source
          // registered in RANKING_SOURCES gets a sortable column
          // automatically.
          if (typeof sortCol === "string" && sortCol.startsWith("src:")) {
            const key = sortCol.slice(4);
            va = Number(a.canonicalSites?.[key]) || 0;
            vb = Number(b.canonicalSites?.[key]) || 0;
            return (va - vb) * dir;
          }
          return resolvedRank(a) - resolvedRank(b);
        }
      }
    });
    return sorted;
  }, [eligible, activeLens, posFilter, confFilter, query, sortCol, sortAsc]);

  // Apply row limit — search/filter bypasses the limit
  const hasActiveFilter = query || posFilter !== "all" || confFilter !== "all" || activeLens !== "consensus";
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

  // ── Copy/Export ────────────────────────────────────────────────────
  async function copyValues() {
    // Header: fixed columns, then one pair (value + rank) per registered source.
    const sourceHeaders = RANKING_SOURCES.flatMap((src) => [
      src.columnLabel,
      `${src.columnLabel} Rank`,
    ]);
    const lines = [
      [
        "Rank", "Player", "Pos", "Team", "Tier", "Value", "Value Band",
        "Confidence", "Action", "Sources",
        ...sourceHeaders,
      ].join("\t"),
    ];
    displayRows.forEach((row) => {
      const val = Math.round(row.rankDerivedValue || row.values?.full || 0);
      const band = valueBand(val);
      const action = actionLabel(row);
      const cautions = cautionLabels(row);
      const actionStr = [action?.label, ...cautions.map((c) => c.label)].filter(Boolean).join("; ");
      const sourceCells = RANKING_SOURCES.flatMap((src) => {
        const raw = row.canonicalSites?.[src.key];
        const valCell = raw != null && Number.isFinite(Number(raw))
          ? Math.round(Number(raw))
          : "";
        const rankCell = row.sourceRanks?.[src.key] ?? "";
        return [valCell, rankCell];
      });
      lines.push(
        [
          row.rank, row.name, row.pos, row.team || "",
          tierLabel(row), val, band.label,
          row.confidenceBucket || "", actionStr, row.sourceCount || 0,
          ...sourceCells,
        ].join("\t")
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
  const tierGroupingActive = showTiers && sortCol === "rank" && sortAsc && activeLens === "consensus" && !query;

  // ── Active lens descriptor ─────────────────────────────────────────
  const currentLens = getLens(activeLens);

  // ── Render ─────────────────────────────────────────────────────────
  return (
    <section className="card">
      {/* ── Header ──────────────────────────────────────────────────── */}
      <div className="rankings-header">
        <div>
          <div className="rankings-title-row">
            <h1 className="page-title">Rankings</h1>
            <CustomMixBadge rankingsOverride={rawData?.rankingsOverride} />
          </div>
          <p className="page-subtitle muted" style={{ marginTop: 4 }}>
            Unified dynasty board &mdash; offense + IDP blended by consensus rank
          </p>
        </div>
        <div className="page-header-actions">
          <button
            className={`button ${showEdgeRail ? "button-primary" : ""}`}
            onClick={() => setShowEdgeRail((v) => !v)}
          >
            {showEdgeRail ? "Hide edge" : "Show edge"}
          </button>
          <button
            className={`button ${showIdpUncalibrated ? "button-primary" : ""}`}
            onClick={() => setShowIdpUncalibrated((v) => !v)}
            title="Toggle IDP calibration display. Swaps each IDP row to its pre-calibration value and re-sorts."
          >
            {showIdpUncalibrated ? "IDP: uncalibrated" : "IDP: calibrated"}
          </button>
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

      {/* ── Edge rail (expandable) ──────────────────────────────────── */}
      {!loading && !error && showEdgeRail && rows.length > 0 && (
        <EdgeRail summary={edgeSummary} onPlayerClick={openPlayerPopup} />
      )}

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

      {/* ── Lens selector + controls ────────────────────────────────── */}
      {!loading && !error && rows.length > 0 && (
        <>
          {/* Lens tabs */}
          <div className="sub-nav" style={{ marginTop: "var(--space-sm)" }}>
            {LENSES.map((lens) => (
              <button
                key={lens.key}
                className={`sub-nav-btn ${activeLens === lens.key ? "active" : ""}`}
                onClick={() => handleLensChange(lens.key)}
                title={lens.description}
              >
                {lens.label}
              </button>
            ))}
          </div>

          {/* Lens description */}
          {activeLens !== "consensus" && (
            <p className="muted text-xs" style={{ margin: "4px 0 8px", lineHeight: 1.4 }}>
              {currentLens.description}
            </p>
          )}

          {/* Filters */}
          <div className="filter-bar">
            <input
              className="input"
              placeholder="Search player..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ flex: 1, minWidth: 140 }}
            />
            <select className="select" value={posFilter} onChange={(e) => setPosFilter(e.target.value)}>
              <option value="all">All</option>
              <option value="offense">OFF</option>
              <option value="idp">IDP</option>
              <option value="pick">Picks</option>
              <optgroup label="Rookies">
                <option value="rookie">All Rookies</option>
                <option value="rookie:QB">R · QB</option>
                <option value="rookie:RB">R · RB</option>
                <option value="rookie:WR">R · WR</option>
                <option value="rookie:TE">R · TE</option>
              </optgroup>
              <optgroup label="Position">
                <option value="QB">QB</option>
                <option value="RB">RB</option>
                <option value="WR">WR</option>
                <option value="TE">TE</option>
                <option value="DL">DL</option>
                <option value="LB">LB</option>
                <option value="DB">DB</option>
              </optgroup>
            </select>
            <select className="select hide-mobile" value={confFilter} onChange={(e) => setConfFilter(e.target.value)}>
              {CONFIDENCE_FILTERS.map((f) => (
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
          </div>

          <p className="muted text-xs" style={{ margin: "6px 0 0" }}>
            {displayRows.length.toLocaleString()}{hasMore ? ` of ${ranked.length.toLocaleString()}` : ""} shown
            {activeLens !== "consensus" && ` \u00B7 ${currentLens.label} lens`}
            {confFilter !== "all" && ` \u00B7 ${confFilter} confidence`}
            {tierGroupingActive && " \u00B7 grouped by tier"}
          </p>

          {/* ── Table ───────────────────────────────────────────────── */}
          <div className="table-wrap" style={{ marginTop: 10 }}>
            <table>
              <thead>
                <tr>
                  <SortHeader col="rank" style={{ width: 36, textAlign: "center" }}>#</SortHeader>
                  <th className="hide-mobile" style={{ width: 90 }}>Tier</th>
                  <SortHeader col="name">Player</SortHeader>
                  <SortHeader col="pos" style={{ width: 54 }}>Pos</SortHeader>
                  {/* Consensus — decimal mean of per-source effective ranks.
                      This is NOT the engine's final opinion (the # column is).
                      It's an orthogonal transparency metric that shows where
                      the sources on average place the player. Gaps between
                      Consensus and # reveal where the blend penalized
                      disagreement. Visible on mobile because it's the
                      hero transparency signal. */}
                  <SortHeader
                    col="score"
                    style={{ textAlign: "right", width: 72 }}
                    title="Consensus: decimal mean of each source's effective rank. Orthogonal to #. When Consensus and # disagree, the blend penalized source disagreement. Lower = better."
                  >
                    Consensus
                  </SortHeader>
                  <SortHeader col="value" style={{ textAlign: "right" }}>Value</SortHeader>
                  {settings.showSiteCols && RANKING_SOURCES.map((src) => (
                    <SortHeader
                      key={src.key}
                      col={`src:${src.key}`}
                      style={{ textAlign: "right", width: 90 }}
                      className="hide-mobile rankings-source-col"
                      title={`${src.displayName} — ${
                        src.isRankSignal
                          ? "expert rank source (lower = better). Cell shows the source's original rank with its effective rank on the shared board in parentheses."
                          : "value source. Cell shows the source's raw trade value with its effective rank on the shared board in parentheses."
                      }`}
                    >
                      {src.columnLabel}
                    </SortHeader>
                  ))}
                  <th className="hide-mobile" style={{ textAlign: "center", width: 72 }} title="Sources that matched this player / sources structurally eligible to cover the player's position.">Sources</th>
                  <SortHeader col="confidence" style={{ textAlign: "center" }} className="hide-mobile" title="High / Medium / Low confidence based on how many sources matched and how tightly they agree.">Confidence</SortHeader>
                  <th className="hide-mobile" style={{ textAlign: "center", width: 140 }} title="Market edge: retail (KTC) vs expert consensus. Always rendered with an explicit state — never an ambiguous dash.">Edge</th>
                  <th className="hide-mobile" style={{ width: 170 }}>Signal</th>
                </tr>
              </thead>
              <tbody>
                {displayRows.map((row, idx) => {
                  const chips = rowChips(row);
                  const val = Math.round(row.rankDerivedValue || row.values?.full || 0);
                  const band = valueBand(val);
                  const tier = tierLabel(row);
                  const tierId = effectiveTierId(row);
                  // Structured market edge descriptor (never returns null).
                  // Replaces the legacy marketGapLabel(row) string which
                  // caused the Gap column to show an ambiguous dash.
                  const edge = marketEdge(row);
                  const isQuarantined = row.quarantined;
                  const action = actionLabel(row);
                  const cautions = cautionLabels(row);
                  const isExpanded = expandedRow === row.name;
                  // Column count drives the tier-separator and audit-panel
                  // colspans.  It tracks the render gate on
                  // ``settings.showSiteCols`` so the separator stretches
                  // cleanly whether or not per-source columns are visible.
                  const totalCols = 10 + (settings.showSiteCols ? RANKING_SOURCES.length : 0);

                  const prevTierId = idx > 0 ? effectiveTierId(displayRows[idx - 1]) : null;
                  const showTierBreak = tierGroupingActive && idx > 0 && tierId !== prevTierId && tierId != null;
                  const tierCssClass = tierId != null ? `tier-${tierId}` : "tier-unknown";

                  // Source audit data for the expanded panel
                  const audit = row.sourceAudit || row.raw?.sourceAudit || {};
                  const srcCount = row.sourceCount ?? Object.keys(row.sourceRanks || {}).length;

                  // Explicit confidence explanation
                  const confExplain = row.confidenceLabel || (
                    row.confidenceBucket === "high" ? "2+ sources, tight agreement (spread \u226430)" :
                    row.confidenceBucket === "medium" ? "2+ sources, moderate spread (30-80)" :
                    row.confidenceBucket === "low" ? "Single source or wide disagreement (spread >80)" :
                    "Unranked"
                  );

                  return (
                    <Fragment key={row.name}>
                      {showTierBreak && (
                        <tr className="rankings-tier-separator">
                          <td colSpan={totalCols}>
                            <span className="rankings-tier-separator-label">{tier}</span>
                          </td>
                        </tr>
                      )}
                      <tr
                        className={[
                          isQuarantined ? "rankings-row-quarantined" : "",
                          isExpanded ? "rankings-row-expanded" : "",
                          "rankings-row-clickable",
                        ].filter(Boolean).join(" ")}
                        onClick={() => setExpandedRow(isExpanded ? null : row.name)}
                      >
                        {/* Rank */}
                        <td style={{ textAlign: "center", fontWeight: 700, color: "var(--cyan)", fontFamily: "var(--mono)" }}>
                          {row.rank || "\u2014"}
                        </td>

                        {/* Tier */}
                        <td className="hide-mobile">
                          <span className={`rankings-tier-badge ${tierCssClass}`}>{tier}</span>
                        </td>

                        {/* Player: name, context, chips */}
                        <td>
                          <div className="rankings-player-cell">
                            <span
                              className="rankings-player-name"
                              onClick={(e) => { e.stopPropagation(); openPlayerPopup?.(row); }}
                            >
                              {row.name}
                            </span>
                            {(row.team || row.age) && (
                              <span className="rankings-player-meta">
                                {row.team || ""}{row.age ? `, ${row.age}` : ""}
                              </span>
                            )}
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
                          <span className={posBadgeClass(row)}>
                            {row.pos}
                          </span>
                        </td>

                        {/* Consensus — decimal mean of per-source effective
                            ranks. Orthogonal to the final # — gaps between
                            this value and the rank column reveal source
                            disagreement that the blend arbitrated.
                            Visible on mobile. */}
                        <td
                          style={{ textAlign: "right", fontFamily: "var(--mono)", fontSize: "0.82rem", color: "var(--cyan)" }}
                          title={row.blendedSourceRank != null ? `Mean source rank ${row.blendedSourceRank.toFixed(2)}. Final rank is ${row.rank ? `#${row.rank}` : "\u2014 (unranked)"}. Gap = blend penalty/bonus for source disagreement.` : "No sources ranked this player"}
                        >
                          {row.blendedSourceRank != null
                            ? row.blendedSourceRank.toFixed(1)
                            : "\u2014"}
                        </td>

                        {/* Value — Hill-curve dynasty value (integer, 1-9999).
                            Band badge (S+/S/D+/D/F) carries a tooltip so
                            users can hover to see what the letter means. */}
                        <td style={{ textAlign: "right" }} title={`Hill-curve value ${val.toLocaleString()} (scale 1\u20139,999)`}>
                          <span className="rankings-value">{val.toLocaleString()}</span>
                          <span
                            className={`rankings-value-band ${band.css}`}
                            title={band.title || "Value band"}
                          >
                            {band.label}
                          </span>
                        </td>

                        {/* Per-source value + rank columns.  Gated on
                            `showSiteCols` so power users can collapse the
                            source columns to focus on the Value column.
                            Each cell shows the source's raw value (or
                            original rank for rank-signal sources) with
                            the effective rank on the shared board in
                            parentheses — unified single-line format. */}
                        {settings.showSiteCols && RANKING_SOURCES.map((src) => {
                          const cell = formatSourceCell(row, src);
                          return (
                            <td
                              key={src.key}
                              className="hide-mobile rankings-source-col"
                              style={{
                                textAlign: "right",
                                fontFamily: "var(--mono, monospace)",
                                fontSize: "0.78rem",
                                whiteSpace: "nowrap",
                              }}
                              title={cell.title}
                            >
                              {cell.hasVal ? (
                                <>
                                  <span className="rankings-source-value">{cell.primary}</span>
                                  <span className="rankings-source-rank"> ({cell.rankLabel})</span>
                                </>
                              ) : (
                                <span className="muted">&mdash;</span>
                              )}
                            </td>
                          );
                        })}

                        {/* Source count */}
                        <td className="hide-mobile" style={{ textAlign: "center", fontFamily: "var(--mono)", fontSize: "0.78rem" }}>
                          <span className={srcCount >= 2 ? "rankings-src-count-multi" : "rankings-src-count-single"}>
                            {srcCount}/{RANKING_SOURCES.filter((s) => {
                              const pos = (row.pos || "").toUpperCase();
                              if (s.scope === "overall_offense") return ["QB","RB","WR","TE","PICK"].includes(pos);
                              if (s.scope === "overall_idp") return ["DL","LB","DB"].includes(pos);
                              return false;
                            }).length || RANKING_SOURCES.length}
                          </span>
                        </td>

                        {/* Confidence */}
                        <td className="hide-mobile" style={{ textAlign: "center" }}>
                          <span className={confidenceBadgeClass(row.confidenceBucket)} title={confExplain}>
                            {confidenceBadgeLabel(row.confidenceBucket)}
                          </span>
                        </td>

                        {/* Market edge — always rendered with an explicit
                            state label.  No ambiguous dashes: the column
                            always tells the user which side is higher and
                            by how much, or why no comparison is possible. */}
                        <td className="hide-mobile" style={{ textAlign: "center" }}>
                          <span className={`edge-label ${edge.css}`} title={edge.title}>{edge.label}</span>
                        </td>

                        {/* Signal */}
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
                          {!action && cautions.length === 0 && (
                            <span className="muted">{"\u2014"}</span>
                          )}
                        </td>
                      </tr>

                      {/* ── Mobile source strip ───────────────────────
                          The desktop table has one column per source,
                          but at ≤768px those columns would overflow
                          horizontally and get hidden via `hide-mobile`.
                          Instead of dropping the data entirely, we
                          render a compact flex strip of source chips
                          below each player row so mobile users see the
                          same per-source value + rank they'd see on
                          desktop.  Gated on `showSiteCols` so the
                          toggle has the same effect on both surfaces.

                          Uses a dedicated `.rankings-mobile-source-row`
                          class (not the global `.mobile-only` helper)
                          so we can set `display: table-row` on mobile
                          — the global helper resolves to
                          `display: initial !important`, which would
                          force the <tr> to `inline` and break the
                          table layout. */}
                      {settings.showSiteCols && (
                        <tr className="rankings-mobile-source-row">
                          <td colSpan={totalCols}>
                            <div className="rankings-mobile-sources">
                              {RANKING_SOURCES.map((src) => {
                                const cell = formatSourceCell(row, src);
                                return (
                                  <span
                                    key={src.key}
                                    className={`rankings-mobile-source-chip${cell.hasVal ? "" : " is-empty"}`}
                                    title={cell.title}
                                  >
                                    <span className="rankings-mobile-source-label">
                                      {src.columnLabel}
                                    </span>
                                    <span className="rankings-mobile-source-val">
                                      {cell.hasVal ? (
                                        <>
                                          {cell.primary}
                                          <span className="rankings-mobile-source-rank">
                                            {" "}
                                            ({cell.rankLabel})
                                          </span>
                                        </>
                                      ) : (
                                        "\u2014"
                                      )}
                                    </span>
                                  </span>
                                );
                              })}
                            </div>
                          </td>
                        </tr>
                      )}

                      {/* ── Expandable source audit panel ──────────── */}
                      {isExpanded && (
                        <tr className="rankings-audit-row">
                          <td colSpan={totalCols}>
                            <div className="source-audit-panel">
                              <div className="source-audit-header">
                                <strong>Source Audit: {row.name}</strong>
                                <span className="muted" style={{ marginLeft: 12 }}>
                                  {audit.reason === "fully_matched" ? "All expected sources matched" :
                                   audit.reason === "structurally_single_source" ? "Only one source structurally covers this player" :
                                   audit.reason === "matching_failure_other_sources_eligible" ? "Matching failure \u2014 expected source(s) did not match" :
                                   audit.reason === "partial_coverage" ? "Some expected sources missing" :
                                   audit.reason === "no_source_match" ? "No source matched" :
                                   audit.reason || ""}
                                </span>
                                {audit.allowlistReason && (
                                  <span className="source-audit-allowlist" title="Allowlisted reason">
                                    {audit.allowlistReason}
                                  </span>
                                )}
                              </div>

                              {/* Per-source detail grid */}
                              <div className="source-audit-grid">
                                {RANKING_SOURCES.map((src) => {
                                  const siteVal = row.canonicalSites?.[src.key];
                                  const hasVal = siteVal != null && Number.isFinite(Number(siteVal)) && Number(siteVal) > 0;
                                  const eRank = row.sourceRanks?.[src.key];
                                  const meta = (row.sourceRankMeta || row.raw?.sourceRankMeta || {})[src.key];
                                  const origRk = (row.sourceOriginalRanks || {})[src.key];
                                  const matchDetail = (audit.matchedDetails || {})[src.key];
                                  const isExpected = (audit.expectedSources || []).includes(src.key);
                                  const isMatched = (audit.matchedSources || []).includes(src.key);
                                  const isUnmatched = (audit.unmatchedSources || []).includes(src.key);

                                  return (
                                    <div key={src.key} className={`source-audit-card ${hasVal ? "source-audit-card-active" : "source-audit-card-missing"}`}>
                                      <div className="source-audit-card-header">
                                        <strong>{src.columnLabel}</strong>
                                        <span className={`badge ${isMatched ? "badge-green" : isUnmatched ? "badge-red" : isExpected ? "badge-amber" : "badge-muted"}`} style={{ fontSize: "0.6rem" }}>
                                          {isMatched ? "matched" : isUnmatched ? "missing" : isExpected ? "expected" : "n/a"}
                                        </span>
                                      </div>
                                      {hasVal ? (
                                        <div className="source-audit-card-body">
                                          <div className="source-audit-field">
                                            <span className="source-audit-label">{src.isRankSignal ? "Rank" : "Value"}</span>
                                            <span className="source-audit-val">
                                              {src.isRankSignal
                                                ? `#${origRk != null ? origRk : "\u2014"}`
                                                : Math.round(Number(siteVal)).toLocaleString()
                                              }
                                            </span>
                                          </div>
                                          {eRank != null && (
                                            <div className="source-audit-field">
                                              <span className="source-audit-label">Eff. Rank</span>
                                              <span className="source-audit-val">#{eRank}</span>
                                            </div>
                                          )}
                                          {meta?.valueContribution != null && (
                                            <div className="source-audit-field">
                                              <span className="source-audit-label">Hill Value</span>
                                              <span className="source-audit-val">{meta.valueContribution.toLocaleString()}</span>
                                            </div>
                                          )}
                                          {meta?.effectiveWeight != null && (
                                            <div className="source-audit-field">
                                              <span className="source-audit-label">Weight</span>
                                              <span className="source-audit-val">{meta.effectiveWeight}</span>
                                            </div>
                                          )}
                                          {meta?.method && (
                                            <div className="source-audit-field">
                                              <span className="source-audit-label">Method</span>
                                              <span className="source-audit-val">{meta.method}</span>
                                            </div>
                                          )}
                                          {matchDetail?.matchedName && (
                                            <div className="source-audit-field">
                                              <span className="source-audit-label">Matched As</span>
                                              <span className="source-audit-val">{matchDetail.matchedName}</span>
                                            </div>
                                          )}
                                          {matchDetail?.via && (
                                            <div className="source-audit-field">
                                              <span className="source-audit-label">Via</span>
                                              <span className="source-audit-val">{matchDetail.via}</span>
                                            </div>
                                          )}
                                        </div>
                                      ) : (
                                        <div className="source-audit-card-body source-audit-missing-body">
                                          <span className="muted">
                                            {isUnmatched ? "Expected but did not match" :
                                             !isExpected ? "Not expected for this position" :
                                             "No data"}
                                          </span>
                                        </div>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>

                              {/* Summary row — uses consistent naming spec.
                                  Mirrors the exact labels from the main table
                                  header so the user can match row→column. */}
                              <div className="source-audit-summary">
                                <span><strong>Rank:</strong> {row.rank ? `#${row.rank}` : "\u2014 (unranked)"} (final ordinal — the engine's opinion)</span>
                                <span><strong>Consensus:</strong> {row.blendedSourceRank?.toFixed(1) ?? "\u2014"} (mean of per-source effective ranks — orthogonal to Rank; gaps reveal blend arbitration)</span>
                                <span><strong>Value:</strong> {val.toLocaleString()} (Hill curve, 1\u20139,999 scale)</span>
                                <span><strong>Confidence:</strong> {confExplain}</span>
                                <span><strong>Edge:</strong> {edge.label} \u2014 {edge.title}</span>
                                {row.sourceRankSpread != null && (
                                  <span><strong>Source spread:</strong> {Math.round(row.sourceRankSpread)} ordinal ranks between the highest and lowest source</span>
                                )}
                                {row.sourceRankPercentileSpread != null && (
                                  <span><strong>Depth-adjusted spread:</strong> {(row.sourceRankPercentileSpread * 100).toFixed(1)}% (accounts for source pool sizes)</span>
                                )}
                                {(row.anomalyFlags || []).length > 0 && (
                                  <span><strong>Flags:</strong> {row.anomalyFlags.join(", ")}</span>
                                )}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
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

"use client";

import { useMemo } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { useApp } from "@/components/AppShell";
import { actionLabel, cautionLabels, isTopRankedForEdgePremium } from "@/lib/edge-helpers";
import { posBadgeClass, confBadgeClass, confBadgeLabel as confLabel, isEligibleForAnalysis } from "@/lib/display-helpers";
import {
  EDGE_SECTION_LIMIT,
  EDGE_PREMIUM_LIMIT,
  EDGE_CAUTION_RANK_LIMIT,
  EDGE_PREMIUM_RANK_LIMIT,
  PREMIUM_SUMMARY_SPREAD,
} from "@/lib/thresholds";
import { getRetailLabel } from "@/lib/dynasty-data";

// ── Edge Page ─────────────────────────────────────────────────────────────
// Source-agreement analysis dashboard. Every signal on this page traces to
// measurable properties of the ranking sources — nothing is predicted.

// ── Section component ─────────────────────────────────────────────────────

function EdgeSection({ title, description, count, accent, children }) {
  const accentMap = {
    green: "rgba(52, 211, 153, 0.12)",
    amber: "rgba(251, 191, 36, 0.10)",
    red: "rgba(248, 113, 113, 0.10)",
    cyan: "rgba(86, 214, 255, 0.08)",
  };
  const borderMap = {
    green: "rgba(52, 211, 153, 0.25)",
    amber: "rgba(251, 191, 36, 0.20)",
    red: "rgba(248, 113, 113, 0.20)",
    cyan: "rgba(86, 214, 255, 0.18)",
  };

  return (
    <div
      className="edge-section"
      style={{
        borderTopColor: borderMap[accent] || "var(--border)",
        background: accentMap[accent] || undefined,
      }}
    >
      <div className="edge-section-header">
        <h3 className="edge-section-title">{title}</h3>
        {count != null && <span className="edge-section-count">{count}</span>}
      </div>
      <p className="edge-section-desc">{description}</p>
      {children}
    </div>
  );
}

// ── Compact table for section rows ────────────────────────────────────────

function SectionTable({ rows, columns, onPlayerClick, emptyText }) {
  if (rows.length === 0) {
    return <p className="muted text-sm" style={{ margin: "8px 0 0" }}>{emptyText || "No matching players."}</p>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} style={c.thStyle}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.name}>
              {columns.map((c) => (
                <td key={c.key} style={c.tdStyle}>{c.render(row, onPlayerClick)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Column definitions ────────────────────────────────────────────────────

const COL_RANK = {
  key: "rank",
  label: "#",
  thStyle: { width: 40, textAlign: "center" },
  tdStyle: { textAlign: "center", fontWeight: 700, color: "var(--cyan)", fontFamily: "var(--mono)" },
  render: (r) => r.rank || "\u2014",
};

const COL_PLAYER = {
  key: "name",
  label: "Player",
  thStyle: {},
  tdStyle: { fontWeight: 600 },
  render: (r, onClick) => (
    <span style={{ cursor: "pointer" }} onClick={() => onClick?.(r)}>
      {r.name}
      {r.team && <span className="muted text-xs" style={{ marginLeft: 4 }}>{r.team}</span>}
    </span>
  ),
};

const COL_POS = {
  key: "pos",
  label: "Pos",
  thStyle: { width: 54 },
  tdStyle: {},
  render: (r) => <span className={posBadgeClass(r)}>{r.pos}</span>,
};

const COL_VALUE = {
  key: "value",
  label: "Value",
  thStyle: { textAlign: "right", width: 70 },
  tdStyle: { textAlign: "right", fontFamily: "var(--mono)" },
  render: (r) => {
    const val = Math.round(r.rankDerivedValue || r.values?.full || 0);
    return val > 0 ? val.toLocaleString() : "\u2014";
  },
};

const COL_SPREAD = {
  key: "spread",
  label: "Spread",
  thStyle: { textAlign: "center", width: 60 },
  tdStyle: { textAlign: "center", fontFamily: "var(--mono)" },
  render: (r) => (r.sourceRankSpread != null ? `\u00B1${r.sourceRankSpread}` : "\u2014"),
};

const COL_GAP_DIR = {
  key: "gap",
  label: "Higher",
  thStyle: { width: 70 },
  tdStyle: { fontSize: "0.78rem" },
  render: (r) => {
    if (r.marketGapDirection === "retail_premium") return <span className="text-cyan">Sell</span>;
    if (r.marketGapDirection === "consensus_premium") return <span className="text-amber">Buy</span>;
    return <span className="muted">\u2014</span>;
  },
};

const COL_CONF = {
  key: "conf",
  label: "Conf",
  thStyle: { textAlign: "center", width: 55 },
  tdStyle: { textAlign: "center" },
  render: (r) => <span className={confBadgeClass(r.confidenceBucket)}>{confLabel(r.confidenceBucket)}</span>,
};

const COL_FLAGS = {
  key: "flags",
  label: "Flags",
  thStyle: { width: 150 },
  tdStyle: { fontSize: "0.76rem", color: "var(--amber)" },
  render: (r) => (r.anomalyFlags || []).slice(0, 2).join(", ") || "\u2014",
};

const COL_SIGNAL = {
  key: "signal",
  label: "Signal",
  thStyle: { width: 160 },
  tdStyle: {},
  render: (r) => {
    const action = actionLabel(r);
    const cautions = cautionLabels(r);
    if (!action && cautions.length === 0) return <span className="muted">\u2014</span>;
    return (
      <>
        {action && <span className={`action-label ${action.css}`} title={action.title}>{action.label}</span>}
        {cautions.map((c) => (
          <span key={c.label} className={`action-label ${c.css}`} title={c.title}>{c.label}</span>
        ))}
      </>
    );
  },
};

// ── Main component ────────────────────────────────────────────────────────

export default function EdgePage() {
  const { loading, error, rows } = useDynastyData();
  const { openPlayerPopup } = useApp();

  // Eligible: non-pick, ranked players
  const eligible = useMemo(
    () => rows.filter(isEligibleForAnalysis),
    [rows],
  );

  // ── Section data ────────────────────────────────────────────────────

  const consensus = useMemo(
    () =>
      eligible
        .filter((r) => r.confidenceBucket === "high" && (r.sourceCount ?? 0) >= 2 && !r.quarantined)
        .sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity))
        .slice(0, EDGE_SECTION_LIMIT),
    [eligible],
  );

  const disagreements = useMemo(
    () =>
      eligible
        .filter((r) => (r.sourceRankSpread ?? 0) > PREMIUM_SUMMARY_SPREAD && (r.sourceCount ?? 0) >= 2 && !r.quarantined)
        .sort((a, b) => (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0))
        .slice(0, EDGE_SECTION_LIMIT),
    [eligible],
  );

  const retailPremium = useMemo(
    () =>
      eligible
        .filter(
          (r) =>
            r.marketGapDirection === "retail_premium" &&
            (r.sourceRankSpread ?? 0) >= PREMIUM_SUMMARY_SPREAD &&
            !r.quarantined &&
            isTopRankedForEdgePremium(r),
        )
        .sort((a, b) => (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0))
        .slice(0, EDGE_PREMIUM_LIMIT),
    [eligible],
  );

  const consensusPremium = useMemo(
    () =>
      eligible
        .filter(
          (r) =>
            r.marketGapDirection === "consensus_premium" &&
            (r.sourceRankSpread ?? 0) >= PREMIUM_SUMMARY_SPREAD &&
            !r.quarantined &&
            isTopRankedForEdgePremium(r),
        )
        .sort((a, b) => (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0))
        .slice(0, EDGE_PREMIUM_LIMIT),
    [eligible],
  );

  const flagged = useMemo(
    () =>
      eligible
        .filter((r) => (r.anomalyFlags || []).length > 0 && (r.rank ?? Infinity) <= EDGE_CAUTION_RANK_LIMIT)
        .sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity))
        .slice(0, EDGE_SECTION_LIMIT),
    [eligible],
  );

  const singleSource = useMemo(
    () =>
      eligible
        .filter((r) => r.isSingleSource && (r.rank ?? Infinity) <= EDGE_CAUTION_RANK_LIMIT)
        .sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity))
        .slice(0, EDGE_SECTION_LIMIT),
    [eligible],
  );

  // ── Summary stats ────────────────────────────────────────────────────
  const stats = useMemo(() => ({
    total: eligible.length,
    multiSource: eligible.filter((r) => (r.sourceCount ?? 0) >= 2).length,
    highConf: eligible.filter((r) => r.confidenceBucket === "high").length,
    disagreementCount: eligible.filter((r) => (r.sourceRankSpread ?? 0) > PREMIUM_SUMMARY_SPREAD && (r.sourceCount ?? 0) >= 2).length,
    flaggedCount: eligible.filter((r) => (r.anomalyFlags || []).length > 0).length,
    singleCount: eligible.filter((r) => r.isSingleSource).length,
  }), [eligible]);

  return (
    <section>
      {/* ── Header ──────────────────────────────────────────────────── */}
      <div className="card">
        <h1 className="page-title">Edge</h1>
        <p className="page-subtitle muted" style={{ marginTop: 4 }}>
          Source agreement signals &mdash; where ranking sources agree, disagree, and flag issues
        </p>
        <p className="text-xs muted" style={{ marginTop: 6, lineHeight: 1.5, maxWidth: 680 }}>
          Every signal on this page is derived from measurable properties of the ranking data:
          how many sources cover a player, how closely they agree, and where they diverge.
          Nothing is predicted or editorialized.
        </p>
      </div>

      {loading && (
        <div className="card loading-state">
          <div className="loading-spinner" />
          <span className="muted text-sm">Loading edge data&hellip;</span>
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
        <>
          {/* ── Summary stats ─────────────────────────────────────── */}
          <div className="card edge-stat-bar">
            <div className="edge-stat">
              <span className="edge-stat-value">{stats.total.toLocaleString()}</span>
              <span className="edge-stat-label">Analyzed</span>
            </div>
            <div className="edge-stat">
              <span className="edge-stat-value text-green">{stats.highConf.toLocaleString()}</span>
              <span className="edge-stat-label">High conf</span>
            </div>
            <div className="edge-stat">
              <span className="edge-stat-value text-green">{stats.multiSource.toLocaleString()}</span>
              <span className="edge-stat-label">Multi-src</span>
            </div>
            <div className="edge-stat">
              <span className="edge-stat-value text-amber">{stats.disagreementCount.toLocaleString()}</span>
              <span className="edge-stat-label">Disagree</span>
            </div>
            <div className="edge-stat">
              <span className="edge-stat-value text-amber">{stats.flaggedCount.toLocaleString()}</span>
              <span className="edge-stat-label">Flagged</span>
            </div>
            <div className="edge-stat">
              <span className="edge-stat-value">{stats.singleCount.toLocaleString()}</span>
              <span className="edge-stat-label">1-source</span>
            </div>
          </div>

          {/* ── Main grid ─────────────────────────────────────────── */}
          <div className="edge-page-grid">
            {/* Consensus Assets */}
            <EdgeSection
              title="Consensus Assets"
              description="Highest-confidence players where both sources agree closely. These are the safest trade anchors."
              count={`${consensus.length} shown`}
              accent="green"
            >
              <SectionTable
                rows={consensus}
                onPlayerClick={openPlayerPopup}
                emptyText="No high-confidence consensus assets found."
                columns={[COL_RANK, COL_PLAYER, COL_POS, COL_VALUE, COL_SPREAD, COL_CONF]}
              />
            </EdgeSection>

            {/* Biggest Disagreements */}
            <EdgeSection
              title="Biggest Disagreements"
              description="Players where ranking sources diverge most. One market may be wrong — which creates opportunity."
              count={`${disagreements.length} shown`}
              accent="amber"
            >
              <SectionTable
                rows={disagreements}
                onPlayerClick={openPlayerPopup}
                emptyText="No significant source disagreements."
                columns={[COL_RANK, COL_PLAYER, COL_POS, COL_SPREAD, COL_GAP_DIR, COL_SIGNAL]}
              />
            </EdgeSection>

            {/* Sell Signals — retail (KTC) values higher than consensus */}
            <EdgeSection
              title="Sell Signals"
              description={`Players the retail market (${getRetailLabel()}) values much higher than the expert consensus. Limited to players inside the top ${EDGE_PREMIUM_RANK_LIMIT} by consensus or ${getRetailLabel()} rank so only trade-relevant gaps surface. Potential sells to retail-first trade partners.`}
              count={`${retailPremium.length} shown`}
              accent="cyan"
            >
              <SectionTable
                rows={retailPremium}
                onPlayerClick={openPlayerPopup}
                emptyText={`No sell signals in the top ${EDGE_PREMIUM_RANK_LIMIT}.`}
                columns={[COL_RANK, COL_PLAYER, COL_POS, COL_SPREAD, COL_VALUE]}
              />
            </EdgeSection>

            {/* Buy Signals — consensus values higher than retail */}
            <EdgeSection
              title="Buy Signals"
              description={`Players the expert consensus values much higher than ${getRetailLabel()}. Limited to players inside the top ${EDGE_PREMIUM_RANK_LIMIT} by consensus or ${getRetailLabel()} rank so only trade-relevant gaps surface. Potential buys from retail-first trade partners.`}
              count={`${consensusPremium.length} shown`}
              accent="cyan"
            >
              <SectionTable
                rows={consensusPremium}
                onPlayerClick={openPlayerPopup}
                emptyText={`No buy signals in the top ${EDGE_PREMIUM_RANK_LIMIT}.`}
                columns={[COL_RANK, COL_PLAYER, COL_POS, COL_SPREAD, COL_VALUE]}
              />
            </EdgeSection>

            {/* Flagged Anomalies */}
            <EdgeSection
              title="Flagged Anomalies"
              description="Ranked players with data quality flags. Not necessarily bad — but worth knowing before trading."
              count={`${flagged.length} shown`}
              accent="red"
            >
              <SectionTable
                rows={flagged}
                onPlayerClick={openPlayerPopup}
                emptyText="No flagged players in top 300."
                columns={[COL_RANK, COL_PLAYER, COL_POS, COL_FLAGS, COL_CONF]}
              />
            </EdgeSection>

            {/* Single-Source Caution */}
            <EdgeSection
              title="Single-Source Players"
              description="Valued by only one ranking source. Confidence is lower and rank could shift significantly if another source adds coverage."
              count={`${singleSource.length} shown`}
              accent="amber"
            >
              <SectionTable
                rows={singleSource}
                onPlayerClick={openPlayerPopup}
                emptyText="No single-source players in top 300."
                columns={[COL_RANK, COL_PLAYER, COL_POS, COL_VALUE, COL_SIGNAL]}
              />
            </EdgeSection>
          </div>
        </>
      )}
    </section>
  );
}

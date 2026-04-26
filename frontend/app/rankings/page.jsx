"use client";

import { Fragment, useMemo, useState, useCallback, useEffect } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { resolvedRank, RANKING_SOURCES, getRetailLabel } from "@/lib/dynasty-data";
import { useSettings } from "@/components/useSettings";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
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
  marketAction,
  isEligibleForBoard,
} from "@/lib/display-helpers";
import HillCurveExplorer from "@/components/graphs/HillCurveExplorer";
import TierGapWaterfall from "@/components/graphs/TierGapWaterfall";
import SourceContributionBars from "@/components/graphs/SourceContributionBars";
import SourceAgreementRadar from "@/components/graphs/SourceAgreementRadar";
import RankChangeGlyph from "@/components/graphs/RankChangeGlyph";
import { PlayerImage } from "@/components/ui";
import { useNews } from "@/components/useNews";

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

// ── Scoring-fit badges ───────────────────────────────────────────────
// Renders next to the value cell when the scoring-fit lens is active
// or the apply-scoring-fit toggle is on.  Three pieces of info:
//
//   * Tier — categorical (elite / starter+ / starter / fringe / below)
//   * Confidence — how robust the underlying estimate is.  ``synthetic``
//     means the value comes from a draft-cohort baseline (rookie), not
//     from realized production.
//   * Delta — the value-scale gap vs the consensus market.  Positive =
//     the league's stacked scoring would value this player higher than
//     consensus does (buy-low candidate).  Negative = the league
//     undervalues vs market (sell-high candidate).
//
// Pure presentational — every value comes from backend stamps.
const _TIER_STYLES = {
  elite:              { label: "Elite",     css: "rankings-tier-elite" },
  starter_plus:       { label: "Starter+",  css: "rankings-tier-starter-plus" },
  starter:            { label: "Starter",   css: "rankings-tier-starter" },
  fringe:             { label: "Fringe",    css: "rankings-tier-fringe" },
  below_replacement:  { label: "Below",     css: "rankings-tier-below" },
  rookie:             { label: "Rookie",    css: "rankings-tier-rookie" },
};

const _CONFIDENCE_STYLES = {
  high:      { label: "High conf",       dot: "var(--green, #4ade80)" },
  medium:    { label: "Medium conf",     dot: "var(--yellow, #facc15)" },
  low:       { label: "Low conf",        dot: "var(--orange, #fb923c)" },
  synthetic: { label: "Rookie cohort",   dot: "var(--cyan, #22d3ee)" },
  none:      { label: "No data",         dot: "var(--muted, #9ca3af)" },
};

function ScoringFitBadges({ tier, confidence, synthetic, draftRound, delta, consensusValue }) {
  const tierMeta = _TIER_STYLES[tier] || _TIER_STYLES.starter;
  const confMeta = _CONFIDENCE_STYLES[confidence] || _CONFIDENCE_STYLES.none;
  const showSynthetic = !!synthetic;
  const deltaNum = typeof delta === "number" && Number.isFinite(delta) ? delta : null;
  const consensus = typeof consensusValue === "number" && Number.isFinite(consensusValue) ? consensusValue : null;

  let deltaTitle = "";
  if (deltaNum != null && consensus != null) {
    const sign = deltaNum > 0 ? "+" : "";
    deltaTitle = `Scoring fit delta vs market: ${sign}${Math.round(deltaNum)} (consensus ${Math.round(consensus)})`;
  }

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, marginLeft: 6 }}>
      <span
        className={`rankings-tier-badge ${tierMeta.css}`}
        title={`Tier from VORP-per-game under your league's scoring`}
        style={{ fontSize: "0.65rem", padding: "1px 5px" }}
      >
        {tierMeta.label}
      </span>
      <span
        title={confMeta.label + (showSynthetic && draftRound != null ? ` (Round ${draftRound})` : "")}
        style={{
          display: "inline-block",
          width: 8,
          height: 8,
          borderRadius: "50%",
          backgroundColor: confMeta.dot,
        }}
      />
      {showSynthetic && (
        <span
          title={draftRound != null
            ? `Estimated from average rookie-year production of round-${draftRound} ${tier}s under your league's scoring`
            : "Synthetic value from draft-cohort baseline"}
          style={{
            fontSize: "0.62rem",
            padding: "1px 4px",
            borderRadius: 3,
            background: "rgba(34, 211, 238, 0.18)",
            color: "var(--cyan, #22d3ee)",
            fontWeight: 600,
          }}
        >
          R{draftRound != null ? draftRound : "?"} synth
        </span>
      )}
      {deltaNum != null && (
        <span
          title={deltaTitle}
          style={{
            fontFamily: "var(--mono, monospace)",
            fontSize: "0.7rem",
            color: deltaNum > 0 ? "var(--green, #4ade80)" : "var(--red, #f87171)",
            fontWeight: 600,
          }}
        >
          {deltaNum > 0 ? "+" : ""}{Math.round(deltaNum)}
        </span>
      )}
    </span>
  );
}

// ── Methodology content ──────────────────────────────────────────────

// ── Source cell formatter ────────────────────────────────────────────
//
// Unified formatting for every per-source cell the rankings table
// renders — both the desktop column cells and the mobile chip strip
// beneath each player row.  Every source (rank-signal or value-based)
// lives on one common 1-9,999 scale in the UI: the backend stamps a
// ``valueContribution`` for every matched source (rank sources route
// through the Hill curve, value sources rescale linearly), and this
// helper renders that number as the primary cell label with the
// effective rank on the shared board shown in parentheses.  Returns:
//
//   hasVal    — true if the source contributed a value for this player
//   primary   — the 9,999-scale ``valueContribution`` for the source
//   rankLabel — the effective rank on the shared board, `#`-prefixed
//   title     — hover tooltip explaining the cell (includes the
//               source's original pre-translation rank when it differs
//               from the effective rank, e.g. rookie / shared-market).
//
// Mirror the display format between desktop and mobile by always
// using this helper so both surfaces show `value (#rank)` consistently.
function formatSourceCell(row, src) {
  const rawVal = row?.canonicalSites?.[src.key];
  // valueContribution is the backend's 9999-scale normalized value
  // (source's top player = 9999, others scale linearly).  For sources
  // whose native value range is already 0-9999 (KTC, IDPTC, DD-SF)
  // this is effectively rawVal; for sources like Yahoo/Boone whose
  // native range is 0-~141, this is the rescaled value so every
  // value column in the UI lives on the same scale.
  const normalizedVal = row?.sourceRankMeta?.[src.key]?.valueContribution;
  // Rank-signal sources stamp a synthetic encoding into canonicalSites
  // (``_RANK_TO_SYNTHETIC_VALUE_OFFSET - rank * 100`` in the backend) that
  // the pipeline uses only for ordering — it is NOT a 1-9,999 contribution.
  // Require a real ``valueContribution`` for those sources so a legacy
  // payload without the stamp shows an honest "\u2014" instead of a
  // six-digit synthetic number mislabeled as a normalized value.
  const hasNormalized =
    normalizedVal != null && Number.isFinite(Number(normalizedVal));
  const hasRaw = rawVal != null && Number.isFinite(Number(rawVal));
  const hasVal = hasNormalized || (!src.isRankSignal && hasRaw);
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

  // Every source renders its 9,999-scale valueContribution as the
  // primary cell label — the same number the blend averages into the
  // final Hill value.  Value-based sources may fall back to the raw
  // site value on legacy payloads that predate the valueContribution
  // stamp (their raw value IS on a monotonic value scale, just not yet
  // rescaled to 9,999); rank-signal sources intentionally do not fall
  // back because their raw canonicalSites entry is a synthetic rank
  // encoding, not a value.
  const displayVal = hasNormalized ? normalizedVal : rawVal;
  const primary = Math.round(Number(displayVal)).toLocaleString();
  const rankLabel = effectiveRank != null ? `#${effectiveRank}` : "\u2014";
  const origRankSuffix =
    origRank != null && origRank !== effectiveRank
      ? `, original rank #${origRank}`
      : "";
  return {
    hasVal: true,
    primary,
    rankLabel,
    title: `${src.displayName}: value ${primary}${
      effectiveRank != null ? `, effective rank #${effectiveRank}` : ""
    }${origRankSuffix}`,
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

function TopMoversRail({ rows, onPlayerClick }) {
  // "Who moved since the last scrape" — sorts ranked rows by the
  // backend-stamped rankChange and surfaces the 5 biggest risers
  // and 5 biggest fallers.  Only renders when we have movement
  // data (first build of a fresh deploy has no prior snapshot, so
  // this silently hides itself).
  const { risers, fallers } = useMemo(() => {
    const withChange = rows.filter(
      (r) => typeof r?.rankChange === "number" && r.rankChange !== 0 && r.rank != null,
    );
    const byDelta = [...withChange].sort(
      (a, b) => Math.abs(b.rankChange) - Math.abs(a.rankChange),
    );
    const ups = byDelta.filter((r) => r.rankChange > 0).slice(0, 5);
    const downs = byDelta.filter((r) => r.rankChange < 0).slice(0, 5);
    return { risers: ups, fallers: downs };
  }, [rows]);

  if (risers.length === 0 && fallers.length === 0) return null;

  const renderSection = (label, items, color, arrow) => (
    <div className="edge-rail-section">
      <h4 className="edge-rail-section-title" style={{ color }}>
        {arrow} {label}
      </h4>
      {items.length === 0 ? (
        <p className="muted text-xs">No movement</p>
      ) : (
        <ul className="edge-rail-list">
          {items.map((row) => (
            <li key={row.name} className="edge-rail-item">
              <span
                className="edge-rail-name"
                onClick={() => onPlayerClick?.(row)}
              >
                #{row.rank} {row.name}
              </span>
              <span className="edge-rail-pos badge">{row.pos}</span>
              <span
                className="edge-rail-detail"
                style={{ color, fontFamily: "var(--mono, monospace)" }}
              >
                {row.rankChange > 0 ? "\u25B2" : "\u25BC"}
                {Math.abs(row.rankChange)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  return (
    <div className="edge-rail">
      <div className="edge-rail-header">
        <h3 className="edge-rail-title">Top Movers</h3>
        <span className="muted text-xs">Biggest rank changes since the previous scrape</span>
      </div>
      <div className="edge-rail-grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
        {renderSection("Risers", risers, "var(--green, #4ade80)", "\u25B2")}
        {renderSection("Fallers", fallers, "var(--red, #f87171)", "\u25BC")}
      </div>
    </div>
  );
}


function EdgeRail({ summary, onPlayerClick, applyScoringFit = false }) {
  const hasSomething =
    summary.retailPremium.length > 0 ||
    summary.consensusPremium.length > 0 ||
    summary.flaggedCautions.length > 0 ||
    summary.consensusAssets.length > 0 ||
    (applyScoringFit && (
      (summary.scoringFitBuys?.length ?? 0) > 0 ||
      (summary.scoringFitSells?.length ?? 0) > 0
    ));

  if (!hasSomething) return null;

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
        {/* Scoring-fit edges only render when the user has the global
            toggle on AND the backend pass produced data.  Surfaces the
            top buy-low / sell-high IDPs by league-aware delta. */}
        {applyScoringFit && (summary.scoringFitBuys?.length ?? 0) > 0 && (
          <EdgeRailSection
            label="League Fit · Buy"
            items={summary.scoringFitBuys}
            emptyText="No league-fit buys"
            onPlayerClick={onPlayerClick}
          />
        )}
        {applyScoringFit && (summary.scoringFitSells?.length ?? 0) > 0 && (
          <EdgeRailSection
            label="League Fit · Sell"
            items={summary.scoringFitSells}
            emptyText="No league-fit sells"
            onPlayerClick={onPlayerClick}
          />
        )}
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
  const { settings, update: updateSetting } = useSettings();
  const [colsMenuOpen, setColsMenuOpen] = useState(false);
  const hiddenSiteCols = settings.hiddenSiteCols || {};
  const visibleSources = useMemo(
    () => RANKING_SOURCES.filter((s) => !hiddenSiteCols[s.key]),
    [hiddenSiteCols]
  );
  const hiddenCount = RANKING_SOURCES.length - visibleSources.length;
  const toggleSiteCol = useCallback((key) => {
    const next = { ...(settings.hiddenSiteCols || {}) };
    if (next[key]) delete next[key];
    else next[key] = true;
    updateSetting("hiddenSiteCols", next);
  }, [settings.hiddenSiteCols, updateSetting]);
  const showAllSiteCols = useCallback(() => {
    updateSetting("hiddenSiteCols", {});
  }, [updateSetting]);
  const { openPlayerPopup } = useApp();
  // IDP gating — when the active league has ``idpEnabled: false``
  // (the new non-IDP league), we strip IDP filter tabs from the
  // pos-filter dropdown and drop IDP rows from the list.  The
  // underlying blended board still lives on the backend; we just
  // don't surface it here.  ``useTeam`` reads the flag off the
  // registry's league config via ``useLeague``.
  const { idpEnabled } = useTeam();
  // Pull recent news so we can stamp a "📰" chip on rows whose
  // player has fresh news / injury status.  Looks up by lowercase
  // name in O(1).  News data is single-flighted at module level so
  // this hook is essentially free for the rankings page.
  const { byPlayer: newsByPlayer } = useNews();
  const [query, setQuery] = useState("");
  const [posFilter, setPosFilter] = useState("all");
  const [confFilter, setConfFilter] = useState("all");
  const [activeLens, setActiveLens] = useState("consensus");
  const [showTiers, setShowTiers] = useState(true);
  const [showEdgeRail, setShowEdgeRail] = useState(true);
  const [rowLimit, setRowLimit] = useState(DEFAULT_ROW_LIMIT);
  const [sortCol, setSortCol] = useState("rank");
  const [sortAsc, setSortAsc] = useState(true);
  const [copyStatus, setCopyStatus] = useState("");
  const [showMethodology, setShowMethodology] = useState(false);
  const [expandedRow, setExpandedRow] = useState(null);

  // ── Apply Scoring Fit toggle ────────────────────────────────────
  // Sourced from global settings so toggling on /rankings is visible
  // immediately on /trade (Trade Calculator), Trade Suggestions, and
  // any other consumer of player values.  When ON, IDP rows substitute
  // ``idpScoringFitAdjustedValue`` for ``rankDerivedValue`` everywhere.
  const applyScoringFit = !!settings.applyScoringFit;
  const setApplyScoringFit = useCallback((next) => {
    updateSetting("applyScoringFit", !!next);
  }, [updateSetting]);

  const handleSort = useCallback((col) => {
    if (sortCol === col) {
      setSortAsc((prev) => !prev);
    } else {
      setSortCol(col);
      setSortAsc(["rank", "name", "pos"].includes(col));
    }
  }, [sortCol]);

  // If the user is viewing an IDP-only filter and then switches to
  // a league that disables IDP, snap back to "all" so the board
  // doesn't render empty.  Runs every render but only commits a
  // state change when the filter is actually stale.
  useEffect(() => {
    if (!idpEnabled && (posFilter === "idp" || posFilter === "DL" || posFilter === "LB" || posFilter === "DB")) {
      setPosFilter("all");
    }
  }, [idpEnabled, posFilter]);

  // Seed ``posFilter`` from the URL query string on first load.  Lets
  // the per-position drill-down routes (e.g. /rankings/qb) deep-link
  // into a pre-filtered view.  Recognised values mirror the dropdown
  // options: all / offense / idp / pick / rookie / rookie:QB / QB /
  // RB / WR / TE / DL / LB / DB.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const requested = (params.get("pos") || "").trim();
    if (!requested) return;
    const normalized = ["all", "offense", "idp", "pick", "rookie"].includes(requested.toLowerCase())
      ? requested.toLowerCase()
      : requested.toUpperCase();
    setPosFilter(normalized);
    // Run once on mount only — subsequent filter changes go through
    // the dropdown.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  // ── Base eligible list ──────────────────────────────────────────
  // ``idpEnabled=false`` drops every IDP row from the board.  The
  // rankings pipeline still blends IDP sources globally, but non-IDP
  // leagues don't render any IDP rows, tabs, or summary counts —
  // nothing the user of a non-IDP league can trade.
  const eligibleRaw = useMemo(() => {
    const filtered = rows.filter(isEligibleForBoard);
    if (!idpEnabled) {
      return filtered.filter((r) => r?.assetClass !== "idp");
    }
    return filtered;
  }, [rows, idpEnabled]);

  // ── Apply Scoring Fit transform ─────────────────────────────────
  // When the toggle is ON: every IDP row that has an
  // ``idpScoringFitAdjustedValue`` substitutes that for its
  // ``rankDerivedValue``, and the entire board is re-sorted by the
  // adjusted values to assign a fresh rank.
  //
  // Offense rows pass through unchanged — they have no scoring-fit
  // adjustment.  This mutation is local to the rankings page; trade
  // engines, edge rail, and any other consumer of ``rankDerivedValue``
  // continue to see the consensus value.
  //
  // Whether at least one row actually carries an adjusted value also
  // controls visibility of the "Apply Scoring Fit" toggle button —
  // hidden when the backend pass didn't run for this league.
  const hasScoringFitAvailable = useMemo(
    () => eligibleRaw.some(
      (r) => typeof r.idpScoringFitDelta === "number"
              && Number.isFinite(r.idpScoringFitDelta),
    ),
    [eligibleRaw],
  );

  // Single source of truth for the slider weight — falls back to 0.30
  // (the recommended default) when the saved settings predate the
  // scoringFitWeight field.  Clamped to [0, 1] so any future code
  // path that mutates the value can't break downstream math.
  const scoringFitWeight = Math.max(
    0,
    Math.min(1,
      typeof settings.scoringFitWeight === "number"
        ? settings.scoringFitWeight : 0.30,
    ),
  );

  const eligible = useMemo(() => {
    if (!applyScoringFit || !hasScoringFitAvailable || scoringFitWeight <= 0) {
      return eligibleRaw;
    }
    // Project every row to a working copy with displayValue/displayRank
    // overlay.  The ORIGINAL ``rankDerivedValue`` is preserved so the
    // PlayerPopup / trade calculator (when invoked from this page) can
    // still surface the consensus number alongside the adjusted one.
    //
    // Adjusted value is recomputed from primitives
    // (``consensus + delta × scoringFitWeight``) so the slider on
    // /settings re-renders the board without a backend round-trip.
    const projected = eligibleRaw.map((r) => {
      const consensus = Number(r.rankDerivedValue) || 0;
      const delta = Number(r.idpScoringFitDelta);
      const adjusted = (Number.isFinite(delta) && consensus > 0)
        ? Math.max(0, Math.min(9999, consensus + delta * scoringFitWeight))
        : null;
      const displayValue = adjusted ?? consensus;
      return {
        ...r,
        // Preserve originals for tooltip / debug surfaces.
        consensusRankDerivedValueOriginal: r.rankDerivedValue,
        consensusRankOriginal: r.canonicalConsensusRank,
        // Swap the working values + ranks so existing sort/display
        // pipelines (resolvedRank, sort by "value", etc.) pick up the
        // adjusted numbers without further plumbing.
        rankDerivedValue: displayValue,
        // Also overlay values.full so the rendered table cell follows
        // the toggle without a separate code path.
        values: {
          ...(r.values || {}),
          full: displayValue,
        },
      };
    });
    // Re-rank by descending adjusted value, breaking ties on the
    // original consensus rank (stable order for offense rows that
    // didn't move).
    const ranked = [...projected].sort((a, b) => {
      const va = Number(a.rankDerivedValue) || 0;
      const vb = Number(b.rankDerivedValue) || 0;
      if (vb !== va) return vb - va;
      return (a.consensusRankOriginal ?? Infinity) - (b.consensusRankOriginal ?? Infinity);
    });
    // Stamp 1-N ranks in the new order; only stamp on rows that
    // currently carry a canonicalConsensusRank — picks-suppressed rows
    // and any other unranked rows stay unranked.  Also overwrite the
    // ``rank`` field (set in buildRows from canonicalConsensusRank) so
    // every existing renderer / sort path picks up the new order
    // without further plumbing.
    let nextRank = 0;
    for (const r of ranked) {
      if (r.consensusRankOriginal != null) {
        nextRank += 1;
        r.canonicalConsensusRank = nextRank;
        r.rank = nextRank;
      }
    }
    return ranked;
  }, [eligibleRaw, applyScoringFit, hasScoringFitAvailable, scoringFitWeight]);

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

  // ── Per-position scoring-fit summary ─────────────────────────────
  // When the user has the global toggle on, summarise how each IDP
  // position group's average ``idpScoringFitDelta`` compares to the
  // consensus.  Surfaces "your league overvalues LBs by avg +1200,
  // undervalues EDGEs by -800, aligned on DBs" — the one-shot
  // insight that tells the user where their league diverges most.
  const scoringFitPositionSummary = useMemo(() => {
    if (!applyScoringFit || !hasScoringFitAvailable) return null;
    const buckets = new Map();
    for (const r of eligibleRaw) {
      if (r.assetClass !== "idp") continue;
      const delta = Number(r.idpScoringFitDelta);
      if (!Number.isFinite(delta)) continue;
      // Group by abstract family — combines specific positions
      // (DT/DE/EDGE → DL, etc.) so the user sees three rows, not
      // ten.  Matches the cohort-aliasing in the rookie baseline.
      const family = (
        ({
          "DL": "DL", "DT": "DL", "DE": "DL", "EDGE": "DL", "NT": "DL",
          "LB": "LB", "ILB": "LB", "OLB": "LB", "MLB": "LB",
          "DB": "DB", "CB": "DB", "S": "DB", "FS": "DB", "SS": "DB",
        })[String(r.pos || "").toUpperCase()] || "Other"
      );
      if (family === "Other") continue;
      if (!buckets.has(family)) buckets.set(family, []);
      buckets.get(family).push(delta);
    }
    const out = [];
    for (const [family, deltas] of buckets) {
      if (!deltas.length) continue;
      const sorted = [...deltas].sort((a, b) => a - b);
      const median = sorted[Math.floor(sorted.length / 2)];
      const avg = deltas.reduce((s, x) => s + x, 0) / deltas.length;
      out.push({
        family,
        count: deltas.length,
        avg: Math.round(avg),
        median: Math.round(median),
        positive: deltas.filter((d) => d > 0).length,
      });
    }
    out.sort((a, b) => Math.abs(b.avg) - Math.abs(a.avg));
    return out.length ? out : null;
  }, [eligibleRaw, applyScoringFit, hasScoringFitAvailable]);

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
            // Sort by the same 9,999-scale ``valueContribution`` the cell
            // renders, so the column order always matches the displayed
            // numbers.  Rank-signal sources with shared-market / rookie
            // translation re-order between their original and effective
            // rank; reading ``canonicalSites`` here would sort on the
            // pre-translation synthetic encoding and produce a ranking
            // that disagrees with the values in the column.
            //
            // Fall back to ``canonicalSites`` only for value-based
            // sources on legacy payloads that predate the
            // ``valueContribution`` stamp — their raw slot is on a
            // monotonic value scale, so the sort still matches what
            // ``formatSourceCell`` renders in that legacy branch.  For
            // rank-signal sources the raw slot is a synthetic rank
            // encoding the cell intentionally refuses to render, so
            // reading it here would reorder rows whose visible cells
            // are all "—" — sort order the user cannot interpret.
            const src = RANKING_SOURCES.find((s) => s.key === key);
            const aMeta = Number(a.sourceRankMeta?.[key]?.valueContribution);
            const bMeta = Number(b.sourceRankMeta?.[key]?.valueContribution);
            const allowRawFallback = !src?.isRankSignal;
            va = Number.isFinite(aMeta)
              ? aMeta
              : allowRawFallback
                ? Number(a.canonicalSites?.[key]) || 0
                : 0;
            vb = Number.isFinite(bMeta)
              ? bMeta
              : allowRawFallback
                ? Number(b.canonicalSites?.[key]) || 0
                : 0;
            return (va - vb) * dir;
          }
          return resolvedRank(a) - resolvedRank(b);
        }
      }
    });
    return sorted;
  }, [eligible, activeLens, posFilter, confFilter, query, sortCol, sortAsc]);

  // Apply row limit — search/filter bypasses the limit
  const hasActiveFilter = query || posFilter !== "all" || confFilter !== "all" || activeLens !== "consensus" || applyScoringFit;
  const displayRows = hasActiveFilter ? ranked : ranked.slice(0, rowLimit);
  const hasMore = !hasActiveFilter && ranked.length > rowLimit;

  // Per-position ranks (QB3, RB5, LB2…).  Computed from the
  // ``eligible`` board sorted by ``row.rank`` ASCENDING — independent
  // of the user's current sort/filter so badges don't renumber when
  // the user sorts by name or filters to a single position.
  //
  // When ``applyScoringFit`` is on, the ``eligible`` projection has
  // already overwritten ``row.rank`` with the adjusted-value-based
  // rank, so iterating in rank order gives position ranks that
  // reflect the league-aware ordering: a fit-positive LB that
  // bubbled to LB3 (from consensus LB12) shows "LB3" in its badge.
  const positionRankByName = useMemo(() => {
    const counts = new Map();
    const byName = new Map();
    const sorted = [...eligible].sort(
      (a, b) => (a?.rank ?? Infinity) - (b?.rank ?? Infinity),
    );
    for (const row of sorted) {
      const pos = String(row?.pos || "").toUpperCase();
      if (!pos || !row?.name) continue;
      const next = (counts.get(pos) || 0) + 1;
      counts.set(pos, next);
      byName.set(row.name, next);
    }
    return byName;
  }, [eligible]);

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

  // Same columns as ``copyValues`` but emits a proper comma-separated
  // CSV with RFC-4180 quoting and triggers a browser download instead
  // of a clipboard write.  Used by the "Export CSV" button.
  function exportCsv() {
    const sourceHeaders = RANKING_SOURCES.flatMap((src) => [
      src.columnLabel,
      `${src.columnLabel} Rank`,
    ]);
    const headers = [
      "Rank", "Player", "Pos", "Team", "Tier", "Value", "Value Band",
      "Confidence", "Action", "Sources",
      ...sourceHeaders,
    ];
    const escape = (cell) => {
      const s = cell == null ? "" : String(cell);
      if (/[",\n\r]/.test(s)) {
        return `"${s.replace(/"/g, '""')}"`;
      }
      return s;
    };
    const lines = [headers.map(escape).join(",")];
    displayRows.forEach((row) => {
      const val = Math.round(row.rankDerivedValue || row.values?.full || 0);
      const band = valueBand(val);
      const action = actionLabel(row);
      const cautions = cautionLabels(row);
      const actionStr = [action?.label, ...cautions.map((c) => c.label)]
        .filter(Boolean).join("; ");
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
        ].map(escape).join(",")
      );
    });
    const csv = lines.join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const iso = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const a = document.createElement("a");
    a.href = url;
    a.download = `brisket-rankings-${iso}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setCopyStatus(`Exported ${displayRows.length.toLocaleString()} rows`);
    setTimeout(() => setCopyStatus(""), 1800);
  }

  // ── Freshness timestamp ────────────────────────────────────────────
  const freshness = rawData?.dataFreshness;
  const timestamp = freshness?.generatedAt || rawData?.date || null;

  // Relative-time formatter for the "Updated" footer.  Matches the
  // stale-banner's formatAgo — keeps humans honest about staleness
  // without having to parse ISO timestamps in their head.
  const relativeUpdated = useMemo(() => {
    if (!timestamp) return null;
    try {
      const then = new Date(timestamp);
      const now = new Date();
      const secs = Math.round((now.getTime() - then.getTime()) / 1000);
      if (!Number.isFinite(secs)) return null;
      if (secs < 60) return `${secs}s ago`;
      if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
      if (secs < 86_400) return `${Math.round(secs / 3600)}h ago`;
      const days = Math.round(secs / 86_400);
      return `${days}d ago`;
    } catch {
      return null;
    }
  }, [timestamp]);

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
            className={`button ${showMethodology ? "button-primary" : ""}`}
            onClick={() => setShowMethodology((v) => !v)}
          >
            {showMethodology ? "Hide methodology" : "How this works"}
          </button>
          <button className="button" onClick={copyValues} title="Copy the current rows as TSV for pasting into a spreadsheet">
            Copy
          </button>
          <button className="button" onClick={exportCsv} title="Download the current rows as a CSV file">
            Export CSV
          </button>
          {/* Columns toggle — opens an inline popover with a master
              on/off for the per-source columns plus one checkbox per
              source so the user can hide clutter from sources they
              don't care about.  Persisted across sessions via
              ``settings.showSiteCols`` (master gate) and
              ``settings.hiddenSiteCols`` (per-source). */}
          <div style={{ position: "relative", display: "inline-block" }}>
            <button
              className="button"
              onClick={() => setColsMenuOpen((v) => !v)}
              title="Show/hide per-source columns"
            >
              Columns
              {!settings.showSiteCols
                ? " (off)"
                : hiddenCount > 0
                  ? ` (${hiddenCount} hidden)`
                  : ""}
            </button>
            {colsMenuOpen && (
              <div
                className="rankings-columns-popover"
                style={{
                  position: "absolute",
                  top: "calc(100% + 4px)",
                  /* Keep the popover anchored to the button's right
                     edge on desktop; the narrow-viewport override in
                     globals.css flips anchoring so the popover cannot
                     overflow off-screen on mobile. */
                  right: 0,
                  minWidth: 260,
                  maxHeight: 400,
                  overflowY: "auto",
                  background: "var(--panel-bg, #1a1e2a)",
                  border: "1px solid var(--border, #2e3442)",
                  borderRadius: 6,
                  padding: "8px 12px",
                  fontSize: "0.85rem",
                  zIndex: 30,
                  boxShadow: "0 4px 16px rgba(0,0,0,0.4)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <strong>Source columns</strong>
                  <button
                    className="button button-small"
                    onClick={showAllSiteCols}
                    style={{ fontSize: "0.7rem", padding: "2px 8px" }}
                    title="Restore all source columns"
                    disabled={!settings.showSiteCols}
                  >
                    Show all
                  </button>
                </div>
                {/* Master on/off — flips the global gate that renders
                    the per-source value columns on desktop and the
                    per-row chip strip on mobile.  Without this toggle
                    the per-source checkboxes below would be silent
                    no-ops for cold-start users, since the default for
                    ``showSiteCols`` is off. */}
                <label
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "6px 0",
                    borderBottom: "1px solid var(--border-dim, rgba(255,255,255,0.08))",
                    marginBottom: 4,
                    cursor: "pointer",
                    fontWeight: 600,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={Boolean(settings.showSiteCols)}
                    onChange={(e) => updateSetting("showSiteCols", e.target.checked)}
                  />
                  <span>Show source columns</span>
                </label>
                {RANKING_SOURCES.map((src) => {
                  const hidden = Boolean(hiddenSiteCols[src.key]);
                  const rowDisabled = !settings.showSiteCols;
                  return (
                    <label
                      key={src.key}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        padding: "4px 0",
                        cursor: rowDisabled ? "not-allowed" : "pointer",
                        opacity: rowDisabled ? 0.45 : 1,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={!hidden}
                        onChange={() => toggleSiteCol(src.key)}
                        disabled={rowDisabled}
                      />
                      <span>{src.columnLabel}</span>
                      <span className="muted" style={{ marginLeft: "auto", fontSize: "0.72rem" }}>{src.displayName}</span>
                    </label>
                  );
                })}
              </div>
            )}
          </div>
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
              <span
                className="rankings-trust-label"
                title={`Data generated at ${timestamp}`}
              >
                Last scraped {relativeUpdated || timestamp}
              </span>
            </div>
          )}
        </div>
      )}

      {/* ── Methodology (expandable) ────────────────────────────────── */}
      {showMethodology && (
        <>
          <MethodologySection />
          <div className="card" style={{ padding: "var(--space-md)" }}>
            <h3 className="section-title">Hill curve</h3>
            <p className="text-xs muted" style={{ marginTop: 4, marginBottom: "var(--space-sm)" }}>
              Percentile → Hill value mapping with the live board overlaid as dots.
              The curve is the canonical rank-to-value shape; dots are where every
              rankable player actually lands after per-source aggregation.
            </p>
            <HillCurveExplorer
              rows={rows}
              curves={rawData?.hillCurves}
              onPointClick={openPlayerPopup}
            />
          </div>
          <div className="card" style={{ padding: "var(--space-md)" }}>
            <h3 className="section-title">Tier gap waterfall</h3>
            <p className="text-xs muted" style={{ marginTop: 4, marginBottom: "var(--space-sm)" }}>
              Top-120 descending value curve with inter-row gap bars overlaid.
              Tall gap bars mark tier cliffs — those are the natural tier boundaries
              the canonical engine detects via rolling-median gap analysis.
            </p>
            <TierGapWaterfall rows={rows} topN={120} />
          </div>
        </>
      )}

      {/* ── Top movers rail (auto-hides when no movement data) ─────── */}
      {!loading && !error && rows.length > 0 && (
        <TopMoversRail rows={ranked} onPlayerClick={openPlayerPopup} />
      )}

      {/* ── Edge rail (expandable) ──────────────────────────────────── */}
      {!loading && !error && showEdgeRail && rows.length > 0 && (
        <EdgeRail summary={edgeSummary} onPlayerClick={openPlayerPopup} applyScoringFit={applyScoringFit && hasScoringFitAvailable} />
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
          {/* Lens tabs.  ``scoringFit`` is conditionally hidden until
              the ``idp_scoring_fit`` backend flag actually stamps
              fields on at least one row — otherwise the button shows
              an empty board for offense-only leagues / when the flag
              is off, which is just confusing UX. */}
          <div className="sub-nav" style={{ marginTop: "var(--space-sm)", display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px" }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
              {LENSES
                .filter((lens) =>
                  lens.key !== "scoringFit"
                  || rows.some((r) => typeof r.idpScoringFitDelta === "number"
                                       && Number.isFinite(r.idpScoringFitDelta))
                )
                .map((lens) => (
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
            {/* Apply Scoring Fit toggle.  Only rendered when at least
                one row has ``idpScoringFitAdjustedValue`` stamped (i.e.
                the backend pass actually ran for this league).  When
                the user toggles, the entire board re-sorts instantly
                and IDP rows show the adjusted value instead of the
                consensus value. */}
            {hasScoringFitAvailable && (
              <button
                className={`sub-nav-btn ${applyScoringFit ? "active" : ""}`}
                onClick={() => setApplyScoringFit(!applyScoringFit)}
                title={applyScoringFit
                  ? "Showing IDP values adjusted by your league's scoring fit. Click to revert to the consensus board."
                  : "Adjust IDP values + ranks by how this league's stacked scoring rates each player vs the consensus market. Toggles instantly — does not affect the trade calculator."}
                style={{ marginLeft: "auto" }}
              >
                {applyScoringFit ? "✓ Scoring Fit applied" : "Apply Scoring Fit"}
              </button>
            )}
          </div>

          {/* Lens description */}
          {activeLens !== "consensus" && (
            <p className="muted text-xs" style={{ margin: "4px 0 8px", lineHeight: 1.4 }}>
              {currentLens.description}
            </p>
          )}

          {/* Apply-Scoring-Fit explainer banner + per-position summary.
              The banner surfaces only when the toggle is ON so first-run
              users understand what changed about the board before the
              lens cells make sense.  The position summary below it
              shows where the league diverges most from the consensus —
              one-shot insight that tells the user "your league
              overvalues X, undervalues Y." */}
          {applyScoringFit && (
            <div
              className="muted text-xs"
              style={{
                margin: "4px 0 8px",
                padding: "6px 10px",
                lineHeight: 1.4,
                borderLeft: "3px solid var(--cyan, #22d3ee)",
                background: "rgba(34, 211, 238, 0.08)",
                borderRadius: "3px",
              }}
            >
              IDP values + ranks are adjusted by your league&apos;s scoring
              fit (weight {Math.round(scoringFitWeight * 100)}% — change on{" "}
              <a href="/settings" style={{ color: "var(--cyan)" }}>/settings</a>).
              Cyan dot = rookie cohort estimate. Trade calculator,
              suggestions, finder + buy/sell signals all respect this toggle.
            </div>
          )}
          {applyScoringFit && scoringFitPositionSummary && (
            <div
              style={{
                margin: "4px 0 8px",
                padding: "6px 10px",
                background: "rgba(20, 25, 36, 0.5)",
                border: "1px solid var(--border)",
                borderRadius: "3px",
                display: "flex",
                gap: 16,
                flexWrap: "wrap",
                alignItems: "center",
                fontSize: "0.74rem",
              }}
              title="Mean per-position scoring-fit delta across all IDPs in this league.  Positive = your league overvalues these vs consensus market (more buy-low candidates).  Negative = market overpays."
            >
              <strong style={{ color: "var(--text)" }}>League fit by position:</strong>
              {scoringFitPositionSummary.map((b) => (
                <span key={b.family} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontWeight: 600 }}>{b.family}</span>
                  <span
                    style={{
                      fontFamily: "var(--mono, monospace)",
                      color: b.avg > 0 ? "var(--green, #4ade80)"
                        : b.avg < 0 ? "var(--red, #f87171)"
                        : "var(--muted)",
                      fontWeight: 600,
                    }}
                    title={`Avg delta ${b.avg >= 0 ? "+" : ""}${b.avg} across ${b.count} ${b.family}s · ${b.positive} fit-positive`}
                  >
                    {b.avg >= 0 ? "+" : ""}{b.avg.toLocaleString()}
                  </span>
                  <span className="muted">({b.count})</span>
                </span>
              ))}
            </div>
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
              {idpEnabled && <option value="idp">IDP</option>}
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
                {idpEnabled && <option value="DL">DL</option>}
                {idpEnabled && <option value="LB">LB</option>}
                {idpEnabled && <option value="DB">DB</option>}
              </optgroup>
            </select>
            {/* Confidence filter and Tiers toggle — previously hidden
                on mobile, now exposed so mobile users can access them.
                On a 390 px viewport they wrap to a second row of the
                filter bar (.filter-bar already has flex-wrap). */}
            <select className="select" value={confFilter} onChange={(e) => setConfFilter(e.target.value)}>
              {CONFIDENCE_FILTERS.map((f) => (
                <option key={f.key} value={f.key}>{f.label}</option>
              ))}
            </select>
            <button
              className={`button ${showTiers ? "button-primary" : ""}`}
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
                  {settings.showSiteCols && visibleSources.map((src) => (
                    <SortHeader
                      key={src.key}
                      col={`src:${src.key}`}
                      style={{ textAlign: "right", width: 90 }}
                      className="hide-mobile rankings-source-col"
                      title={`${src.displayName} — cell shows the source's 1\u20139,999 scale value (${
                        src.isRankSignal ? "Hill curve from this source's ordinal rank" : "linear rescale of this source's native trade value"
                      }) with its effective rank on the shared board in parentheses.`}
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
                  const newsItem = newsByPlayer.get(String(row.name || "").toLowerCase());
                  const chips = rowChips(row, { newsItem });
                  const val = Math.round(row.rankDerivedValue || row.values?.full || 0);
                  const band = valueBand(val);
                  const tier = tierLabel(row);
                  const tierId = effectiveTierId(row);
                  // Structured market edge descriptor (never returns null).
                  // Replaces the legacy marketGapLabel(row) string which
                  // caused the Gap column to show an ambiguous dash.
                  const edge = marketEdge(row);
                  // Trader-facing collapse of edge → BUY/SELL/HOLD.  This
                  // is what renders in the Edge column header.  The
                  // detailed `edge.label` (e.g. "Experts higher by 12")
                  // remains available in the row's expanded audit panel.
                  const action_ = marketAction(row);
                  const isQuarantined = row.quarantined;
                  const action = actionLabel(row);
                  const cautions = cautionLabels(row);
                  const isExpanded = expandedRow === row.name;
                  // Column count drives the tier-separator and audit-panel
                  // colspans.  It tracks the render gate on
                  // ``settings.showSiteCols`` so the separator stretches
                  // cleanly whether or not per-source columns are visible.
                  const totalCols = 10 + (settings.showSiteCols ? visibleSources.length : 0);

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
                        {/* Rank + rank-change indicator.  Positive
                            change = moved up since last scrape (green
                            ▲N); negative = moved down (red ▼N);
                            null = new / previously unranked. */}
                        <td style={{ textAlign: "center", fontWeight: 700, color: "var(--cyan)", fontFamily: "var(--mono)" }}>
                          {row.rank || "\u2014"}
                          {row.rankChange != null && row.rankChange !== 0 && (
                            <span
                              className="rankings-rank-change"
                              title={`Moved ${row.rankChange > 0 ? "up" : "down"} ${Math.abs(row.rankChange)} since the previous scrape`}
                              style={{
                                marginLeft: 4,
                                fontSize: "0.68rem",
                                fontWeight: 600,
                                color: row.rankChange > 0 ? "var(--green, #4ade80)" : "var(--red, #f87171)",
                              }}
                            >
                              {row.rankChange > 0 ? "\u25B2" : "\u25BC"}
                              {Math.abs(row.rankChange)}
                            </span>
                          )}
                        </td>

                        {/* Tier */}
                        <td className="hide-mobile">
                          <span className={`rankings-tier-badge ${tierCssClass}`}>{tier}</span>
                        </td>

                        {/* Player: headshot, name, context, chips */}
                        <td>
                          <div className="rankings-player-cell">
                            <PlayerImage
                              playerId={row.raw?.playerId}
                              team={row.team}
                              position={row.pos}
                              name={row.name}
                              size={28}
                            />
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
                            <RankChangeGlyph
                              history={row.rankHistory}
                              change={row.rankChange}
                            />
                            {/* ``rankHistory`` is reserved for a future per-
                                player time series; until it's stamped, the
                                glyph falls back to the single-delta arrow on
                                ``rankChange``, or renders nothing. */}
                            {chips.length > 0 && (
                              <span className="rankings-chips">
                                {chips.map((c) => (
                                  <span key={c.label} className={`badge ${c.css} rankings-chip`} title={c.title}>{c.label}</span>
                                ))}
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Position + position rank (QB3, RB5, LB2…).
                            Position rank is computed from the full
                            ``ranked`` order at render-time so search/filter
                            doesn't renumber badges. */}
                        <td>
                          <span className={posBadgeClass(row)}>
                            {row.pos}
                            {positionRankByName.get(row.name) != null && (
                              <span
                                className="rankings-pos-rank"
                                style={{
                                  marginLeft: 4,
                                  opacity: 0.85,
                                  fontFamily: "var(--mono, monospace)",
                                  fontSize: "0.78em",
                                }}
                                title={`${row.pos}${positionRankByName.get(row.name)} — position rank within the full ranked board`}
                              >
                                {positionRankByName.get(row.name)}
                              </span>
                            )}
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
                            users can hover to see what the letter means.
                            Value is clickable and opens the player popup
                            with the full per-source breakdown so you can
                            see exactly which sources contributed to this
                            number.

                            When ``Apply Scoring Fit`` is active OR the
                            user is on the Scoring Fit lens, IDP rows
                            also render two badges:

                            * a confidence dot (high / medium / low /
                              synthetic) — how robust the underlying
                              VORP estimate is
                            * a tier badge (elite / starter+ / starter /
                              fringe / below) — categorical translation
                              of the VORP-per-game

                            For synthetic rows (rookies built from
                            cohort baselines), the confidence dot reads
                            "rookie cohort" so the user knows the value
                            is a draft-capital estimate, not realized
                            production. */}
                        <td style={{ textAlign: "right" }} title={`Hill-curve value ${val.toLocaleString()} (scale 1\u20139,999) — click to see per-source breakdown`}>
                          <span
                            className="rankings-value rankings-value-clickable"
                            onClick={(e) => { e.stopPropagation(); openPlayerPopup?.(row); }}
                            style={{ cursor: "pointer", textDecoration: "underline dotted transparent", textUnderlineOffset: "3px" }}
                            onMouseEnter={(e) => { e.currentTarget.style.textDecorationColor = "currentColor"; }}
                            onMouseLeave={(e) => { e.currentTarget.style.textDecorationColor = "transparent"; }}
                          >
                            {val.toLocaleString()}
                          </span>
                          <span
                            className={`rankings-value-band ${band.css}`}
                            title={band.title || "Value band"}
                          >
                            {band.label}
                          </span>
                          {(applyScoringFit || activeLens === "scoringFit") && row.idpScoringFitTier && (
                            <ScoringFitBadges
                              tier={row.idpScoringFitTier}
                              confidence={row.idpScoringFitConfidence}
                              synthetic={row.idpScoringFitSynthetic}
                              draftRound={row.idpScoringFitDraftRound}
                              delta={row.idpScoringFitDelta}
                              consensusValue={row.consensusRankDerivedValueOriginal ?? row.rankDerivedValue}
                            />
                          )}
                        </td>

                        {/* Per-source value + rank columns.  Gated on
                            `showSiteCols` so power users can collapse the
                            source columns to focus on the Value column.
                            Each cell shows the source's 9,999-scale
                            valueContribution with the effective rank on
                            the shared board in parentheses — unified
                            single-line format so every source sits on
                            the same value scale. */}
                        {settings.showSiteCols && visibleSources.map((src) => {
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

                        {/* Market edge — collapsed to BUY/SELL/HOLD.
                            BUY = experts > market (undervalued).
                            SELL = market > experts (overvalued).
                            HOLD = aligned within threshold.
                            "—" = insufficient data to compare.
                            Tooltip surfaces the detailed gap. */}
                        <td className="hide-mobile" style={{ textAlign: "center" }}>
                          <span className={`edge-label ${action_.css}`} title={action_.title}>
                            {action_.label}
                          </span>
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
                          below each player row — but only when the
                          user has tapped the row to expand it.
                          Rendering the strip under every row by
                          default dominated the mobile viewport and
                          pushed the headline Value column off-screen
                          for cold-start users carrying the legacy
                          ``showSiteCols: true`` localStorage value.
                          Gating on ``isExpanded`` makes the source
                          audit on-demand on mobile.  ``showSiteCols``
                          still governs the desktop per-source column
                          render — desktop behavior is unchanged.

                          Uses a dedicated `.rankings-mobile-source-row`
                          class (not the global `.mobile-only` helper)
                          so we can set `display: table-row` on mobile
                          — the global helper resolves to
                          `display: initial !important`, which would
                          force the <tr> to `inline` and break the
                          table layout. */}
                      {isExpanded && (
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

                              {/* ── Visual source contribution + agreement ──
                                  Two compact graphs side-by-side so the
                                  aggregation is legible at a glance: bars
                                  rank per-source contributions (with any
                                  Hampel-dropped sources struck through); the
                                  radar shows agreement/disagreement shape. */}
                              <div
                                style={{
                                  display: "grid",
                                  gridTemplateColumns: "minmax(280px, 1fr) minmax(220px, 260px)",
                                  gap: "var(--space-md)",
                                  alignItems: "center",
                                  marginTop: "var(--space-sm)",
                                }}
                              >
                                <div>
                                  <div className="muted text-xs" style={{ marginBottom: 4 }}>
                                    Per-source value contribution
                                  </div>
                                  <SourceContributionBars
                                    row={row}
                                    labelFor={(k) =>
                                      RANKING_SOURCES.find((s) => s.key === k)?.columnLabel || k
                                    }
                                  />
                                </div>
                                <div>
                                  <div className="muted text-xs" style={{ marginBottom: 4 }}>
                                    Source agreement
                                  </div>
                                  <SourceAgreementRadar
                                    row={row}
                                    labelFor={(k) =>
                                      RANKING_SOURCES.find((s) => s.key === k)?.columnLabel || k
                                    }
                                  />
                                </div>
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

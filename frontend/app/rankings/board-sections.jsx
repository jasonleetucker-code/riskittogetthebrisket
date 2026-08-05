"use client";

/**
 * board-sections.jsx — display sections of the rankings board (R2).
 *
 * Methodology, the two signal rails (Top Movers / Edge Summary), the
 * expanded per-row source-audit panel, and the mobile source strip.
 * All data derivations live in the page / lib helpers — these render
 * backend stamps verbatim (no ranking math client-side).
 */
import { Icon, Panel } from "@/components/ds";
import { RANKING_SOURCES } from "@/lib/dynasty-data";
import SourceContributionBars from "@/components/graphs/SourceContributionBars";
import SourceAgreementRadar from "@/components/graphs/SourceAgreementRadar";
import styles from "./board.module.css";

const srcLabel = (key) =>
  RANKING_SOURCES.find((s) => s.key === key)?.columnLabel || key;

// ── Methodology ──────────────────────────────────────────────────────
//
// Everything version-specific here is READ FROM THE CONTRACT, never
// duplicated. This panel used to hardcode
//
//     value = max(1, min(9999, round(1 + 9998 / (1 + ((rank-1)/45)^1.10))))
//
// which was wrong twice over: the constants (45 / 1.10) were the
// retired rank-form pair, and the live pipeline does not use rank form
// at all — it uses the percentile-form Hill with per-scope masters.
// Measured against the real board on the pinned 2026-07-30 payload,
// the displayed formula was off by a MEDIAN of 805 points across 740
// ranked rows (p90 1060, max 1185).
//
// The same panel published "spread <= 30 / <= 80" for confidence, the
// legacy absolute-ordinal rule, while the board decides on percentile
// spread — 31.9% of bucketed rows contradicted it.
//
// The contract already publishes both correctly under `methodology`,
// so the mirror is deleted rather than corrected: a duplicated constant
// with a comment is how the rank-form pair drifted in the first place.
// When the payload has no methodology block we omit the line entirely —
// showing nothing beats showing a number that disagrees with the board.
export function MethodologySection({ methodology } = {}) {
  const sourceNames = RANKING_SOURCES.map((s) => s.displayName).join(", ");
  const formula = methodology?.formula;
  const buckets = methodology?.confidenceBuckets;
  // What the board does NOT know, straight from the contract — never a
  // mirrored constant, for the reason the formula line above was
  // deleted. Rendered only while the contract says the values are not
  // scored under the league's own settings, so it disappears by itself
  // the day that changes (W27-F012).
  const idpFormat = methodology?.idpTranslation?.formatSensitivity;
  const idpUnscored = idpFormat && idpFormat.scoredUnderLeagueSettings === false;
  return (
    <ol className={styles.methodologyList}>
      <li><strong>Source ingestion</strong> — Raw values from {sourceNames}.</li>
      <li><strong>Per-source ranking</strong> — Each player ranked within each source by raw value (highest = rank 1).</li>
      <li><strong>Rank normalization</strong> — Per-source ranks converted to 1–9,999 values via Hill-curve formula so sources are comparable.</li>
      <li><strong>Blended ranking</strong> — Multi-source players get averaged normalized values. Single-source players keep their one value.</li>
      <li><strong>Unified sort</strong> — All players sorted by blended value into one board. Top 800 get a consensus rank.</li>
      <li><strong>Tier detection</strong> — Natural value clusters detected via gap analysis. Tier breaks appear where adjacent players have unusually large value gaps.</li>
      <li>
        <strong>Confidence scoring</strong>
        {buckets ? (
          <> — High = {buckets.high}. Medium = {buckets.medium}. Low = {buckets.low}.</>
        ) : (
          <> — multi-source agreement, measured on the backend&rsquo;s spread signal.</>
        )}
      </li>
      <li><strong>Identity validation</strong> — Post-ranking pass checks for entity resolution problems. Flagged rows are quarantined (confidence degraded, not removed).</li>
      {idpUnscored ? (
        <li>
          <strong>IDP values are format-generic</strong> — {idpFormat.description}
        </li>
      ) : null}
      {formula?.expression ? (
        <li className={styles.methodologyFormula}>
          {formula.name ? `${formula.name}: ` : null}
          {formula.expression}
          {formula.referenceN ? ` (referenceN = ${formula.referenceN})` : null}
        </li>
      ) : null}
    </ol>
  );
}

// ── Signal rails ─────────────────────────────────────────────────────
function RailList({ items, emptyText, onPlayerClick, detailFor }) {
  if (items.length === 0) return <p className={styles.railEmpty}>{emptyText}</p>;
  return (
    <ul className={styles.railList}>
      {items.map((item) => {
        const row = item.row || item;
        const detail = detailFor(item);
        return (
          <li key={row.name} className={styles.railItem}>
            <button
              type="button"
              className={`button-reset ${styles.railName}`}
              onClick={() => onPlayerClick?.(row)}
            >
              #{item.rank ?? row.rank} {row.name}
            </button>
            <span className="badge">{row.pos}</span>
            {detail}
          </li>
        );
      })}
    </ul>
  );
}

export function TopMoversRail({ risers, fallers, onPlayerClick }) {
  if (risers.length === 0 && fallers.length === 0) return null;
  const delta = (row) => (
    <span
      className={`ds-movement ${row.rankChange > 0 ? "ds-movement--up" : "ds-movement--down"} ${styles.railDetail}`}
      title={`Moved ${row.rankChange > 0 ? "up" : "down"} ${Math.abs(row.rankChange)} since the previous scrape`}
    >
      <Icon name={row.rankChange > 0 ? "arrow-up" : "arrow-down"} size={10} />
      {Math.abs(row.rankChange)}
    </span>
  );
  return (
    <Panel
      dense
      title="Top movers"
      subtitle="Biggest rank changes since the previous scrape"
    >
      <div className={styles.railGrid2}>
        <div>
          <h4 className={styles.railTitle}>Risers</h4>
          <RailList
            items={risers}
            emptyText="No movement"
            onPlayerClick={onPlayerClick}
            detailFor={delta}
          />
        </div>
        <div>
          <h4 className={styles.railTitle}>Fallers</h4>
          <RailList
            items={fallers}
            emptyText="No movement"
            onPlayerClick={onPlayerClick}
            detailFor={delta}
          />
        </div>
      </div>
    </Panel>
  );
}

export function EdgeRail({ summary, onPlayerClick }) {
  const hasSomething =
    summary.retailPremium.length > 0 ||
    summary.consensusPremium.length > 0 ||
    summary.flaggedCautions.length > 0 ||
    summary.consensusAssets.length > 0;
  if (!hasSomething) return null;

  const sections = [
    { label: "Sell signals", items: summary.retailPremium, empty: "No sell signals" },
    { label: "Buy signals", items: summary.consensusPremium, empty: "No buy signals" },
    { label: "Consensus assets", items: summary.consensusAssets, empty: "No high-confidence consensus assets" },
    { label: "Flagged — needs caution", items: summary.flaggedCautions, empty: "No flagged players in top 300" },
  ];
  return (
    <Panel
      dense
      title="Edge summary"
      subtitle="Derived from source agreement data — not predictions"
    >
      <div className={styles.railGrid4}>
        {sections.map((section) => (
          <div key={section.label}>
            <h4 className={styles.railTitle}>{section.label}</h4>
            <RailList
              items={section.items}
              emptyText={section.empty}
              onPlayerClick={onPlayerClick}
              detailFor={(item) => (
                <span className={styles.railDetail}>{item.detail}</span>
              )}
            />
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ── Expanded row: mobile source strip ────────────────────────────────
// Desktop shows one column per source; below the md breakpoint those
// columns hide (ds-col-hide-md), so the expanded row renders the same
// value (#rank) pairs as a chip strip — one format, both surfaces
// (formatSourceCell).
export function MobileSourceStrip({ row, formatSourceCell }) {
  return (
    <div className={styles.mobileSources}>
      {RANKING_SOURCES.map((src) => {
        const cell = formatSourceCell(row, src);
        return (
          <span
            key={src.key}
            className={`${styles.mobileSourceChip}${cell.hasVal ? "" : ` ${styles.mobileSourceChipEmpty}`}`}
            title={cell.title}
          >
            <span className={styles.mobileSourceLabel}>{src.columnLabel}</span>
            <span className={styles.mobileSourceVal}>
              {cell.hasVal ? (
                <>
                  {cell.primary}
                  <span className={styles.mobileSourceRank}> ({cell.rankLabel})</span>
                </>
              ) : (
                "—"
              )}
            </span>
          </span>
        );
      })}
    </div>
  );
}

// ── Expanded row: source audit panel ─────────────────────────────────
// Renders backend audit stamps verbatim. Keeps the legacy
// ``source-audit-*`` classes (globals.css) — the panel's internal
// grid/badge styling is unchanged in R2; the R5 CSS purge migrates it.
export function SourceAuditPanel({ row, val, edge, confExplain }) {
  const audit = row.sourceAudit || row.raw?.sourceAudit || {};
  return (
    <div className="source-audit-panel">
      <div className="source-audit-header">
        <strong>Source Audit: {row.name}</strong>
        <span className="muted" style={{ marginLeft: 12 }}>
          {audit.reason === "fully_matched" ? "All expected sources matched" :
           audit.reason === "structurally_single_source" ? "Only one source structurally covers this player" :
           audit.reason === "matching_failure_other_sources_eligible" ? "Matching failure — expected source(s) did not match" :
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
                        ? `#${origRk != null ? origRk : "—"}`
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

      {/* Visual source contribution + agreement */}
      <div className={styles.auditGraphs}>
        <div>
          <div className={styles.auditGraphLabel}>Per-source value contribution</div>
          <SourceContributionBars row={row} labelFor={srcLabel} />
        </div>
        <div>
          <div className={styles.auditGraphLabel}>Source agreement</div>
          <SourceAgreementRadar row={row} labelFor={srcLabel} />
        </div>
      </div>

      {/* Summary row — mirrors the main table header labels */}
      <div className="source-audit-summary">
        <span><strong>Rank:</strong> {row.rank ? `#${row.rank}` : "— (unranked)"} (final ordinal — the engine&apos;s opinion)</span>
        <span><strong>Consensus:</strong> {row.blendedSourceRank?.toFixed(1) ?? "—"} (mean of per-source effective ranks — orthogonal to Rank; gaps reveal blend arbitration)</span>
        <span><strong>Value:</strong> {val.toLocaleString()} (Hill curve, 1–9,999 scale)</span>
        <span><strong>Confidence:</strong> {confExplain}</span>
        <span><strong>Edge:</strong> {edge.label} — {edge.title}</span>
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
  );
}

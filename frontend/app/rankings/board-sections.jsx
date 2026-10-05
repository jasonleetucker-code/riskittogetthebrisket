"use client";

/**
 * board-sections.jsx — display sections of the rankings board (R2).
 *
 * Methodology, the two signal rails (Top Movers / Edge Summary), the
 * expanded per-row source-audit panel, and the mobile source strip.
 * All data derivations live in the page / lib helpers — these render
 * backend stamps verbatim (no ranking math client-side).
 */
import {
  Icon,
  Panel,
  PlayerNameButton,
  canonicalPlayerId,
} from "@/components/ds";
import { RANKING_SOURCES } from "@/lib/dynasty-data";
import { formatHours, rowAuthority } from "@/lib/value-explainers";
import SourceContributionBars from "@/components/graphs/SourceContributionBars";
import SourceAgreementRadar from "@/components/graphs/SourceAgreementRadar";
import { sourceObservation, withheldReasonText } from "./board-utils";
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
//
// 2026-09-29: the confidence line read `methodology.confidenceBuckets`,
// a key the contract stopped publishing when B11 replaced the spread
// rule with the five-axis gate (`methodology.confidenceGate`). Every
// board therefore took the fallback, which still described the RETIRED
// spread signal. It now names the gate's axes from the contract. The
// plain-language explanation of each step lives in
// lib/value-explainers.js, rendered beside this list.
export function MethodologySection({ methodology, sourceWeighting } = {}) {
  const sourceNames = RANKING_SOURCES.map((s) => s.displayName).join(", ");
  const formula = methodology?.formula;
  const gate = methodology?.confidenceGate;
  const axisNames = gate?.axes ? Object.keys(gate.axes) : [];
  const rankLimit = Number(methodology?.overallRankLimit);
  const weighting = sourceWeighting?.formula;
  return (
    <ol className={styles.methodologyList}>
      <li>
        <strong>Source ingestion</strong> — Dynasty values and ranks from{" "}
        {sourceNames}. KTC Market is a benchmark and never one of them.
      </li>
      <li>
        <strong>Shared rank scale</strong> — Each source&rsquo;s rank for the
        player is placed on one shared scale; position-only IDP lists are first
        translated onto the full IDP board.
      </li>
      <li>
        <strong>Rank to value</strong> — Rank-based sources are converted to
        1–9,999 values through the Hill curve; the value-based markets (KTC
        Crowd, KTC Trades, IDP Trade Calculator) are rescaled directly.
      </li>
      <li>
        <strong>Weighting</strong> — Each vote is weighted by how fresh, healthy
        and complete its source is
        {weighting ? <> ({weighting})</> : null}; correlated boards from one
        provider family share one vote.
      </li>
      <li>
        <strong>Blend</strong> — Outliers are filtered, then a count-aware
        weighted mean-median combines the votes. IDP players and picks blend
        toward an anchor market; offense uses a flat blend. A player backed by
        one evidence family keeps 30% of the blend.
      </li>
      <li>
        <strong>Unified sort</strong> — Every asset is sorted by value into one
        board
        {Number.isFinite(rankLimit) && rankLimit > 0 ? (
          <>; the top {rankLimit.toLocaleString()} receive an official rank.</>
        ) : (
          "."
        )}
      </li>
      <li>
        <strong>Tier detection</strong> — Natural value clusters detected via
        gap analysis. Tier breaks appear where adjacent players have unusually
        large value gaps.
      </li>
      <li>
        <strong>Confidence</strong>
        {axisNames.length > 0 ? (
          <>
            {" "}
            — Graded on {axisNames.join(", ")}; the overall level is the weakest
            of them.
          </>
        ) : (
          <>
            {" "}
            — Graded by the backend evidence checks; the overall level is the
            weakest of them.
          </>
        )}
      </li>
      <li>
        <strong>Identity validation</strong> — Post-ranking pass checks for
        entity resolution problems. Flagged rows are quarantined (confidence
        degraded, not removed).
      </li>
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
            {/* #1337: canonical Player File link when the row carries a
                playerId; picks (no id) keep the quick-view button. */}
            <PlayerNameButton
              name={row.name}
              row={row}
              playerId={canonicalPlayerId(row)}
              onOpen={onPlayerClick}
              className={`${styles.resetButton} ${styles.railName}`}
            >
              #{item.rank ?? row.rank} {row.name}
            </PlayerNameButton>
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
                  <span className={styles.mobileSourceRank}>
                    {" "}
                    ({cell.rankLabel})
                  </span>
                </>
              ) : (
                "—"
              )}
            </span>
            {cell.observation && (
              <span
                className={styles.mobileSourceRank}
                data-testid={`source-observation-${src.key}`}
              >
                {cell.observation.voting === false
                  ? `${cell.observation.voteLabel || "not voting"} · `
                  : ""}
                {cell.observation.basis === "VALUE"
                  ? `native ${cell.observation.nativeValue.toLocaleString()}`
                  : "rank fallback"}
                {cell.observation.rankLabel
                  ? ` · ${cell.observation.rankLabel}`
                  : ""}
                {cell.observation.asOf
                  ? ` · ${String(cell.observation.asOf).slice(0, 10)}`
                  : ""}
                {cell.observation.shadow?.wouldContribute != null
                  ? ` · would contribute ${Number(
                      cell.observation.shadow.wouldContribute,
                    ).toLocaleString()}`
                  : ""}
              </span>
            )}
          </span>
        );
      })}
    </div>
  );
}

// ── Expanded row: source audit panel ─────────────────────────────────
// Renders backend audit stamps verbatim.
//
// 2026-09-29 (C8-U2): moved off the legacy ``source-audit-*`` classes in
// globals.css onto this module's tokens. Those classes carry the retired
// dark terminal palette (a translucent slate row background, muted grey
// labels at 0.66rem, 6px cards), so on the PSI editorial page the
// expanded row rendered as a dark slab: 283 axe color-contrast nodes at
// 1366px and 217 at 390px on the populated board, and card text
// ("Not expected for this position", ``csv_combined_cross_market``)
// overflowed its column. The legacy selectors stay in globals.css until
// their last consumer is proven gone (this panel no longer uses them).
function auditReasonText(reason) {
  if (reason === "fully_matched") return "All expected sources matched";
  if (reason === "structurally_single_source") return "Only one source structurally covers this player";
  if (reason === "matching_failure_other_sources_eligible") return "Matching failure — expected source(s) did not match";
  if (reason === "partial_coverage") return "Some expected sources missing";
  if (reason === "no_source_match") return "No source matched";
  return reason || "";
}

function AuditField({ label, children }) {
  return (
    <div className={styles.auditField}>
      <span className={styles.auditLabel}>{label}</span>
      <span className={styles.auditVal}>{children}</span>
    </div>
  );
}

export function SourceAuditPanel({ row, rawData, val, edge, confidence }) {
  const audit = row.sourceAudit || row.raw?.sourceAudit || {};
  const authority = rowAuthority(row);
  return (
    <div className={styles.auditPanel}>
      <div className={styles.auditHeader}>
        <strong>Source Audit: {row.name}</strong>
        <span className={styles.auditReason}>{auditReasonText(audit.reason)}</span>
        {audit.allowlistReason && (
          <span className={styles.auditAllowlist} title="Allowlisted reason">
            {audit.allowlistReason}
          </span>
        )}
      </div>

      {/* Per-source detail grid */}
      <div className={styles.auditGrid}>
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
          const status = isMatched ? "matched" : isUnmatched ? "missing" : isExpected ? "expected" : "n/a";
          const freshness = Number(meta?.freshness);
          // Signals (owner addendum 2026-10-03): native value vs rank
          // fallback, the DERIVED value-ordered rank, dataset, format and
          // as-of — all backend stamps (board-utils.sourceObservation).
          const observation = sourceObservation(row, src, rawData);

          return (
            <div
              key={src.key}
              className={`${styles.auditCard}${hasVal ? "" : ` ${styles.auditCardMissing}`}`}
            >
              <div className={styles.auditCardHeader}>
                <strong>{src.columnLabel}</strong>
                <span className={styles.auditStatus} data-status={status}>
                  {status}
                </span>
              </div>
              {hasVal ? (
                <div className={styles.auditCardBody}>
                  {observation ? (
                    <>
                      {observation.voteLabel && (
                        <AuditField label="Vote">
                          {observation.voteLabel}
                        </AuditField>
                      )}
                      {observation.voteExplanation && (
                        <AuditField label="Why">
                          {observation.voteExplanation}
                        </AuditField>
                      )}
                      {observation.family && (
                        <AuditField label="Family">
                          {observation.family}
                        </AuditField>
                      )}
                      {observation.shadow && (
                        <AuditField label="Shadow">
                          {observation.shadow.withheldReason
                            ? `withheld — ${withheldReasonText(observation.shadow.withheldReason)}`
                            : `${observation.family || ""}${
                                observation.shadow.familyRank ?? "?"
                              } → shared-market #${observation.shadow.translatedRank} · would contribute ${Number(
                                observation.shadow.wouldContribute,
                              ).toLocaleString()}`}
                        </AuditField>
                      )}
                      {observation.familyNote && (
                        <AuditField label="Family cap">
                          {observation.familyNote}
                        </AuditField>
                      )}
                      {observation.excludedReason && (
                        <AuditField label="Excluded">
                          {observation.excludedReason}
                        </AuditField>
                      )}
                      <AuditField label="Basis">
                        {observation.basis === "VALUE"
                          ? "VALUE (native value)"
                          : "RANK fallback"}
                      </AuditField>
                      {observation.nativeValue != null && (
                        <AuditField label="Native value">
                          {observation.nativeValue.toLocaleString()}
                        </AuditField>
                      )}
                      {observation.rankLabel && (
                        <AuditField label="Signals rank">{observation.rankLabel}</AuditField>
                      )}
                      <AuditField label="Dataset">{observation.dataset}</AuditField>
                      {observation.format && (
                        <AuditField label="Format">{observation.format}</AuditField>
                      )}
                      <AuditField label="As of">
                        {observation.asOf
                          ? `${String(observation.asOf).slice(0, 10)}${
                              observation.state ? ` · ${observation.state}` : ""
                            }`
                          : "unknown"}
                      </AuditField>
                    </>
                  ) : (
                    <AuditField label={src.isRankSignal ? "Rank" : "Value"}>
                      {src.isRankSignal
                        ? `#${origRk != null ? origRk : "—"}`
                        : Math.round(Number(siteVal)).toLocaleString()}
                    </AuditField>
                  )}
                  {eRank != null && <AuditField label="Eff. rank">#{eRank}</AuditField>}
                  {meta?.valueContribution != null && (
                    <AuditField label="Hill value">{meta.valueContribution.toLocaleString()}</AuditField>
                  )}
                  {/* `effectiveWeight` is the depth-scaled coverage
                      DIAGNOSTIC (declared x min(1, depth/60)). The
                      contract says so in as many words — "never applied
                      to the blend" (data_contract.py) — and
                      docs/open-modeling-decisions.md decision #1 is the
                      measured call NOT to apply it. The number that IS
                      applied is `appliedWeight`, so show that one first
                      and mark the other as diagnostic. */}
                  {meta?.appliedWeight != null && (
                    <AuditField label="Weight (applied)">{meta.appliedWeight}</AuditField>
                  )}
                  {/* Row-level content freshness — stamped only when it
                      reduced this source's weight on this row. */}
                  {Number.isFinite(freshness) && (
                    <AuditField label="Freshness">
                      ×{freshness.toFixed(2)}
                      {formatHours(meta?.freshnessAgeHours)
                        ? ` · ${formatHours(meta.freshnessAgeHours)} old`
                        : ""}
                    </AuditField>
                  )}
                  {meta?.effectiveWeight != null && (
                    <AuditField label="Coverage wt (diagnostic)">{meta.effectiveWeight}</AuditField>
                  )}
                  {meta?.method && <AuditField label="Method">{meta.method}</AuditField>}
                  {matchDetail?.matchedName && (
                    <AuditField label="Matched as">{matchDetail.matchedName}</AuditField>
                  )}
                  {matchDetail?.via && <AuditField label="Via">{matchDetail.via}</AuditField>}
                </div>
              ) : (
                <p className={styles.auditMissing}>
                  {isUnmatched ? "Expected but did not match" :
                   !isExpected ? "Not expected for this position" :
                   "No data"}
                </p>
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
      <div className={styles.auditSummary}>
        <span><strong>Rank:</strong> {row.rank ? `#${row.rank}` : "— (unranked)"} (final ordinal — the engine&apos;s opinion)</span>
        <span><strong>Consensus:</strong> {row.blendedSourceRank?.toFixed(1) ?? "—"} (mean of per-source effective ranks — a diagnostic; the rank comes from the blended value)</span>
        <span><strong>Value:</strong> {val.toLocaleString()} (1–9,999 scale)</span>
        <span><strong>Confidence:</strong> {confidence?.label || "—"}</span>
        {authority?.retained != null && (
          <span>
            <strong>Source authority:</strong> {Math.round(authority.retained * 100)}% retained
            {authority.stateLabel ? ` (${authority.stateLabel})` : ""}
          </span>
        )}
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
      {confidence?.reasons?.length > 0 && (
        <ul className={styles.auditReasons} aria-label="Why this confidence">
          {confidence.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

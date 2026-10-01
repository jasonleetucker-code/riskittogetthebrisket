"use client";

/**
 * ValueExplain — the rendering half of lib/value-explainers.js.
 *
 * Rankings and the Player File both explain the same value, so the
 * explanation is ONE set of components over ONE copy module rather than
 * two pages each paraphrasing the methodology. Progressive disclosure,
 * built on the existing ds primitives:
 *
 *   <ExplainTip>          short answer beside the number (ds InfoTip)
 *   <ValueExplainHelp>    the long form, every question in order (ds HelpModal)
 *   <ConfidenceEvidence>  one row's confidence: label, basis, checks, reasons
 *   <SourceFreshnessList> one row's sources: weight here, content age, last fetch
 *   <BoardClocks>         "board built … from the scrape of …"
 *
 * The backend's per-player explanation (value-explain/v2: estimator,
 * attribution, leave-one-out, per-source clocks and exclusions) renders in
 * ValueExplainDetail.jsx, lazily loaded by the Player File.
 *
 * Display only: every number is a backend stamp selected by the lib
 * helpers. Nothing here computes a value, rank, confidence or freshness.
 */
import React from "react";
import { HelpModal, InfoTip } from "@/components/ds";
import {
  VALUE_EXPLAINERS,
  VALUE_EXPLAINER_ORDER,
  CONFIDENCE_AXIS_LABELS,
  SOURCE_FRESHNESS_STATE_LABELS,
  boardClocks,
  confidenceDisplay,
  formatAgo,
  formatHours,
  rowAuthority,
  rowSourceFreshness,
} from "@/lib/value-explainers";
import styles from "./value-explain.module.css";

/** Short explanation for one topic, as a tappable InfoTip. */
export function ExplainTip({ topic, label, side = "bottom", className = "" }) {
  const entry = VALUE_EXPLAINERS[topic];
  if (!entry) return null;
  return (
    // Plain text, not a <p>: the tip sits inside headings, stat labels
    // and paragraphs, where a block child is invalid nesting.
    <InfoTip label={label || entry.title} side={side} className={className}>
      {entry.short}
    </InfoTip>
  );
}

function rankLimitOf(methodology) {
  const n = Number(methodology?.overallRankLimit);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/**
 * Every explainer section, in reading order. Contract-published
 * parameters (the rank limit) are read here rather than restated in the
 * copy, so the prose cannot drift from the board.
 */
export function ValueExplainerSections({ methodology, topics = VALUE_EXPLAINER_ORDER }) {
  const rankLimit = rankLimitOf(methodology);
  return (
    <>
      {topics.map((topic) => {
        const entry = VALUE_EXPLAINERS[topic];
        if (!entry) return null;
        return (
          <section key={topic} aria-labelledby={`value-explain-${topic}`}>
            <h3 id={`value-explain-${topic}`}>{entry.title}</h3>
            <p>{entry.short}</p>
            {entry.detail.map((para) => (
              <p key={para.slice(0, 40)}>{para}</p>
            ))}
            {topic === "rankVsValue" && rankLimit ? (
              <p>
                On this board the top {rankLimit.toLocaleString()} receive an official rank.
              </p>
            ) : null}
            <p className={styles.owner}>Methodology source: {entry.owner}</p>
          </section>
        );
      })}
    </>
  );
}

/** "How values work" button + dialog. `children` append page-specific detail. */
export function ValueExplainHelp({
  methodology,
  label = "How values work",
  title = "How player values work",
  children,
  className = "",
}) {
  return (
    <HelpModal title={title} label={label} className={className}>
      <ValueExplainerSections methodology={methodology} />
      {children}
    </HelpModal>
  );
}

const AXIS_LEVEL_LABELS = { high: "High", medium: "Medium", low: "Low", none: "None" };

/** One row's confidence, with the checks and reasons the backend stamped. */
export function ConfidenceEvidence({ row }) {
  const c = confidenceDisplay(row);
  const axes = c.axes
    ? Object.keys(CONFIDENCE_AXIS_LABELS).filter((k) => c.axes[k] != null)
    : [];
  return (
    <div className={styles.evidence}>
      <div className={styles.evidenceLabel}>
        {/* No second tip here: the Confidence tile directly above already
            carries it, and two "What is confidence?" buttons on one page
            would share an accessible name. */}
        <span className={styles.level} data-level={c.level}>
          {c.label}
        </span>
      </div>
      {c.basisNote ? <p className={styles.muted}>{c.basisNote}</p> : null}
      {axes.length > 0 ? (
        <dl className={styles.axes}>
          {axes.map((k) => (
            <div key={k} className={styles.axis}>
              <dt>{CONFIDENCE_AXIS_LABELS[k]}</dt>
              <dd data-level={c.axes[k]}>{AXIS_LEVEL_LABELS[c.axes[k]] || c.axes[k]}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {c.reasons.length > 0 ? (
        <ul className={styles.reasons}>
          {c.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      ) : c.level === "none" ? (
        <p className={styles.muted}>{VALUE_EXPLAINERS.missingConfidence.short}</p>
      ) : null}
    </div>
  );
}

function formatInstant(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function formatWeight(n) {
  if (n == null) return null;
  return n >= 0.995 ? "1" : n.toFixed(2);
}

/** Board-level clocks: when the board was built, and from which scrape. */
export function BoardClocks({ rawData, className = "", tip = true }) {
  const { builtAt, scrapedAt } = boardClocks(rawData);
  const built = formatAgo(builtAt);
  const scraped = formatAgo(scrapedAt);
  if (!built && !scraped) return null;
  return (
    <span className={`${styles.clocks} ${className}`.trim()}>
      <span title={builtAt || undefined}>Board built {built || "at an unknown time"}</span>
      {scraped ? (
        <span title={scrapedAt || undefined}> · from the scrape of {scraped}</span>
      ) : (
        <span> · scrape time not published</span>
      )}
      {tip ? (
        <ExplainTip topic="freshness" label="data freshness" side="top" className="ds-infotip--end" />
      ) : null}
    </span>
  );
}

/**
 * One row's sources with the weight each carried HERE and the two clocks
 * behind it. A source stale enough to stop voting is listed as such —
 * present in the list, absent from the value, never shown as zero.
 */
export function SourceFreshnessList({ row, rawData }) {
  const items = rowSourceFreshness(row, rawData);
  const authority = rowAuthority(row);
  if (items.length === 0) {
    return (
      <p className={styles.muted}>
        No source freshness is published for this asset.
      </p>
    );
  }
  return (
    <div className={styles.freshness}>
      {authority && authority.retained != null ? (
        <p className={styles.authority}>
          This value keeps {Math.round(authority.retained * 100)}% of its sources&rsquo; normal
          authority
          {authority.stateLabel ? ` — ${authority.stateLabel.toLowerCase()}` : ""}.
          {authority.dominantLabel && authority.dominantShare != null
            ? ` Largest single share: ${authority.dominantLabel}, ${Math.round(authority.dominantShare * 100)}%.`
            : ""}
        </p>
      ) : null}
      {items.some((s) => !s.excluded && !s.rowDetailAvailable) ? (
        <p className={styles.muted}>
          This lighter data view carries each source&rsquo;s applied weight but not its
          per-player freshness factor or outlier flag, so those are not shown here.
        </p>
      ) : null}
      <ul className={styles.sourceList}>
        {items.map((s) => {
          const contentAt = formatInstant(s.contentAsOf);
          const age = formatHours(s.boardAgeHours);
          const fetched = formatAgo(s.lastFetchedAt);
          const reduced = s.rowFreshness != null && s.rowFreshness < 0.995;
          return (
            <li key={s.key} className={styles.sourceItem} data-voting={s.voting ? "true" : "false"}>
              <div className={styles.sourceLine}>
                <span className={styles.sourceName}>{s.label}</span>
                <span className={styles.sourceWeight}>
                  {s.excluded
                    ? "not voting — stale or unhealthy source"
                    : s.outlierDropped
                      ? "dropped as an outlier"
                      : s.appliedWeight != null
                        ? `weight ${formatWeight(s.appliedWeight)}${s.baseWeight != null ? ` of ${formatWeight(s.baseWeight)}` : ""}${reduced ? ` · freshness ×${s.rowFreshness.toFixed(2)} here` : ""}`
                        : "weight not published"}
                </span>
              </div>
              <div className={styles.sourceMeta}>
                {/* Board-level facts about the SOURCE; the weight above is
                    this player's. Batch-style sources age per row, so the
                    two can differ. */}
                <span>{"Source: "}</span>
                {s.boardState ? (
                  <span data-state={s.boardState}>
                    {SOURCE_FRESHNESS_STATE_LABELS[s.boardState] || s.boardState}
                  </span>
                ) : (
                  <span>freshness not measured</span>
                )}
                {s.familyShared ? <span> · shares one vote with its provider family</span> : null}
                <span>
                  {" · content as of "}
                  {contentAt ? `${contentAt}${age ? ` (${age} old)` : ""}` : "unknown"}
                </span>
                <span>{" · last fetched "}{fetched || "unknown"}</span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

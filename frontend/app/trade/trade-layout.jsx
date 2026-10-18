"use client";

/**
 * trade-layout.jsx — the TC-D workspace pieces of /trade (D1).
 *
 * The page is laid out in five layers (docs/trade/TRADE_CALCULATOR_UX_AUDIT.md
 * §7, TC-D in the completion workstream):
 *
 *   1. Trade Builder            #trade-builder
 *   2. Immediate Result         #trade-result     (raw, VA, adjusted, the meter)
 *   3. Final Decision           #trade-decision   (the War Room; echoed here)
 *   4. Supporting Intelligence  #trade-intelligence
 *   5. Ideas & tools            #trade-tools
 *
 * Desktop (>= 1024): two columns, layers 2 + the decision echo sticky on the
 * right.  Below 1024: one column in that order, a section nav, and the
 * persistent verdict bar (the tray) that links to the decision.
 *
 * PURE PRESENTATION, like ./trade-sections.jsx: totals come from
 * lib/trade-logic (`adjustedSideTotals`), the decision is the War Room's
 * `POST /api/trade/analyze` answer, verbatim.  Nothing here computes a value,
 * a band or a recommendation.
 */

import { Badge, DataTable } from "@/components/ds";
import { DECISION_TONES } from "@/lib/trade-war-room";
import styles from "./trade.module.css";

/** Anchors of the five layers, in reading order. */
export const TRADE_LAYERS = [
  { id: "trade-builder", label: "Build" },
  { id: "trade-result", label: "Result" },
  { id: "trade-decision", label: "Decision" },
  { id: "trade-intelligence", label: "Evidence" },
  { id: "trade-tools", label: "Tools" },
];

/** Contextual section navigation (below 1024 px; hidden on the desktop workspace). */
export function TradeSectionNav() {
  return (
    <nav className={styles.sectionNav} aria-label="Trade sections">
      {TRADE_LAYERS.map((layer) => (
        <a key={layer.id} href={`#${layer.id}`} className={styles.sectionNavLink}>
          {layer.label}
        </a>
      ))}
    </nav>
  );
}

const rounded = (v) => Math.round(Number(v)).toLocaleString();

/**
 * Layer 2's package table for a two-team trade: raw, Value Adjustment and the
 * adjusted total per side, straight from `sideTotals` (adjusted = raw + VA,
 * nothing else), on the DataTable primitive.  VA is the difference of the
 * rounded figures, the same rule the side cards use, so the visible parts
 * always add up; no VA reads as a dash, never "+0".  The gap and the band are
 * the meter's, directly below — not repeated here.
 */
export function ImmediateResultTable({ sides, sideTotals }) {
  const totals = [sideTotals[0], sideTotals[1]];
  if (sides.length < 2 || totals.some((t) => !t)) return null;
  const va = (t) =>
    t.adjustment > 0 ? `+${(Math.round(t.adjusted) - Math.round(t.raw)).toLocaleString()}` : "—";
  const rows = [
    { id: "raw", measure: "Raw", a: rounded(totals[0].raw), b: rounded(totals[1].raw) },
    { id: "va", measure: "Value Adjustment", a: va(totals[0]), b: va(totals[1]) },
    {
      id: "adjusted",
      measure: "Adjusted",
      a: rounded(totals[0].adjusted),
      b: rounded(totals[1].adjusted),
    },
  ];
  const columns = [
    { key: "measure", header: "Package" },
    { key: "a", header: `Side ${sides[0].label}`, numeric: true },
    { key: "b", header: `Side ${sides[1].label}`, numeric: true },
  ];
  return (
    <div className={styles.resultTable} data-testid="trade-immediate-result">
      <DataTable
        columns={columns}
        rows={rows}
        rowKey="id"
        caption="Package totals per side: raw, Value Adjustment, adjusted"
        density="compact"
        rowClassName={(row) => (row.id === "adjusted" ? styles.resultTableTotal : "")}
      />
    </div>
  );
}

/** The words for every non-answer state of the decision echo. */
const SUMMARY_STATE_TEXT = {
  "no-team": "Pick your team to get a decision for your roster.",
  idle: "Add assets to both sides to get a decision.",
  "side-choice": "Tell the War Room which side is yours to get a decision.",
  loading: "Analyzing this trade…",
  error: "Analysis unavailable right now. The package result above is unaffected.",
  multi: "No YES / NO for a trade with more than two teams; the War Room covers two-team trades.",
};

/**
 * Layer 3's echo in the sticky desktop column: the War Room's headline,
 * confidence statement and primary reason, verbatim, with a link to the full
 * analysis.  It is the SAME decision, never a second one — the War Room owns
 * the request and reports it through `onDecision`.
 */
export function DecisionSummary({ summary }) {
  const status = summary?.status || "idle";
  const decision = summary?.decision || null;
  const showDecision = Boolean(decision) && (status === "ok" || status === "updating");
  return (
    <section
      className={styles.decisionSummary}
      aria-labelledby="trade-decision-summary-title"
      data-testid="decision-summary"
      data-decision-state={showDecision ? status : status === "updating" ? "loading" : status}
    >
      <h2 id="trade-decision-summary-title" className={styles.layerTitle}>
        Final decision
      </h2>
      {showDecision ? (
        <div className={status === "updating" ? styles.summaryStale : undefined}>
          <p className={styles.summaryLine}>
            <Badge
              tone={DECISION_TONES[decision.headline]}
              data-testid="decision-summary-headline"
            >
              {decision.headlineText}
            </Badge>
          </p>
          {decision.confidence?.statement ? (
            <p className={styles.summaryNote}>{decision.confidence.statement}</p>
          ) : null}
          {decision.primaryReason?.text ? (
            <p className={styles.summaryNote}>
              <span className={styles.summaryLabel}>Primary reason</span>{" "}
              {decision.primaryReason.text}
            </p>
          ) : null}
          {status === "updating" ? (
            <p className={styles.summaryNote} role="status">
              Updating for your latest change…
            </p>
          ) : null}
        </div>
      ) : (
        <p className={styles.summaryNote} role={status === "loading" ? "status" : undefined}>
          {SUMMARY_STATE_TEXT[status === "updating" ? "loading" : status] || SUMMARY_STATE_TEXT.idle}
        </p>
      )}
      <a href="#trade-decision" className={styles.summaryLink}>
        {status === "multi" ? "About the War Room" : "Full analysis in the War Room"}
      </a>
    </section>
  );
}

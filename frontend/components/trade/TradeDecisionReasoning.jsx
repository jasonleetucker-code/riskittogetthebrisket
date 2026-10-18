"use client";

/**
 * TradeDecisionReasoning — the Reasoning tab of /trade's Supporting
 * intelligence (TC-D2; UX audit §7.1 layer 4 "Reasoning ... how this was
 * decided + coverage").
 *
 * It renders, verbatim, two parts of the ONE decision the War Room already
 * fetched (`POST /api/trade/analyze`, reported up through `onDecision`) that
 * the War Room itself does not show:
 *
 *   - `decision.whatWouldChange` — what would flip the answer (TC-C);
 *   - `decision.coverage` — the per-dimension evidence coverage record, all
 *     ten dimensions, so "not evaluated" can never read as "evaluated and
 *     neutral" (decision-engine audit §7.5).
 *
 * Nothing here decides or re-weighs anything: the words and states are the
 * engine's, mapped to plain labels; an unknown code is shown, never dropped.
 */

import { DataTable } from "@/components/ds";
import styles from "./trade-package-breakdown.module.css";

export const DIMENSION_LABELS = {
  asset_value: "Asset value",
  immediate_improvement: "Immediate improvement",
  long_term: "Long-term improvement",
  roster_construction: "Roster construction",
  market_evidence: "Market evidence",
  competitive_strategy: "Competitive strategy",
  risk: "Risk",
  feasibility: "Feasibility",
  opportunity_cost: "Opportunity cost",
  league_constraints: "League constraints",
};

export const COVERAGE_STATE_LABELS = {
  evaluated: "Evaluated",
  partial: "Partly evaluated",
  unavailable: "Not evaluated",
  excluded_by_mode: "Not evaluated (Asset-Only)",
};

export const EVIDENCE_KIND_LABELS = {
  independent: "Independent",
  correlated: "Correlated",
  contextual: "Contextual",
  explanatory: "Explanatory",
};

export const ROLE_LABELS = {
  decides: "Decides",
  gate: "Gate",
  tiebreak: "Tie-break",
  explain_only: "Explains only",
  confidence_only: "Confidence only",
};

const REASON_LABELS = {
  asset_only_mode: "Asset-Only analysis",
  not_computed: "not computed",
  not_wired: "not wired yet",
  partial_projection_coverage: "a traded player has no projection",
};

const humanize = (code) => (code == null || code === "" ? null : String(code).replace(/_/g, " "));
const label = (map, code) => map[code] || humanize(code) || "—";

/** The coverage record as table rows; every record kept, in the engine's order. */
export function coverageRows(coverage) {
  return (Array.isArray(coverage) ? coverage : []).map((c, i) => ({
    id: `${c?.dimension || "dimension"}-${i}`,
    dimension: label(DIMENSION_LABELS, c?.dimension),
    state: label(COVERAGE_STATE_LABELS, c?.state),
    kind: label(EVIDENCE_KIND_LABELS, c?.evidenceKind),
    role: label(ROLE_LABELS, c?.role),
    freshness: humanize(c?.freshness) || "—",
    note:
      REASON_LABELS[c?.exclusionReason] ||
      humanize(c?.exclusionReason) ||
      c?.applicability?.reason ||
      "",
  }));
}

const COLUMNS = [
  { key: "dimension", header: "Dimension" },
  { key: "state", header: "Coverage" },
  { key: "kind", header: "Evidence", hideBelow: "md" },
  { key: "role", header: "Role" },
  { key: "freshness", header: "Freshness", hideBelow: "md" },
  { key: "note", header: "Note", hideBelow: "sm" },
];

export default function TradeDecisionReasoning({ decision, emptyText }) {
  if (!decision) {
    return (
      <p className={styles.note} data-testid="decision-reasoning-empty">
        {emptyText}
      </p>
    );
  }
  const changes = (decision.whatWouldChange || []).filter((w) => w?.text);
  const rows = coverageRows(decision.coverage);
  return (
    <div className={styles.breakdown} data-testid="decision-reasoning">
      <h3 className={styles.title}>What would change the answer</h3>
      {changes.length ? (
        <ul className={styles.legend} data-testid="decision-what-would-change">
          {changes.map((w, i) => (
            <li key={`${w.kind || "change"}-${i}`} className={styles.note}>
              {w.text}
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.note}>The engine named no single change that would flip it.</p>
      )}
      <h3 className={styles.title}>Evidence coverage</h3>
      {rows.length ? (
        <DataTable
          columns={COLUMNS}
          rows={rows}
          rowKey="id"
          caption="Evidence coverage for each decision dimension"
          density="compact"
        />
      ) : (
        <p className={styles.note}>This answer carries no coverage record.</p>
      )}
      <p className={styles.note}>
        &ldquo;Decides&rdquo; rows are the independent evidence the answer rests on; gates and
        tie-breaks apply only as the engine&apos;s rules say; the other rows explain without being
        weighed. A dimension that was not evaluated says why.
      </p>
    </div>
  );
}

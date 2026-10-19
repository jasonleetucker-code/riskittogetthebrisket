"use client";

/**
 * ValueAdjustmentComparison — Chase Upside's package adjustment beside the KTC
 * adjustment method, for the trade on screen (owner directive 2026-10-19,
 * part 2).  Self-contained: mounted once in the decision area; the War Room
 * layout lane may move the mount line freely.
 *
 * Compact by default: one plain sentence (the methods agree / both call it
 * near even but differ on which side is slightly ahead ("split") / disagree /
 * no adjustment under either / unavailable), the two gaps, and one control
 * that opens the full calculation.  Never a second verdict: the recommendation is
 * the War Room's, computed with Chase Upside's adjustment only, and nothing
 * here reads or feeds it.
 *
 * Props
 *   sideValues    Array<Array<number|null>> — each side's canonical published
 *                 values (`trade-logic.js::displayValue` per asset; null =
 *                 unpriced, which makes the comparison unavailable, never 0).
 *   sideLabels    string[] — "A", "B", …
 *   compact       boolean — start with the calculation closed (default true).
 *   hasOverrides  boolean — the user typed value overrides; says the
 *                 comparison uses published values, like the War Room.
 *
 * Every number comes from `lib/va-comparison.js`, which runs the ONE canonical
 * package-model dispatch once per model.  This file formats; it computes
 * nothing.
 */

import { useId, useMemo, useState } from "react";
import { Button } from "@/components/ds";
import {
  ACTIVE_METHOD_LABEL,
  COMPARATOR_METHOD_LABEL,
  VA_COMPARISON_STATUS,
  compareValueAdjustments,
  vaComparisonSummary,
} from "@/lib/va-comparison";
import styles from "./va-comparison.module.css";

const fmt = (v) => Math.round(v).toLocaleString("en-US");
const signed = (v) => {
  const r = Math.round(v);
  if (r === 0) return "0";
  return `${r > 0 ? "+" : "−"}${Math.abs(r).toLocaleString("en-US")}`;
};

function moreValueText(evaluation, sideLabels) {
  return evaluation.moreValueIdx == null ? "Equal" : `Side ${sideLabels[evaluation.moreValueIdx]}`;
}

function CalculationTable({ comparison, sideLabels }) {
  const { active, comparator } = comparison;
  const cols = [active, comparator];
  const rows = [
    ...sideLabels.map((lbl, i) => ({
      key: `adj-${i}`,
      label: `Adjustment to Side ${lbl}`,
      cells: cols.map((m) => (m.adjustments[i] > 0 ? `+${fmt(m.adjustments[i])}` : "None")),
    })),
    ...sideLabels.map((lbl, i) => ({
      key: `tot-${i}`,
      label: `Side ${lbl} after adjustment`,
      cells: cols.map((m) => fmt(m.adjustedTotals[i])),
    })),
    {
      key: "gap",
      label: `Gap (Side ${sideLabels[0]} minus Side ${sideLabels[1]})`,
      cells: cols.map((m) => signed(m.gap)),
    },
    {
      key: "more",
      label: "More adjusted value",
      cells: cols.map((m) => moreValueText(m, sideLabels)),
    },
    // A bare percentage — never a fairness-band word (the summary sentence
    // already says whether each method calls it near even), so neither column
    // reads like a second verdict.
    {
      key: "pct",
      label: "Gap, % of the larger side",
      cells: cols.map((m) => (m.relativeGapPct == null ? "—" : `${m.relativeGapPct.toFixed(1)}%`)),
    },
  ];
  return (
    <div
      className={styles.tableWrap}
      role="region"
      aria-label="Value Adjustment calculation"
      tabIndex={0}
    >
      <table className={styles.table} data-testid="va-comparison-table">
        <caption className="ds-visually-hidden">
          Package totals under Chase Upside&apos;s adjustment and under the KTC adjustment method,
          both applied to the same Chase Upside values
        </caption>
        <thead>
          <tr>
            <th scope="col">Measure</th>
            <th scope="col" className={styles.num}>
              {ACTIVE_METHOD_LABEL} (used)
            </th>
            <th scope="col" className={styles.num}>
              {COMPARATOR_METHOD_LABEL}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <th scope="row">{r.label}</th>
              {r.cells.map((c, i) => (
                <td key={i} className={styles.num}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ValueAdjustmentComparison({
  sideValues,
  sideLabels = ["A", "B"],
  compact = true,
  hasOverrides = false,
}) {
  const [open, setOpen] = useState(!compact);
  const detailId = useId();
  // Keyed on the values themselves: the page may hand a fresh array each render.
  const valuesKey = JSON.stringify(sideValues || []);
  const comparison = useMemo(
    () => compareValueAdjustments(sideValues),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [valuesKey],
  );
  const labels = sideLabels.length ? sideLabels : ["A", "B"];
  const summary = vaComparisonSummary(comparison, labels);
  if (summary.tone === "empty") return null;
  const numeric = comparison.status === VA_COMPARISON_STATUS.OK && !comparison.noAdjustment;

  return (
    <section
      className={styles.vac}
      aria-label="Value Adjustment comparison"
      data-testid="va-comparison"
      data-tone={summary.tone}
    >
      <p className={styles.label}>Value Adjustment</p>
      <p className={styles.summary} data-testid="va-comparison-summary">
        {summary.headline}
      </p>
      {summary.gapLine ? (
        <p className={styles.note} data-testid="va-comparison-gaps">
          {summary.gapLine}
        </p>
      ) : null}
      {hasOverrides && comparison.status !== VA_COMPARISON_STATUS.MULTI_TEAM ? (
        <p className={styles.note} data-testid="va-comparison-override-note">
          Uses published Chase Upside values; your typed overrides change the headline only.
        </p>
      ) : null}
      {numeric ? (
        <>
          <Button
            size="sm"
            variant="ghost"
            className={styles.toggle}
            aria-expanded={open}
            aria-controls={detailId}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "Hide the calculation" : "Show the calculation"}
          </Button>
          {open ? (
            <div id={detailId} className={styles.detail} data-testid="va-comparison-detail">
              <p className={styles.note}>
                Before any adjustment: Side {labels[0]} {fmt(comparison.active.rawTotals[0])} · Side{" "}
                {labels[1]} {fmt(comparison.active.rawTotals[1])} (Chase Upside values, the same for
                both methods).
              </p>
              <CalculationTable comparison={comparison} sideLabels={labels} />
              <ul className={styles.notes}>
                <li>
                  {ACTIVE_METHOD_LABEL}: {comparison.active.receipt.label}. It is the one the
                  recommendation uses.
                </li>
                <li>
                  {COMPARATOR_METHOD_LABEL}: KeepTradeCut&apos;s published package-adjustment
                  formula (April 2026), applied here to Chase Upside values. These are not
                  KTC&apos;s own player values. It shows no adjustment for a one-for-one trade or
                  when its result is under 3.3% of the combined trade.
                </li>
                <li>
                  For comparison only: the two adjustments are never added together, averaged or
                  used to change any player&apos;s value.
                </li>
              </ul>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

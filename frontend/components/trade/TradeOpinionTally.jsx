"use client";

/**
 * TradeOpinionTally — the IMMEDIATE one-glance Second Opinions tally beside
 * the meter (TC-B / TCM-K03; SECOND_OPINIONS_TODO, owner fallback spec).
 *
 * "Independent: Side A 5 · Side B 3 · Even 1 — 9 of 11 source families
 * priced every piece · Estimates (share our values): Side A 2".
 *
 * Reads the SAME rows as the per-source table (`buildOpinionRows`, one
 * assembly) and the SAME tally owner (`tallyOpinions`): full-source rows are
 * the only independent votes, one per correlation family; hybrid estimates
 * are shown separately and never counted as votes.  It states counts, not a
 * verdict — the decision is the War Room's.  BARE sides: a manual override
 * changes the user's headline, never what a source sees.
 *
 * Loaded on demand (React.lazy on /trade), so the opinion machinery stays out
 * of the page's first-load chunk.
 */

import { useMemo } from "react";
import {
  buildOpinionRows,
  opinionCoverageText,
  opinionTally,
  opinionTallyText,
} from "@/lib/second-opinions-rows";
import styles from "./trade-next-actions.module.css";

export default function TradeOpinionTally({ sides }) {
  const rows = useMemo(() => buildOpinionRows(sides), [sides]);
  const sideLabels = (sides || []).map((s) => s.label);
  const filled = (sides || []).filter((s) => (s.assets || []).length > 0).length;
  if (filled < 2 || !rows.length) return null;
  const tally = opinionTally(rows, sideLabels.length);
  const independent = tally.independent;
  return (
    <p className={styles.tally} data-testid="trade-opinion-tally" aria-label="Second opinions tally">
      <span className={styles.label}>Second opinions</span>
      {independent.families > 0 ? (
        <span>
          Independent: <span className={styles.count}>{opinionTallyText(independent, sideLabels)}</span>
        </span>
      ) : (
        <span>No source priced every piece, so there is no independent vote.</span>
      )}
      <span className={styles.muted} data-testid="trade-opinion-tally-coverage">
        {opinionCoverageText(tally)}
      </span>
      {tally.modeled.families > 0 ? (
        <span className={styles.muted}>
          Estimates (share our values, not votes): {opinionTallyText(tally.modeled, sideLabels)}
        </span>
      ) : null}
      <span className={styles.muted}>Per-source detail: Second opinions, below.</span>
    </p>
  );
}

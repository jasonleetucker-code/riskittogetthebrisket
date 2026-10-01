"use client";

/**
 * BdvmScoringNotice — the BDVM partial-scoring notice.
 *
 * Some nonzero rules on the league's scoring card cannot be scored from a
 * projected stat line (the projection simply has no such stat). For the
 * players those rules touch, projected points — and the fundamental value
 * built on them — are a PARTIAL total. The omitted contribution can be
 * positive (an unscored bonus) or negative (an unscored penalty), so the
 * notice never calls the total a floor or a ceiling.
 *
 * Display only: the census and the per-rule signs are backend fields
 * (`meta.scoringCoverage.unscoredKeys` / `.weightSign`, src/bdvm/service.py),
 * selected by lib/bdvm.js::bdvmScoringCoverage. An unpublished sign is said
 * as such — never assumed to be a bonus.
 */
import React from "react";
import { Banner } from "@/components/ds";
import { bdvmScoringCoverage } from "@/lib/bdvm";
import styles from "./value-explain.module.css";

function signLabel(sign, signsPublished) {
  if (sign === "+") return "bonus (+) — can only raise the true total";
  if (sign === "-") return "penalty (−) — can only lower the true total";
  return signsPublished ? "sign unknown" : "sign not published";
}

export default function BdvmScoringNotice({ payload }) {
  const cov = bdvmScoringCoverage(payload);
  if (!cov || cov.keys.length === 0) return null;
  const n = cov.keys.length;
  return (
    <Banner tone="info" title="Partial scoring">
      <p className={styles.attribution}>
        {n === 1 ? "One league scoring rule" : `${n} league scoring rules`} can&rsquo;t be
        scored from the projections. For the players affected, projected points and the
        fundamental value built on them are a partial total: each unscored rule&rsquo;s
        omitted contribution may be positive (a bonus) or negative (a penalty), so the true
        total can be higher or lower.
      </p>
      <details>
        <summary className={styles.attribution}>Unscored rules ({n})</summary>
        <ul className={styles.reasons}>
          {cov.keys.map((k) => (
            <li key={k.key}>
              <code>{k.key}</code>
              {k.players != null
                ? ` — ${k.players} player${k.players === 1 ? "" : "s"}`
                : ""}{" "}
              · {signLabel(k.sign, cov.signsPublished)}
            </li>
          ))}
        </ul>
      </details>
    </Banner>
  );
}

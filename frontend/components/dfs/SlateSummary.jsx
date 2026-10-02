"use client";

/**
 * SlateSummary — what an imported slate contains, what disagrees with the
 * encoded rules, and how fresh each information class is.  Code-split from the
 * /dfs page chunk (React.lazy) to keep that chunk inside its budget.
 * Display only: every value comes from the /api/dfs/slates response.
 */

import React from "react";
import { Banner, StatusIndicator } from "@/components/ds";
import { formatSalary } from "@/lib/dfs";
import styles from "./dfs-workspace.module.css";

const FRESHNESS_LABELS = {
  salary: "Salary",
  projection: "Projections",
  distribution: "Outcome ranges",
  ownership: "Ownership",
  sportsbook: "Sportsbook",
  news: "News",
  lineups_status: "Lineups / status",
  podcast: "Podcast evidence",
};

function Freshness({ rows }) {
  if (!rows?.length) return null;
  return (
    // Controlled horizontal scroll region (UI contract: tables may scroll
    // sideways; the PAGE may not). Focusable + labelled so keyboard users can
    // scroll it too.
    <div className={styles.tableScroll} role="region" aria-label="Data freshness" tabIndex={0}>
    <table className={styles.freshness}>
      <caption>Data freshness</caption>
      <thead>
        <tr>
          <th scope="col">Information</th>
          <th scope="col">State</th>
          <th scope="col">Source</th>
          <th scope="col">As of</th>
          <th scope="col">Coverage</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((f) => (
          <tr key={f.class}>
            <th scope="row">{FRESHNESS_LABELS[f.class] || f.class}</th>
            <td>
              <StatusIndicator status={f.state === "unavailable" ? "neutral" : "warning"}>
                {f.state === "as_imported" ? "As imported" : "Unavailable"}
              </StatusIndicator>
            </td>
            <td>{f.source || "—"}</td>
            <td className="ds-mono">{f.asOf ? new Date(f.asOf).toLocaleString() : "—"}</td>
            <td>{f.coverage || f.note || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
}

export default function ImportSummary({ slate }) {
  const cov = slate.coverage;
  const pr = slate.projectionReport;
  const rejected = slate.importReport?.rejected || [];
  return (
    <div className={styles.summary} aria-live="polite">
      <dl className={styles.facts}>
        <div>
          <dt>Players</dt>
          <dd className="ds-mono">{cov.athletes}</dd>
        </div>
        <div>
          <dt>With projection</dt>
          <dd className="ds-mono">{cov.projected}</dd>
        </div>
        <div>
          <dt>No projection</dt>
          <dd className="ds-mono">{cov.unprojected}</dd>
        </div>
        <div>
          <dt>Games</dt>
          <dd className="ds-mono">{slate.games.length}</dd>
        </div>
        <div>
          <dt>Snapshot</dt>
          <dd className="ds-mono" title={slate.contentHash}>
            {slate.contentHash.slice(0, 10)}
          </dd>
        </div>
      </dl>
      {rejected.length ? (
        <Banner tone="warning" title={`${rejected.length} salary row(s) not imported`}>
          <ul className={styles.list}>
            {rejected.slice(0, 8).map((r) => (
              <li key={`${r.row}-${r.reason}`}>
                Row {r.row}: {r.reason.replaceAll("_", " ")}
              </li>
            ))}
          </ul>
        </Banner>
      ) : null}
      {pr && (pr.unmatched.length || pr.ambiguous.length || pr.conflicts.length || pr.invalid.length) ? (
        <Banner tone="warning" title="Some projection rows were not applied">
          <p>
            Unresolved identities are held back, never guessed: {pr.unmatched.length} unmatched,{" "}
            {pr.ambiguous.length} ambiguous, {pr.conflicts.length} conflicting, {pr.invalid.length} blank or non-numeric.
          </p>
          <ul className={styles.list}>
            {[...pr.ambiguous, ...pr.unmatched, ...pr.conflicts].slice(0, 8).map((r) => (
              <li key={`${r.row}-${r.reason}`}>
                Row {r.row} {r.name ? `(${r.name})` : ""}: {r.reason.replaceAll("_", " ")}
              </li>
            ))}
          </ul>
        </Banner>
      ) : null}
      {slate.eligibilityCrossCheck?.state === "disagrees" ? (
        <Banner tone="warning" title="The platform's roster slots disagree with the encoded rules">
          {slate.eligibilityCrossCheck.mismatched} of {slate.eligibilityCrossCheck.checked} players list different
          eligible slots than the rule set. The rule set is unverified; nothing was changed automatically.
        </Banner>
      ) : slate.eligibilityCrossCheck?.state === "agrees" ? (
        <p className={styles.note}>
          The platform's own roster slots agree with the encoded rules for all {slate.eligibilityCrossCheck.checked}{" "}
          players — evidence toward verifying them, not verification.
        </p>
      ) : null}
      {slate.salaryCapCrossCheck && !slate.salaryCapCrossCheck.agrees ? (
        <Banner tone="warning" title="Salary cap disagrees">
          Source cap {formatSalary(slate.salaryCapCrossCheck.source)}; rule set {formatSalary(slate.salaryCapCrossCheck.ruleset)}.
        </Banner>
      ) : null}
      <Freshness rows={slate.freshness} />
      {slate.platformAverageApplied ? (
        <p className={styles.note}>
          {slate.platformAverageApplied} player(s) use the platform season average because you opted in. It is a
          past-performance observation, not a projection.
        </p>
      ) : null}
    </div>
  );
}

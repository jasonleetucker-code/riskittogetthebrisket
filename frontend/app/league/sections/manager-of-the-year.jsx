"use client";

// Unified Manager of the Year — the one overall management card (owner
// decision 2026-09-28; methodology: docs/awards/MANAGER_OF_THE_YEAR_METHODOLOGY.md).
//
// Renders the backend's evaluation (`bySeason[].managerOfTheYear`) verbatim:
// overall score, the five contributions out of 40/25/15/10/10, raw metrics,
// provisional / final / candidate status, coverage and the as-of week. This
// file computes no score, weight, rank or normalization — every number on the
// card is a backend field, only formatted here.

import { Badge } from "@/components/ds";

import { fmtNumber } from "../shared-helpers.js";
import styles from "./awards.module.css";

// Component order, labels and the weight each is worth, as the backend
// publishes them in `evaluation.weights` (fallback: the owner-proposed 40/25/15/10/10).
const COMPONENTS = [
  ["A", "All-play"],
  ["T", "Trades"],
  ["W", "Waivers & roster"],
  ["D", "Draft"],
  ["P", "Postseason"],
];

const COVERAGE_COPY = {
  trade_future_value_unavailable: "Trade future value isn't scored: no decision-time valuations exist for this window.",
  trade_future_value_partial: "Trade future value isn't scored: only some trades have decision-time valuations.",
  waiver_future_value_not_implemented: "Waiver and draft future value aren't measured yet — those channels score production only.",
  window_baseline_unavailable: "Starting rosters are unavailable, so trade, waiver and draft value can't be scored.",
  ledger_reconciliation_gaps: "A few roster-weeks couldn't be matched to a transaction and are left out.",
};

function signed(n, digits = 1) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  const v = Number(n);
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmtNumber(Math.abs(v), digits)}`;
}

export function motyStatusCopy(evaluation) {
  if (!evaluation) return null;
  if (evaluation.status === "provisional") return "Provisional score — postseason component pending.";
  if (evaluation.official) return "Final score.";
  return "Candidate methodology — not this season's official result.";
}

export function motyCoverageNotes(evaluation) {
  const reasons = evaluation?.coverage?.reasons || [];
  const notes = [];
  for (const reason of reasons) {
    if (reason === "draft_future_value_not_implemented") continue; // folded into the waiver line
    const copy = COVERAGE_COPY[reason];
    if (copy && !notes.includes(copy)) notes.push(copy);
  }
  return notes;
}

function rawLine(key, component) {
  const raw = component?.raw || {};
  switch (key) {
    case "A":
      return component?.score == null
        ? "No finished week yet"
        : `${fmtNumber(component.score, 1)}% of weekly matchups won against the whole league · ${raw.weeksObserved} wk`;
    case "T": {
      if (!raw.trades && !raw.draftPickExpectationNet) return "No trades";
      const picks = raw.draftPickExpectationNet
        ? ` (picks ${signed(raw.draftPickExpectationNet)})`
        : "";
      return `${signed(raw.netSurplus)} net surplus pts${picks} · ${raw.trades || 0} trades`;
    }
    case "W": {
      const faab =
        raw.faabBudget != null
          ? ` · $${fmtNumber(raw.faabSpent)} of $${fmtNumber(raw.faabBudget)} FAAB`
          : "";
      return `${signed(raw.netSurplus)} net surplus pts${faab}`;
    }
    case "D":
      if (!raw.selections) return "No draft selections";
      return `${signed(raw.netSurplusVsExpectation)} pts vs slot expectation · ${raw.selections} picks`;
    case "P": {
      if (component?.status !== "final") return "Pending — decided by the playoffs";
      const rank = component.finishRank;
      if (rank === 1) return "Champion";
      if (rank === 2) return "Runner-up";
      if (component.madePlayoffs) return `Playoffs · finish ${fmtNumber(rank, rank % 1 ? 1 : 0)}`;
      return "Missed the playoffs (eligible; scores 0)";
    }
    default:
      return "";
  }
}

function unobservedWeeks(row) {
  const c = row?.components || {};
  return ["T", "W", "D"].reduce((sum, k) => sum + (Number(c[k]?.raw?.unobservedWeeks) || 0), 0);
}

export function ManagerOfTheYearBreakdown({ evaluation, focusOwnerId, officialName }) {
  if (!evaluation || !Array.isArray(evaluation.rows) || evaluation.rows.length === 0) return null;
  const scored = evaluation.rows.filter((r) => r.score !== null && r.score !== undefined);
  const row =
    evaluation.rows.find((r) => r.ownerId === focusOwnerId && r.score != null) || scored[0];
  if (!row) return null;
  const weights = evaluation.weights || { A: 0.4, T: 0.25, W: 0.15, D: 0.1, P: 0.1 };
  const provisional = evaluation.status === "provisional";
  const notes = motyCoverageNotes(evaluation);
  const unobserved = unobservedWeeks(row);
  const candidateOnly = !provisional && !evaluation.official;
  return (
    <section
      className={styles.motyPanel}
      aria-label={`Manager of the Year breakdown for ${row.displayName}`}
      data-moty-breakdown
    >
      <header className={styles.motyHeader}>
        <div>
          <div className={styles.motyKicker}>
            {candidateOnly ? "Unified method · candidate leader" : "Manager of the Year · breakdown"}
          </div>
          <div className={styles.motyName}>{row.displayName}</div>
        </div>
        <div className={styles.motyScore}>
          <span className={styles.motyScoreValue}>{fmtNumber(row.score, 1)}</span>
          <span className={styles.motyScoreMax}>/ 100</span>
        </div>
      </header>
      <p className={styles.motyStatus} data-moty-status={evaluation.status}>
        <Badge tone={provisional ? "info" : candidateOnly ? "outline" : "neutral"}>
          {provisional ? "Provisional" : candidateOnly ? "Candidate" : "Final"}
        </Badge>{" "}
        {motyStatusCopy(evaluation)}
        {provisional && row.earnedOf90 != null && (
          <> Earned {fmtNumber(row.earnedOf90, 1)} of the 90 points decided so far.</>
        )}
        {candidateOnly && officialName && <> The official winner is {officialName}.</>}
      </p>
      {row.explanation && <p className={styles.motyExplain}>{row.explanation}</p>}
      <ul className={styles.motyComponents}>
        {COMPONENTS.map(([key, label]) => {
          const comp = row.components?.[key] || {};
          const max = Math.round((weights[key] || 0) * 100);
          const contribution = row.contributions?.[key];
          const pending = contribution === null || contribution === undefined;
          return (
            <li key={key} className={styles.motyComponent} data-moty-component={key}>
              <div className={styles.motyComponentTop}>
                <span className={styles.motyComponentLabel}>{label}</span>
                <span className={styles.motyComponentValue}>
                  {pending ? "pending" : fmtNumber(contribution, 1)}
                  <span className={styles.motyComponentMax}> / {max}</span>
                </span>
              </div>
              <div
                className={styles.motyBar}
                role="img"
                aria-label={
                  comp.score == null
                    ? `${label}: not scored yet`
                    : `${label}: ${fmtNumber(comp.score, 1)} out of 100`
                }
              >
                <span
                  className={styles.motyBarFill}
                  style={{ width: `${comp.score == null ? 0 : Math.max(0, Math.min(100, comp.score))}%` }}
                />
              </div>
              <div className={styles.motyRaw}>
                {rawLine(key, comp)}
                {comp.coverage === "partial" && key !== "A" && (
                  <span className={styles.motyPartial}> · production only</span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {(notes.length > 0 || unobserved > 0) && (
        <div className={styles.motyCoverage} data-moty-coverage={evaluation.coverage?.status}>
          <div className={styles.motyCoverageTitle}>
            Coverage: {evaluation.coverage?.status === "complete" ? "complete" : "partial"}
          </div>
          <ul>
            {notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
            {unobserved > 0 && (
              <li>
                {fmtNumber(unobserved)} player-weeks couldn't be observed (player unrostered) and are
                left out — never counted as zero.
              </li>
            )}
          </ul>
        </div>
      )}
      <details className={styles.motyAll}>
        <summary>All managers</summary>
        <div className={styles.motyTableWrap}>
          <table className={styles.motyTable}>
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Manager</th>
                <th scope="col">Score</th>
                {COMPONENTS.map(([key]) => (
                  <th scope="col" key={key} title={COMPONENTS.find((c) => c[0] === key)[1]}>
                    {key}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {evaluation.rows.map((r) => (
                <tr key={r.ownerId}>
                  <td>{r.rank == null ? "—" : `${r.tied ? "T" : ""}${r.rank}`}</td>
                  <th scope="row">{r.displayName}</th>
                  <td>{fmtNumber(r.score, 1)}</td>
                  {COMPONENTS.map(([key]) => (
                    <td key={key}>
                      {r.components?.[key]?.score == null ? "—" : fmtNumber(r.components[key].score, 1)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <footer className={styles.motyFooter}>
        As of week {evaluation.asOfWeek} · method {evaluation.methodVersion} · weights{" "}
        {COMPONENTS.map(([key]) => Math.round((weights[key] || 0) * 100)).join("/")} are award
        policy, not statistically validated
      </footer>
    </section>
  );
}

export default ManagerOfTheYearBreakdown;

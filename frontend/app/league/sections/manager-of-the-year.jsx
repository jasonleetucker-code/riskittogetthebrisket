"use client";

// Unified Manager of the Year — the one overall management card (owner
// decision 2026-09-28; methodology: docs/awards/MANAGER_OF_THE_YEAR_METHODOLOGY.md).
//
// Renders the backend's evaluation (`bySeason[].managerOfTheYear`) verbatim:
// overall score (or, while trades cannot be scored, the measured points out of
// the measurable points), the five contributions out of 40/25/15/10/10, raw
// metrics, status, coverage and the as-of week. This file computes no score,
// weight, rank or normalization — every number on the card is a backend field,
// only formatted here.
//
// VALIDATION TRACK (owner direction 2026-09-29): until the backend says
// `official: true`, the card is labelled PARTIAL / NOT PROMOTED and never
// presented as the official Manager of the Year.

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
  trade_future_value_unavailable: "No decision-time valuations exist for this window's trades.",
  trade_future_value_partial: "Only some of this window's trades have decision-time valuations.",
  trade_component_unscored:
    "Trades aren't scored: their future-value side (picks, young players) can't be measured, and scoring only this season's production would penalize every rebuilding trade. Their 25 points are missing, not redistributed.",
  waiver_future_value_not_implemented: "Waiver and draft future value aren't measured yet — those channels score production only.",
  window_baseline_unavailable: "Starting rosters are unavailable, so trade, waiver and draft value can't be scored.",
  ledger_reconciliation_gaps: "A few roster-weeks couldn't be matched to a transaction and are left out.",
};

function signed(n, digits = 1) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  const v = Number(n);
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmtNumber(Math.abs(v), digits)}`;
}

export const VALIDATION_LABEL = "PARTIAL / NOT PROMOTED";

export function motyStatusCopy(evaluation) {
  if (!evaluation) return null;
  if (evaluation.official) {
    return evaluation.status === "provisional"
      ? "Provisional score — postseason component pending."
      : "Final score.";
  }
  const parts = ["Validation track — not the official Manager of the Year."];
  if (evaluation.scoreBasis === "incomplete") {
    parts.push("Incomplete: trades aren't scored, so there is no overall score yet.");
  }
  if (evaluation.status === "provisional") parts.push("Postseason component pending.");
  return parts.join(" ");
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
      const line = `${signed(raw.netSurplus)} net surplus pts${picks} · ${raw.trades || 0} trades`;
      if (component?.score == null) {
        return `Not scored — future-value side can't be measured · production side only (context): ${line}`;
      }
      return line;
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
  // Backend-ranked rows: ranked on the score, or on measured points while
  // trades are unscored (the backend decides which; never recomputed here).
  const ranked = evaluation.rows.filter((r) => r.rank !== null && r.rank !== undefined);
  const row = evaluation.rows.find((r) => r.ownerId === focusOwnerId && r.rank != null) || ranked[0];
  if (!row) return null;
  const weights = evaluation.weights || { A: 0.4, T: 0.25, W: 0.15, D: 0.1, P: 0.1 };
  const provisional = evaluation.status === "provisional";
  const notes = motyCoverageNotes(evaluation);
  const unobserved = unobservedWeeks(row);
  const official = evaluation.official === true;
  const incomplete = row.score == null ? row.incomplete : null;
  return (
    <section
      className={styles.motyPanel}
      aria-label={`Manager of the Year breakdown for ${row.displayName}`}
      data-moty-breakdown
    >
      <header className={styles.motyHeader}>
        <div>
          <div className={styles.motyKicker}>
            {official
              ? "Manager of the Year · breakdown"
              : "Unified method · validation track · not official"}
          </div>
          <div className={styles.motyName}>{row.displayName}</div>
        </div>
        {incomplete ? (
          <div className={styles.motyScore} data-moty-incomplete>
            <span className={styles.motyScoreValue}>{fmtNumber(incomplete.measuredPoints, 1)}</span>
            <span className={styles.motyScoreMax}>
              {" "}
              / {fmtNumber(incomplete.measurablePoints, 0)} measured pts
            </span>
          </div>
        ) : (
          <div className={styles.motyScore}>
            <span className={styles.motyScoreValue}>{fmtNumber(row.score, 1)}</span>
            <span className={styles.motyScoreMax}>/ 100</span>
          </div>
        )}
      </header>
      <p className={styles.motyStatus} data-moty-status={evaluation.status}>
        <Badge tone={official ? (provisional ? "info" : "neutral") : "outline"}>
          {official ? (provisional ? "Provisional" : "Final") : VALIDATION_LABEL}
        </Badge>{" "}
        {motyStatusCopy(evaluation)}
        {provisional && row.earnedOf90 != null && (
          <> Earned {fmtNumber(row.earnedOf90, 1)} of the 90 points decided so far.</>
        )}
        {incomplete && (
          <>
            {" "}
            {fmtNumber(incomplete.measuredPoints, 1)} of the {fmtNumber(incomplete.measurablePoints, 0)}{" "}
            points that can be measured — not a score out of 100.
          </>
        )}
        {incomplete && Array.isArray(evaluation.unscoredTradeRange?.couldLeadUnderSomeT) && (
          <span data-moty-undecided>
            {" "}
            {evaluation.unscoredTradeRange.leaderDetermined
              ? "No unscored trade value could change who leads."
              : `Not decided: the unscored trades (up to ${fmtNumber(
                  evaluation.unscoredTradeRange.tMaxPoints,
                  0,
                )} pts) could put any of ${evaluation.unscoredTradeRange.couldLeadUnderSomeT.length} managers first.`}
          </span>
        )}
        {!official && officialName && (
          <>
            {" "}
            {provisional
              ? `The official race uses the existing method (current leader: ${officialName}).`
              : `The official winner is ${officialName}.`}
          </>
        )}
      </p>
      {row.explanation && <p className={styles.motyExplain}>{row.explanation}</p>}
      <ul className={styles.motyComponents}>
        {COMPONENTS.map(([key, label]) => {
          const comp = row.components?.[key] || {};
          const max = Math.round((weights[key] || 0) * 100);
          const contribution = row.contributions?.[key];
          const unscored = key === "T" && comp.score == null && comp.coverage === "unavailable";
          const pending = contribution === null || contribution === undefined;
          return (
            <li key={key} className={styles.motyComponent} data-moty-component={key}>
              <div className={styles.motyComponentTop}>
                <span className={styles.motyComponentLabel}>{label}</span>
                <span className={styles.motyComponentValue}>
                  {unscored ? "not scored" : pending ? "pending" : fmtNumber(contribution, 1)}
                  <span className={styles.motyComponentMax}> / {max}</span>
                </span>
              </div>
              <div
                className={styles.motyBar}
                role="img"
                aria-label={
                  comp.score == null
                    ? `${label}: not scored`
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
                  <td>
                    {r.score != null
                      ? fmtNumber(r.score, 1)
                      : r.incomplete
                        ? `${fmtNumber(r.incomplete.measuredPoints, 1)}/${fmtNumber(r.incomplete.measurablePoints, 0)}`
                        : "—"}
                  </td>
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
        As of week {evaluation.asOfWeek} · method {evaluation.methodVersion}
        {official ? "" : ` · ${VALIDATION_LABEL}`} · weights{" "}
        {COMPONENTS.map(([key]) => Math.round((weights[key] || 0) * 100)).join("/")} are award
        policy, not statistically validated
      </footer>
    </section>
  );
}

export default ManagerOfTheYearBreakdown;

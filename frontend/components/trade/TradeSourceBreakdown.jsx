"use client";

/**
 * TradeSourceBreakdown — Second Opinions: each source's view of THIS trade.
 *
 * Owner package 2026-10-17 (SECOND_OPINIONS_CANONICAL_FALLBACK_SPEC). Per
 * source (grouped by vendor): the source's normalized values for the pieces
 * it prices, Chase Upside's EXACT published value for every piece it does
 * not, and OUR ACTIVE package model applied once to the assembled packages —
 * the same model as the headline. Every number is on one canonical 1-9999
 * basis; vendor-native values appear only in the per-asset drilldown.
 *
 * Row states (lib/second-opinions.js):
 *   FULL_SOURCE         all pieces source-priced — votes (one per family)
 *   HYBRID_ESTIMATE     some pieces are our value — shown, labelled, no vote
 *   CHASE_ONLY_BASELINE source priced nothing here — listed, never an opinion
 *   INCOMPLETE          a piece nobody prices — no numeric verdict
 *   UNAVAILABLE         the source's value was excluded for an evidence
 *                       reason — "Unavailable — <reason>", no vote, never
 *                       EVEN (owner closeout 2026-10-18, decision 9)
 *
 * LAYOUT (owner directive 2026-10-19: easy to scan on a phone).  The opinion
 * (Leader + Margin) is visible without panning at 1366, 390 and 375: the
 * coverage line wraps, each row's raw / Chase Upside adjustment / total
 * breakdown is in its expanded detail, and below 768 px the side totals move
 * there too (`source-breakdown.module.css`).  Layout only: every number,
 * state, label and vote is unchanged.
 *
 * COMPARE ADJUSTMENTS (owner directive 2026-10-19, part 3).  One control
 * re-evaluates every row under the KTC adjustment method — the SAME per-asset
 * values the row already used, a second whole-package adjustment (never
 * stacked on, added to or averaged with ours).  The answer is a line under
 * each source name, at every width: the shell caps /trade at 1320 px and this
 * table already fills the 60% builder column, so an extra column would sit
 * off-screen on every desktop.  Rows whose adjusted leader changes say so in
 * words; nothing else is badged.  The votes, tallies and row states are
 * computed before and without it, and are identical whichever way the control
 * is set.  It is OUR copy of KTC's formula applied to that source's values —
 * never that site's own policy.
 *
 * Inputs: ``sides`` (``{label, assets}``, 2+ sides; also rendered by the
 * waivers add/drop panel), ``settings`` (memo dep), and ``hasOverrides``:
 * /trade passes BARE sides on purpose — a manual override changes the
 * user's headline, never what a source is said to see — and this flag lets
 * the panel say so.
 */

import { Fragment, useMemo, useState } from "react";

import { Button } from "@/components/ds";

import {
  FALLBACK_REASON_LABEL,
  OPINION_ORIGIN,
  OPINION_STATE,
  tallyOpinions,
  unavailableReasonText,
} from "@/lib/second-opinions";
import { buildOpinionRows, opinionTallyText } from "@/lib/second-opinions-rows";
import { packageModelReceipt } from "@/lib/trade-logic";
import { COMPARATOR_METHOD_LABEL, COMPARATOR_PACKAGE_MODEL_ID } from "@/lib/va-comparison";

import SignalsRankOpinion from "./SignalsRankOpinion";
import sb from "./source-breakdown.module.css";
import vac from "./va-comparison.module.css";

const fmt = (v) => (v == null ? "—" : Math.round(v).toLocaleString());

function stateLabel(opinion, sideLabels) {
  const lead =
    opinion.leaderIdx == null
      ? "Even"
      : `Side ${sideLabels[opinion.leaderIdx]}`;
  if (opinion.state === OPINION_STATE.INCOMPLETE) return "Incomplete";
  // Decision 9: never "Even" -- the source could not be evaluated, and says
  // why (the reason on its own wrapping line, so the column stays narrow).
  if (opinion.state === OPINION_STATE.UNAVAILABLE) {
    return (
      <>
        Unavailable —{" "}
        <span
          className="muted"
          style={{
            display: "block",
            fontSize: "0.62rem",
            fontWeight: 400,
            maxWidth: "14rem",
            margin: "0 auto",
            whiteSpace: "normal",
          }}
        >
          {(opinion.unavailableReasons || [null]).map(unavailableReasonText).join("; ")}
        </span>
      </>
    );
  }
  if (opinion.state === OPINION_STATE.HYBRID_ESTIMATE) return `${lead} (est.)`;
  return lead;
}

function coverageText(counts) {
  const parts = [`${counts.source}/${counts.total} source`];
  if (counts.fallback) parts.push(`${counts.fallback} Chase fallback`);
  if (counts.unpriced) parts.push(`${counts.unpriced} unpriced`);
  if (counts.unavailable) parts.push(`${counts.unavailable} unavailable`);
  return parts.join(" · ");
}

const tallyText = opinionTallyText;

/**
 * The KTC-method answer for one row, terse ("A by 58%", "even", "not
 * computed") so the line stays short on a phone; the adjusted totals live in
 * the row's expanded detail.  Never a number for a row with no numeric verdict.
 */
function comparisonLeaderText(cmp, sideLabels) {
  if (!cmp?.available) return "not computed";
  if (cmp.leaderIdx == null) return "even";
  return `${sideLabels[cmp.leaderIdx]} by ${Math.round(cmp.marginPct)}%`;
}

/** "Leader differs on 2 of 9 compared sources." — counts only, no verdict. */
function compareCountText(comparable, differing) {
  const n = comparable.length;
  const noun = `compared source${n === 1 ? "" : "s"}`;
  if (n === 0) return "No source has a numeric verdict to compare.";
  if (differing.length === 0) return `Same leader on all ${n} ${noun}.`;
  return `Leader differs on ${differing.length} of ${n} ${noun}.`;
}

/**
 * Per-row detail: each side's raw total, Chase Upside's adjustment and the
 * adjusted total (the breakdown that used to sit under every side cell) and,
 * with Compare adjustments on, the KTC method beside it from the same raw
 * totals.  The only place a phone shows the side totals.
 */
function PackageDetail({ row, sideLabels, compareOn }) {
  const o = row.opinion;
  const cmp = row.comparison;
  if (!o.rawTotals) {
    return compareOn ? (
      <p className="muted" style={{ margin: "0 0 6px", fontSize: "0.7rem" }}>
        {COMPARATOR_METHOD_LABEL}: not computed — this source has no numeric verdict here.
      </p>
    ) : null;
  }
  const withKtc = compareOn && cmp?.available;
  const signedVa = (v) => (v > 0 ? `+${fmt(v)}` : "none");
  const num = { textAlign: "right", fontFamily: "var(--mono)" };
  return (
    <table
      className="source-breakdown-assets"
      aria-label={
        withKtc ? `Both adjustment methods for ${row.label}` : `Package totals for ${row.label}`
      }
      style={{ marginBottom: 6 }}
    >
      <thead>
        <tr>
          <th style={{ textAlign: "left" }}>Side</th>
          <th style={{ textAlign: "right" }}>Raw</th>
          <th style={{ textAlign: "right" }}>Chase Upside adj.</th>
          <th style={{ textAlign: "right" }}>Total</th>
          {withKtc ? (
            <>
              <th style={{ textAlign: "right" }}>KTC method adj.</th>
              <th style={{ textAlign: "right" }}>Total</th>
            </>
          ) : null}
        </tr>
      </thead>
      <tbody>
        {sideLabels.map((lbl, i) => (
          <tr key={`pkg-${row.key}-${i}`}>
            <td style={{ textAlign: "left" }}>Side {lbl}</td>
            <td style={num}>{fmt(o.rawTotals[i])}</td>
            <td style={num}>{signedVa(o.adjustments[i])}</td>
            <td style={num}>{fmt(o.adjustedTotals[i])}</td>
            {withKtc ? (
              <>
                <td style={num}>{signedVa(cmp.adjustments[i])}</td>
                <td style={num}>{fmt(cmp.adjustedTotals[i])}</td>
              </>
            ) : null}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function TradeSourceBreakdown({
  sides,
  settings,
  hasOverrides = false,
}) {
  const [open, setOpen] = useState(() => new Set());
  const [compare, setCompare] = useState(false);
  const model = packageModelReceipt();

  // One row assembly shared with the immediate tally beside the meter
  // (lib/second-opinions-rows.js, TC-B / TCM-K03).  The comparison model is
  // attached as `row.comparison`; `row.opinion` never depends on it.
  const rows = useMemo(
    () =>
      buildOpinionRows(sides, compare ? { compareModelId: COMPARATOR_PACKAGE_MODEL_ID } : {}),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sides, settings, compare],
  );

  const sideLabels = sides.map((s) => s.label);
  const shown = rows.filter(
    (r) => r.opinion.state !== OPINION_STATE.CHASE_ONLY_BASELINE,
  );
  const baseline = rows.filter(
    (r) => r.opinion.state === OPINION_STATE.CHASE_ONLY_BASELINE,
  );
  const tally = tallyOpinions(rows, sides.length);
  const twoTeam = sides.length === 2;
  const compareOn = compare && twoTeam;
  const differing = compareOn
    ? shown.filter((r) => r.comparison?.available && r.comparison.leaderDiffers)
    : [];
  const comparable = compareOn ? shown.filter((r) => r.comparison?.available) : [];
  const toggle = (key) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <div className="card source-breakdown-card" style={{ marginTop: 14 }}>
      <div className="source-breakdown-header">
        <span className="source-breakdown-header-text">
          <span
            className="source-breakdown-title"
            style={{ margin: 0, fontSize: "0.88rem", fontWeight: 700 }}
          >
            Per-source view
          </span>
          <span
            className="muted source-breakdown-subtitle"
            style={{ fontSize: "0.72rem" }}
            data-testid="second-opinions-notice"
          >
            Second Opinion = that source&apos;s priced assets + Chase
            Upside&apos;s {model.label} package adjustment. It may not match
            that website&apos;s own calculator. Pieces a source does not price
            use Chase Upside&apos;s published value and are marked estimated.
          </span>
        </span>
      </div>
      {hasOverrides && (
        <p
          className="muted"
          data-testid="second-opinions-override-note"
          style={{ margin: "4px 0", fontSize: "0.72rem" }}
        >
          Your manual value overrides change the headline only; these rows use
          published values.
        </p>
      )}
      {shown.length === 0 ? (
        <div
          className="muted"
          style={{ padding: "10px 0", fontSize: "0.78rem", lineHeight: 1.45 }}
        >
          No per-source view for this trade yet — add at least one asset to each
          side.
        </div>
      ) : (
        <>
          <p
            className="source-breakdown-tally"
            data-testid="second-opinions-tally"
            style={{ margin: "6px 0 2px", fontSize: "0.78rem" }}
          >
            {tally.independent.families > 0 ? (
              <>
                <strong>{tallyText(tally.independent, sideLabels)}</strong>
                <span className="muted">
                  {" "}
                  — independent votes, one per source family (
                  {tally.independent.families} of {tally.independent.eligible}{" "}
                  families priced every piece)
                </span>
              </>
            ) : (
              <span className="muted">
                No complete independent votes available — no source priced every
                piece.
              </span>
            )}
          </p>
          {tally.counts.unavailable > 0 && (
            <p
              className="muted"
              data-testid="second-opinions-unavailable-tally"
              style={{ margin: "0 0 4px", fontSize: "0.74rem" }}
            >
              Unavailable (not counted, not even): {tally.counts.unavailable} source
              {tally.counts.unavailable === 1 ? "" : "s"} — see each row for the reason.
            </p>
          )}
          {tally.modeled.families > 0 && (
            <p
              className="muted"
              data-testid="second-opinions-modeled-tally"
              style={{ margin: "0 0 4px", fontSize: "0.74rem" }}
            >
              Estimates (not independent — they share our values):{" "}
              {tallyText(tally.modeled, sideLabels)}
            </p>
          )}
          <div style={{ margin: "4px 0" }}>
            <Button
              size="sm"
              variant="ghost"
              aria-pressed={compare}
              data-testid="second-opinions-compare"
              onClick={() => setCompare((v) => !v)}
            >
              Compare adjustments
            </Button>
          </div>
          {compare ? (
            <p
              className="muted"
              data-testid="second-opinions-compare-note"
              style={{ margin: "0 0 4px", fontSize: "0.72rem", lineHeight: 1.45 }}
            >
              {twoTeam ? (
                <>
                  {COMPARATOR_METHOD_LABEL}: KeepTradeCut&apos;s package-adjustment formula,
                  applied by Chase Upside to each source&apos;s same values instead of our
                  adjustment. It is not that source&apos;s own calculator, and not KTC&apos;s own
                  player values. Comparison only — the votes above use Chase Upside&apos;s
                  adjustment.{" "}
                  <strong data-testid="second-opinions-compare-count">
                    {compareCountText(comparable, differing)}
                  </strong>
                </>
              ) : (
                <>
                  {COMPARATOR_METHOD_LABEL}: not computed for a {sides.length}-team trade — it is
                  a two-team model.
                </>
              )}
            </p>
          ) : null}
          <div
            id="source-breakdown-body"
            className="source-breakdown-body"
            style={{ overflowX: "auto" }}
          >
            <table className={`source-breakdown-table ${sb.table}`}>
              <caption className="ds-visually-hidden">
                Each source&apos;s raw and adjusted package totals with
                per-asset provenance.
              </caption>
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Source</th>
                  {sideLabels.map((lbl, i) => (
                    <th key={`h-${i}`} className={sb.sideCol} style={{ textAlign: "right" }}>
                      Side {lbl}
                    </th>
                  ))}
                  <th style={{ textAlign: "center" }}>Leader</th>
                  <th style={{ textAlign: "right" }}>Margin</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => {
                  const o = row.opinion;
                  const expanded = open.has(row.key);
                  const numeric =
                    o.state !== OPINION_STATE.INCOMPLETE &&
                    o.state !== OPINION_STATE.UNAVAILABLE;
                  return (
                    <Fragment key={row.key}>
                      <tr data-state={o.state}>
                        <td style={{ textAlign: "left" }} title={row.displayName}>
                          <button
                            type="button"
                            className="source-breakdown-expand"
                            aria-expanded={expanded}
                            aria-label={`${expanded ? "Hide" : "Show"} asset values for ${row.label}`}
                            onClick={() => toggle(row.key)}
                          >
                            {expanded ? "−" : "+"}
                          </button>{" "}
                          {row.label}
                          <span
                            className={`muted ${sb.meta}`}
                            data-testid="second-opinions-coverage"
                          >
                            {row.signal} · {coverageText(o.counts)}
                          </span>
                          {compareOn ? (
                            <span
                              className={vac.compareLine}
                              data-testid="second-opinions-compare-line"
                              data-differs={row.comparison?.leaderDiffers ? "true" : undefined}
                            >
                              KTC method: {comparisonLeaderText(row.comparison, sideLabels)}
                              {row.comparison?.leaderDiffers ? (
                                <span className={vac.differs}> · leader differs</span>
                              ) : null}
                            </span>
                          ) : null}
                        </td>
                        {sideLabels.map((_, i) => (
                          <td
                            key={`v-${row.key}-${i}`}
                            className={sb.sideCol}
                            style={{
                              textAlign: "right",
                              fontFamily: "var(--mono)",
                              fontWeight: o.leaderIdx === i ? 700 : 400,
                              fontStyle:
                                o.state === OPINION_STATE.HYBRID_ESTIMATE
                                  ? "italic"
                                  : "normal",
                            }}
                          >
                            {numeric ? fmt(o.adjustedTotals[i]) : "—"}
                          </td>
                        ))}
                        <td
                          style={{ textAlign: "center", fontWeight: 700 }}
                          data-opinion="leader"
                          data-testid={
                            o.state === OPINION_STATE.UNAVAILABLE
                              ? "second-opinions-unavailable"
                              : undefined
                          }
                        >
                          {stateLabel(o, sideLabels)}
                          {numeric && o.swing && (
                            <span
                              className="muted"
                              style={{
                                display: "block",
                                fontSize: "0.62rem",
                                fontWeight: 400,
                              }}
                            >
                              adjustment flipped raw leader (
                              {o.rawLeaderIdx == null
                                ? "even"
                                : `Side ${sideLabels[o.rawLeaderIdx]}`}
                              )
                            </span>
                          )}
                          {o.state === OPINION_STATE.INCOMPLETE && (
                            <span
                              className="muted"
                              style={{
                                display: "block",
                                fontSize: "0.62rem",
                                fontWeight: 400,
                              }}
                            >
                              {o.counts.unpriced} piece
                              {o.counts.unpriced === 1 ? "" : "s"} nobody prices
                            </span>
                          )}
                        </td>
                        <td
                          style={{
                            textAlign: "right",
                            fontFamily: "var(--mono)",
                          }}
                          data-opinion="margin"
                        >
                          {numeric && o.leaderIdx != null
                            ? `${o.marginPct.toFixed(1)}%`
                            : "—"}
                        </td>
                      </tr>
                      {expanded && (
                        <tr className="source-breakdown-detail">
                          <td colSpan={sideLabels.length + 3}>
                            <div className={`source-breakdown-assets-wrap ${sb.detailWrap}`}>
                              <PackageDetail
                                row={row}
                                sideLabels={sideLabels}
                                compareOn={compareOn}
                              />
                              <table
                                className="source-breakdown-assets"
                                aria-label={`Asset values for ${row.label}`}
                              >
                                <thead>
                                  <tr>
                                    <th style={{ textAlign: "left" }}>Asset</th>
                                    <th style={{ textAlign: "right" }}>
                                      Source value
                                    </th>
                                    <th style={{ textAlign: "right" }}>
                                      Chase fallback
                                    </th>
                                    <th style={{ textAlign: "right" }}>
                                      Value used
                                    </th>
                                    <th style={{ textAlign: "left" }}>
                                      Provenance
                                    </th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {o.resolutionsBySide.flatMap((rs, si) =>
                                    rs.map((r, ai) => (
                                      <tr key={`${row.key}-${si}-${ai}`}>
                                        <td style={{ textAlign: "left" }}>
                                          {r.name}{" "}
                                          <span className="muted">
                                            (Side {sideLabels[si]})
                                          </span>
                                        </td>
                                        <td
                                          style={{
                                            textAlign: "right",
                                            fontFamily: "var(--mono)",
                                          }}
                                        >
                                          {fmt(r.sourceValue)}
                                          {r.nativeValue != null && (
                                            <span
                                              className="muted"
                                              style={{
                                                display: "block",
                                                fontSize: "0.6rem",
                                              }}
                                            >
                                              native {fmt(r.nativeValue)}
                                            </span>
                                          )}
                                        </td>
                                        <td
                                          style={{
                                            textAlign: "right",
                                            fontFamily: "var(--mono)",
                                          }}
                                        >
                                          {fmt(r.fallbackValue)}
                                        </td>
                                        <td
                                          style={{
                                            textAlign: "right",
                                            fontFamily: "var(--mono)",
                                          }}
                                        >
                                          {fmt(r.value)}
                                        </td>
                                        <td style={{ textAlign: "left" }}>
                                          {r.origin === OPINION_ORIGIN.SOURCE
                                            ? "Source"
                                            : r.origin ===
                                                OPINION_ORIGIN.CHASE_UPSIDE_FALLBACK
                                              ? `Chase Upside fallback — ${FALLBACK_REASON_LABEL[r.reason]}`
                                              : r.origin === OPINION_ORIGIN.UNAVAILABLE
                                                ? `Unavailable — ${unavailableReasonText(r.reason)}`
                                                : `Unpriced — ${FALLBACK_REASON_LABEL[r.reason]}`}
                                        </td>
                                      </tr>
                                    )),
                                  )}
                                </tbody>
                              </table>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
      {baseline.length > 0 && (
        <p
          className="muted"
          data-testid="second-opinions-uncovered"
          style={{ margin: "6px 0 0", fontSize: "0.72rem", lineHeight: 1.45 }}
        >
          Chase Upside values only — priced none of these pieces, so not an
          opinion: {baseline.map((r) => r.label).join(", ")}.
        </p>
      )}
      {/* Rank-only, non-voting: never part of `rows` or the tallies above. */}
      <SignalsRankOpinion sides={sides} />
    </div>
  );
}

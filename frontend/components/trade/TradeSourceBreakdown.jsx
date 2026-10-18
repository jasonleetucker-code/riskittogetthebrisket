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
 *
 * Inputs: ``sides`` (``{label, assets}``, 2+ sides; also rendered by the
 * waivers add/drop panel), ``settings`` (memo dep), and ``hasOverrides``:
 * /trade passes BARE sides on purpose — a manual override changes the
 * user's headline, never what a source is said to see — and this flag lets
 * the panel say so.
 */

import { Fragment, useMemo, useState } from "react";

import {
  FALLBACK_REASON_LABEL,
  OPINION_ORIGIN,
  OPINION_STATE,
  tallyOpinions,
} from "@/lib/second-opinions";
import { buildOpinionRows, opinionTallyText } from "@/lib/second-opinions-rows";
import { packageModelReceipt } from "@/lib/trade-logic";

import SignalsRankOpinion from "./SignalsRankOpinion";

const fmt = (v) => (v == null ? "—" : Math.round(v).toLocaleString());

function stateLabel(opinion, sideLabels) {
  const lead =
    opinion.leaderIdx == null
      ? "Even"
      : `Side ${sideLabels[opinion.leaderIdx]}`;
  if (opinion.state === OPINION_STATE.INCOMPLETE) return "Incomplete";
  if (opinion.state === OPINION_STATE.HYBRID_ESTIMATE) return `${lead} (est.)`;
  return lead;
}

function coverageText(counts) {
  const parts = [`${counts.source}/${counts.total} source`];
  if (counts.fallback) parts.push(`${counts.fallback} Chase fallback`);
  if (counts.unpriced) parts.push(`${counts.unpriced} unpriced`);
  return parts.join(" · ");
}

const tallyText = opinionTallyText;

export default function TradeSourceBreakdown({
  sides,
  settings,
  hasOverrides = false,
}) {
  const [open, setOpen] = useState(() => new Set());
  const model = packageModelReceipt();

  // One row assembly shared with the immediate tally beside the meter
  // (lib/second-opinions-rows.js, TC-B / TCM-K03).
  const rows = useMemo(
    () => buildOpinionRows(sides),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sides, settings],
  );

  const sideLabels = sides.map((s) => s.label);
  const shown = rows.filter(
    (r) => r.opinion.state !== OPINION_STATE.CHASE_ONLY_BASELINE,
  );
  const baseline = rows.filter(
    (r) => r.opinion.state === OPINION_STATE.CHASE_ONLY_BASELINE,
  );
  const tally = tallyOpinions(rows, sides.length);
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
          <div
            id="source-breakdown-body"
            className="source-breakdown-body"
            style={{ overflowX: "auto" }}
          >
            <table className="source-breakdown-table">
              <caption className="ds-visually-hidden">
                Each source&apos;s raw and adjusted package totals with
                per-asset provenance.
              </caption>
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Source</th>
                  {sideLabels.map((lbl, i) => (
                    <th key={`h-${i}`} style={{ textAlign: "right" }}>
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
                  const numeric = o.state !== OPINION_STATE.INCOMPLETE;
                  return (
                    <Fragment key={row.key}>
                      <tr data-state={o.state}>
                        <td
                          style={{ textAlign: "left", whiteSpace: "nowrap" }}
                          title={row.displayName}
                        >
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
                            className="muted"
                            style={{
                              display: "block",
                              fontSize: "0.62rem",
                              fontWeight: 400,
                            }}
                          >
                            {row.signal} · {coverageText(o.counts)}
                          </span>
                        </td>
                        {sideLabels.map((_, i) => (
                          <td
                            key={`v-${row.key}-${i}`}
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
                            {numeric && (
                              <span
                                className="muted"
                                style={{
                                  display: "block",
                                  fontSize: "0.62rem",
                                  fontStyle: "normal",
                                }}
                              >
                                raw {fmt(o.rawTotals[i])}
                                {o.adjustments[i] > 0
                                  ? ` + VA ${fmt(o.adjustments[i])}`
                                  : ""}
                              </span>
                            )}
                          </td>
                        ))}
                        <td style={{ textAlign: "center", fontWeight: 700 }}>
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
                        >
                          {numeric && o.leaderIdx != null
                            ? `${o.marginPct.toFixed(1)}%`
                            : "—"}
                        </td>
                      </tr>
                      {expanded && (
                        <tr className="source-breakdown-detail">
                          <td colSpan={sideLabels.length + 3}>
                            <div className="source-breakdown-assets-wrap">
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

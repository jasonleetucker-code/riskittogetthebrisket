"use client";

/**
 * MultiTeamWarRoom — Analyze Trade for a 3+-team trade on /trade (owner
 * directive 2026-10-20 §7; spec docs/trade/NTEAM_TRADE_ENGINE_SPEC.md §3.2).
 *
 * The builder's sides are bound to league teams by rosterId (on each side
 * card), every asset is identified by its canonical id and routed to an
 * explicit destination; `lib/trade-multi-team.js::buildMultiTeamLedger` turns
 * that into the `POST /api/trade/analyze-multi` body or into the named reasons
 * it cannot.  The server analyses EVERY team from one snapshot, simultaneously
 * (`analyze_service.analyze_trade_n`), and this component renders the answer:
 *
 *   * an all-team summary — each team's Decision and Market fairness, the
 *     server's summary lines, the trade-level fairness (all teams fair?) and
 *     the raw-value conservation check — never a trade-level YES / NO;
 *   * a perspective switch (one tab per team, over the one response);
 *   * per team: the ONE decision (`decision.headlineText`, verbatim — the
 *     texts are owned by `src/trade/trade_decision.py::HEADLINE_TEXT` and
 *     never written here) and its category, the market-fairness band as a
 *     SEPARATELY labelled answer (C4), what it sends and receives with destinations and
 *     values, the package totals and Value Adjustment, roster fit and forced
 *     drops, lineup impact, team direction, confidence and missing evidence,
 *     plus the same detail sections as the two-team War Room.
 *
 * DISPLAY ONLY: every number is the server's, verbatim.  Nothing here prices
 * an asset, adjusts a package or decides anything; a missing value renders as
 * words, never 0.  An edited trade invalidates the answer at once and, once
 * the user has asked for an analysis, re-asks automatically.  Recommendation
 * only — nothing executes.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge, Banner, Button, SegmentedControl, Tabs, tabId, tabPanelId } from "@/components/ds";
import {
  CATEGORY_TONES,
  FAIRNESS_LEVEL_WORDS,
  FAIRNESS_REASON_WORDS,
  FAIRNESS_STATE_TONES,
  FAIRNESS_STATE_WORDS,
  MULTI_TEAM_ENDPOINT,
  OVERALL_FAIRNESS_WORDS,
  buildMultiTeamLedger,
  multiErrorRetryable,
  multiErrorText,
  multiRequestKey,
  validMultiPayload,
} from "@/lib/trade-multi-team";
import {
  DECISION_TONES,
  formatSignedValue,
  formatValue,
  postureSummary,
} from "@/lib/trade-war-room";
import {
  confidenceSummary,
  decisionReasonSentences,
  listJoin,
  missingEvidenceText,
  partialCoverageNote,
  rosterFit,
  rosterNoteLines,
  tradeValueSummary,
  weeklyImpact,
} from "@/lib/trade-war-room-copy";
import { RECOMMENDATION_ONLY_TEXT } from "@/components/help/TradeHelp";
import { Arguments, BeforeAfter, Disclosure, Methodology, PlayerImpact } from "./TradeWarRoom";
import styles from "./war-room.module.css";
import own from "./multi-team-war-room.module.css";

export const MULTI_DEBOUNCE_MS = 450;
export const MULTI_TIMEOUT_MS = 90_000;

const CONTEXT_OPTIONS = [
  { value: "team", label: "Team context" },
  { value: "asset", label: "Asset only" },
];

const ROSTER_STATE_WORDS = {
  stale: "League rosters are out of date",
  unknown: "League rosters have no provable refresh time",
};

function valueWords(asset) {
  if (asset?.valueState === "priced" && typeof asset.value === "number") {
    return formatValue(asset.value);
  }
  if (asset?.valueState === "not_held") return "Not held by the sender";
  if (asset?.valueState === "off_board") return "Not on the board (unknown, not zero)";
  if (asset?.valueState === "quarantined") return "Value withheld: quarantined (not trusted)";
  if (asset?.valueState === "stale") return "Value withheld: stale (not trusted)";
  return "No value (unknown, not zero)";
}

const isPricedLeg = (a) => a?.valueState === "priced" && typeof a.value === "number";

/**
 * The legs of one team's part of the trade that carry no trusted value —
 * any ``valueState`` other than ``priced`` (quarantined, stale, unpriced,
 * off-board, not held, or one this component does not recognise).  While
 * there is one, the team's trade-value RESULT is not determinable: the
 * server's totals either leave the leg out or sum a value it withholds, so
 * no "you receive X and send Y" is read from them.
 */
function untrustedLegs(team) {
  return [...(team?.gives || []), ...(team?.receives || [])].filter((a) => !isPricedLeg(a));
}

/** "B Seven (Value withheld: quarantined (not trusted))", for a reason line. */
function legReasons(legs) {
  return listJoin(legs.map((a) => `${a.label || a.assetId} (${valueWords(a)})`));
}

// Short reason words for the at-a-glance table, where width is scarce.
const SHORT_STATE_WORDS = {
  quarantined: "quarantined",
  stale: "stale",
  unpriced: "no value",
  off_board: "not on the board",
  not_held: "not held",
};
const shortStateWords = (a) => SHORT_STATE_WORDS[a?.valueState] || "unknown";

/** "B Seven quarantined", for the at-a-glance table. */
function shortLegReasons(legs) {
  return listJoin(legs.map((a) => `${a.label || a.assetId} ${shortStateWords(a)}`));
}

/**
 * How each per-leg ``valueState`` bears on the server's package sums
 * (``src/trade/analyze_trade.py::_market_lens``):
 *
 *   * EXCLUDED — the leg is not in the sum at all: ``unpriced`` (no positive
 *     canonical value; named in ``unpricedOut`` / ``unpricedIn``),
 *     ``off_board`` (unresolved; named in ``unresolvedOut`` / ``unresolvedIn``)
 *     and ``not_held`` (the simulator leaves a pick the sender does not hold
 *     out of ``sending``).  A package with one is INCOMPLETE.
 *   * WITHHELD — ``quarantined`` / ``stale``: the canonical value is positive,
 *     so the market lens DOES sum it, but the per-team rows withhold it as
 *     untrustworthy (R1-L2).  A total containing a withheld number is not a
 *     trusted total, so it is not shown.
 *   * Any state this component does not recognise is treated as WITHHELD:
 *     whether it is in the sum is unknown, so the total is too (fail closed).
 */
const EXCLUDED_STATES = {
  unpriced: (n) => `${n === 1 ? "has" : "have"} no value on the board (unknown, not zero)`,
  off_board: (n) => `${n === 1 ? "is" : "are"} not on the board (unknown, not zero)`,
  not_held: (n) => `${n === 1 ? "is" : "are"} not held by the sender`,
};
const WITHHELD_STATES = {
  quarantined: (n) =>
    `${n === 1 ? "has a value" : "have values"} withheld as quarantined (not trusted)`,
  stale: (n) => `${n === 1 ? "has a value" : "have values"} withheld as stale (not trusted)`,
};
const UNRECOGNISED_STATE = (n) => `${n === 1 ? "has" : "have"} no usable value (unknown, not zero)`;

function packageState(items, detailNames) {
  const legs = Array.isArray(items) ? items : [];
  const pricedCount = legs.filter(
    (a) => a?.valueState === "priced" && typeof a.value === "number",
  ).length;
  const groups = new Map();
  let excluded = 0;
  let withheld = 0;
  for (const a of legs) {
    if (a?.valueState === "priced" && typeof a.value === "number") continue;
    const state = a?.valueState;
    const kind = EXCLUDED_STATES[state] ? "excluded" : "withheld";
    if (kind === "excluded") excluded += 1;
    else withheld += 1;
    const key = EXCLUDED_STATES[state] || WITHHELD_STATES[state] ? state : "?";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(String(a?.label || a?.assetId || "An asset"));
  }
  // Defensive: the server named an excluded asset no leg carries.
  if (!groups.size && detailNames.length) {
    groups.set("unpriced", detailNames);
    excluded = detailNames.length;
  }
  const clauses = [...groups.entries()].map(([key, names]) => {
    const words = EXCLUDED_STATES[key] || WITHHELD_STATES[key] || UNRECOGNISED_STATE;
    return `${listJoin(names)} ${words(names.length)}`;
  });
  const missing = excluded + withheld;
  return {
    clauses,
    excluded,
    withheld,
    // No priced leg, or a withheld number inside the sum: no total is shown.
    unknown: missing > 0 && (pricedCount === 0 || withheld > 0),
    incomplete: missing > 0,
  };
}

function fairnessDetail(f) {
  if (!f) return null;
  if (f.state === "UNABLE") {
    return FAIRNESS_REASON_WORDS[f.reasonCode]
      ? `Not judged: ${FAIRNESS_REASON_WORDS[f.reasonCode]}.`
      : "Not judged: the evidence is insufficient.";
  }
  const level = FAIRNESS_LEVEL_WORDS[f.level] || null;
  const parts = [];
  if (level) parts.push(`Package gap is ${level}`);
  if (typeof f.gap === "number" && typeof f.largerAdjustedSide === "number") {
    parts.push(
      `${formatSignedValue(f.gap)} on the larger ${formatValue(f.largerAdjustedSide)} package` +
        (typeof f.relativePct === "number" ? ` (${f.relativePct}%)` : ""),
    );
  }
  return parts.length ? `${parts.join(": ")}.` : null;
}

/**
 * The package totals, straight from the market lens (raw, VA, adjusted, gap).
 *
 * The state is derived from every leg's ``valueState`` (``packageState``),
 * never from the server's name lists alone: an unpriced, off-board or unheld
 * asset is left out of the server's sums, so a package with one is INCOMPLETE
 * and says so; a package with NO priced leg has no total at all — the server's
 * 0 is the empty sum, never the package's value — so it reads "Unknown", never
 * 0 (MISSING IS NEVER ZERO; E1-F5).  A quarantined or stale value IS in the
 * server's sum but is withheld per asset, so its package has no trusted total
 * either and reads "Unknown".
 */
function PackageTotals({ detail, gives = [], receives = [] }) {
  if (!detail) return null;
  const n = (v) => (typeof v === "number" ? formatValue(v) : "—");
  const va = (v) => (typeof v === "number" && Math.round(v) !== 0 ? `+${formatValue(v)}` : "none");
  const names = (...lists) =>
    lists.flatMap((xs) => (Array.isArray(xs) ? xs.filter(Boolean).map(String) : []));
  const rows = [
    {
      key: "send",
      label: "Sends",
      raw: detail.sendingValue,
      adj: detail.sendingValueAdjustment,
      total: detail.sendingAdjusted,
      ...packageState(gives, names(detail.unpricedOut, detail.unresolvedOut)),
    },
    {
      key: "recv",
      label: "Receives",
      raw: detail.receivingValue,
      adj: detail.receivingValueAdjustment,
      total: detail.receivingAdjusted,
      ...packageState(receives, names(detail.unpricedIn, detail.unresolvedIn)),
    },
  ];
  const notes = rows
    .filter((r) => r.incomplete)
    .map((r) => ({
      key: r.key,
      text: `${r.label === "Sends" ? "Sent" : "Received"} package ${
        r.unknown ? (r.withheld ? "has no trusted total" : "has no total") : "is incomplete"
      }: ${r.clauses.join("; ")}${
        r.unknown ? "" : `, so ${r.excluded === 1 ? "it is" : "they are"} left out of the total`
      }.`,
    }));
  return (
    <>
      <div
        className={styles.tableWrap}
        role="region"
        aria-label="Package totals for this team"
        tabIndex={0}
      >
        <table className={styles.table} data-testid="multi-team-package-totals">
          <caption className="ds-visually-hidden">Package totals for this team</caption>
          <thead>
            <tr>
              <th scope="col">Package</th>
              <th scope="col" className={styles.num}>
                Raw
              </th>
              <th scope="col" className={styles.num}>
                Value Adjustment
              </th>
              <th scope="col" className={styles.num}>
                Adjusted
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.key}
                data-package={r.key}
                data-package-state={
                  r.unknown ? "unknown" : r.incomplete ? "incomplete" : "complete"
                }
              >
                <th scope="row">
                  {r.label}
                  {r.incomplete ? (
                    <span className={styles.muted}>
                      {r.unknown ? (r.withheld ? " (withheld)" : " (unpriced)") : " (incomplete)"}
                    </span>
                  ) : null}
                </th>
                <td className={styles.num}>{r.unknown ? "Unknown" : n(r.raw)}</td>
                <td className={styles.num}>{r.unknown ? "—" : va(r.adj)}</td>
                <td className={styles.num}>{r.unknown ? "Unknown" : n(r.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {notes.map((x) => (
        <p key={x.key} className={styles.muted} data-testid={`multi-team-package-note-${x.key}`}>
          {x.text}
        </p>
      ))}
    </>
  );
}

function AssetList({ title, items, direction, nameOf, testId }) {
  return (
    <section className={own.assetGroup} aria-label={title}>
      <h4 className={styles.detailTitle}>{title}</h4>
      {items.length ? (
        <ul className={own.assetList} data-testid={testId}>
          {items.map((a) => (
            <li key={a.assetId} className={own.assetItem} data-asset-id={a.assetId}>
              <span className={own.assetName}>{a.label || a.assetId}</span>
              <span className={own.assetRoute}>
                {direction === "out" ? `→ ${nameOf(a.toRosterId)}` : `← ${nameOf(a.fromRosterId)}`}
              </span>
              {/* A value is a right-aligned number; words saying why there is
                  none take their own full-width line, so they never squeeze
                  the asset's name. */}
              <span className={isPricedLeg(a) ? own.assetValue : own.assetNote}>
                {valueWords(a)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.muted}>Nothing.</p>
      )}
    </section>
  );
}

function TeamResult({ team, nameOf, showStrategy, open, toggleOpen }) {
  const analysis = team.analysis || {};
  const decision = analysis.decision || null;
  const fairness = team.fairness || null;
  const confidence = decision
    ? confidenceSummary(decision.confidence, {
        rosterLens: analysis.lenses?.roster,
        evidenceLens: analysis.lenses?.evidence,
        decision,
      })
    : null;
  const reasons = decision ? decisionReasonSentences(decision, { analysis }) : [];
  const missing = (decision?.missingEvidence || [])
    .map((g, i) => ({
      key: `${g?.code || "gap"}-${i}`,
      sentence: missingEvidenceText(g),
    }))
    .filter((g) => g.sentence);
  const market = analysis.lenses?.market;
  // Withheld (F2): any non-priced leg makes the trade-value result not
  // determinable for this team — never a sentence built on the server's sum.
  const untrusted = untrustedLegs(team);
  const value = untrusted.length
    ? null
    : tradeValueSummary(market?.available ? market.detail : null);
  const impact = weeklyImpact(analysis.lenses?.roster);
  const fit = rosterFit(analysis.lenses?.feasibility);
  const fitNotes = rosterNoteLines(
    analysis.lenses?.feasibility?.detail?.notes,
    analysis.lenses?.feasibility?.detail,
  ).fit;
  const posture = postureSummary(analysis.lenses?.posture);
  const rosterLens = analysis.lenses?.roster;
  const rosterDetail = rosterLens?.detail || {};
  const rosterMeasured = typeof rosterDetail.ppg === "number";
  const partial = rosterLens?.unavailableReason === "partial_projection_coverage";
  const teamName = team.team?.name || nameOf(team.rosterId);
  const sec = (id) => `${team.rosterId}-${id}`;

  return (
    <div className={own.teamResult} data-team-result={team.rosterId}>
      <p className={styles.eyebrow}>Viewing the trade as {teamName}</p>
      {/* C4: the decision and the market fairness are two separately labelled
          answers, so "Fair" beside "No" never reads as two competing verdicts. */}
      <dl className={own.answers}>
        <div className={own.answer} data-answer="decision">
          <dt className={styles.glanceLabel}>Decision</dt>
          <dd className={styles.glanceValue}>
            {decision ? (
              <>
                <p className={styles.verdictLine}>
                  <span className="ds-visually-hidden">Decision for {teamName}: </span>
                  <Badge
                    tone={DECISION_TONES[decision.headline] || "neutral"}
                    data-testid="multi-team-decision"
                  >
                    {decision.headlineText}
                  </Badge>{" "}
                  <Badge tone={CATEGORY_TONES[team.category] || "neutral"}>
                    {team.categoryText}
                  </Badge>
                </p>
                {decision.subtext ? <p className={styles.verdictNote}>{decision.subtext}</p> : null}
                {confidence?.level || confidence?.detail ? (
                  <p className={styles.confidence} data-testid="multi-team-confidence">
                    {confidence?.level ? <strong>{confidence.level}.</strong> : null}
                    {confidence?.level && confidence?.detail ? " " : null}
                    {confidence?.detail}
                  </p>
                ) : null}
              </>
            ) : (
              <p className={styles.muted}>No decision was returned for this team.</p>
            )}
          </dd>
        </div>
        <div className={own.answer} data-answer="fairness">
          <dt className={styles.glanceLabel}>Market fairness</dt>
          <dd className={styles.glanceValue}>
            {fairness ? (
              <>
                <p className={styles.verdictLine}>
                  <Badge
                    tone={FAIRNESS_STATE_TONES[fairness.state] || "neutral"}
                    data-testid="multi-team-fairness"
                  >
                    {FAIRNESS_STATE_WORDS[fairness.state] || "Unable to determine"}
                  </Badge>
                </p>
                <p className={styles.note}>{fairnessDetail(fairness)}</p>
                <p className={styles.note}>
                  The package gap alone, before roster fit, lineup impact and forced cuts — the
                  decision weighs those too.
                </p>
              </>
            ) : (
              <p className={styles.muted}>Not returned.</p>
            )}
          </dd>
        </div>
      </dl>

      {reasons.length ? (
        <div className={styles.why}>
          <h4 className={styles.sectionTitle}>Why</h4>
          <ul className={styles.whyList} data-testid="multi-team-reasons">
            {reasons.map(({ role, reason, sentence }) => (
              <li key={role} data-role={role} data-stance={reason.stance}>
                {sentence}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {missing.length ? (
        <div className={styles.why}>
          <h4 className={styles.sectionTitle}>What is missing</h4>
          <ul className={styles.whyList} data-testid="multi-team-missing">
            {missing.map((g) => (
              <li key={g.key}>{g.sentence}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className={own.assets}>
        <AssetList
          title={`${teamName} sends`}
          items={team.gives || []}
          direction="out"
          nameOf={nameOf}
          testId="multi-team-gives"
        />
        <AssetList
          title={`${teamName} receives`}
          items={team.receives || []}
          direction="in"
          nameOf={nameOf}
          testId="multi-team-receives"
        />
      </div>

      <h4 className="ds-visually-hidden">This trade at a glance for {teamName}</h4>
      <dl className={styles.glance}>
        <div className={styles.glanceRow} data-lens="market">
          <dt className={styles.glanceLabel}>Trade value</dt>
          <dd className={styles.glanceValue}>
            {untrusted.length ? (
              <p className={styles.glanceAnswer} data-testid="multi-team-value-withheld">
                Withheld — not determinable for {teamName}: {legReasons(untrusted)}. A value
                that is withheld or unknown is never priced and never counted as 0.
              </p>
            ) : value ? (
              <p className={styles.glanceAnswer}>{value.sentence}</p>
            ) : (
              <p className={styles.muted}>
                No total: an asset in this team&apos;s part of the trade has no value (unknown, not
                zero).
              </p>
            )}
            {market?.available ? (
              <PackageTotals
                detail={market.detail}
                gives={team.gives || []}
                receives={team.receives || []}
              />
            ) : null}
          </dd>
        </div>
        <div className={styles.glanceRow} data-lens="roster">
          <dt className={styles.glanceLabel}>Impact on the lineup</dt>
          <dd className={styles.glanceValue}>
            {impact?.sentence ? (
              <>
                <p className={styles.glanceAnswer}>{impact.sentence}</p>
                {impact.note ? <p className={styles.note}>{impact.note}</p> : null}
              </>
            ) : (
              <p className={styles.muted}>{impact?.unavailable}</p>
            )}
          </dd>
        </div>
        <div className={styles.glanceRow} data-lens="feasibility">
          <dt className={styles.glanceLabel}>Does it fit the roster?</dt>
          <dd className={styles.glanceValue}>
            {fit?.sentence ? (
              <p className={styles.glanceAnswer} data-testid="multi-team-roster-fit">
                {fit.sentence}
              </p>
            ) : (
              <p className={styles.muted}>{fit?.unavailable}</p>
            )}
            {fit?.spots ? <p className={styles.note}>{fit.spots}</p> : null}
            {fitNotes.map((note) => (
              <p key={note} className={styles.note}>
                {note}
              </p>
            ))}
          </dd>
        </div>
        <div className={styles.glanceRow} data-lens="posture">
          <dt className={styles.glanceLabel}>Team direction</dt>
          <dd className={styles.glanceValue}>
            {posture?.available ? (
              <>
                <p className={styles.glanceAnswer} data-testid="multi-team-posture">
                  {posture.headline}
                  {posture.confidence ? ` (confidence ${posture.confidence})` : ""}
                </p>
                <p className={styles.note}>
                  {posture.timing}. {posture.ownFirst}.
                </p>
              </>
            ) : (
              <p className={styles.muted}>
                {analysis.teamContext?.applied === false
                  ? "Not used in Asset only mode."
                  : posture?.reasonText || "Not available for this team."}
              </p>
            )}
          </dd>
        </div>
      </dl>

      <div className={styles.disclosures}>
        {rosterMeasured && (rosterLens?.available || partial) ? (
          <>
            <Disclosure
              id={sec("players")}
              title="Lineup impact, player by player"
              open={Boolean(open[sec("players")])}
              onToggle={toggleOpen}
            >
              <PlayerImpact
                rosterDetail={rosterDetail}
                partialNote={partialCoverageNote(rosterLens)}
              />
            </Disclosure>
            <Disclosure
              id={sec("lineup")}
              title="Lineup before and after"
              open={Boolean(open[sec("lineup")])}
              onToggle={toggleOpen}
            >
              <BeforeAfter rosterDetail={rosterDetail} />
            </Disclosure>
          </>
        ) : null}
        <Disclosure
          id={sec("arguments")}
          title="Arguments, objections and uncertainty"
          open={Boolean(open[sec("arguments")])}
          onToggle={toggleOpen}
        >
          <Arguments analysis={analysis} showStrategy={showStrategy} />
        </Disclosure>
        <Disclosure
          id={sec("method")}
          title="Sources, simulations and methodology"
          open={Boolean(open[sec("method")])}
          onToggle={toggleOpen}
        >
          <Methodology analysis={analysis} raw={team.simulation || {}} />
        </Disclosure>
      </div>
    </div>
  );
}

function Summary({ payload, nameOf }) {
  const summary = payload.summary || {};
  const overall = summary.fairnessOverall || {};
  const cons = summary.conservation || {};
  const byId = new Map((payload.teams || []).map((t) => [t.rosterId, t]));
  return (
    <section className={own.summary} aria-labelledby="multi-team-summary-title">
      <h3 id="multi-team-summary-title" className={styles.sectionTitle}>
        Every team at a glance
      </h3>
      <div
        className={styles.tableWrap}
        role="region"
        aria-label="Every team at a glance"
        tabIndex={0}
      >
        <table className={styles.table} data-testid="multi-team-summary">
          <caption className="ds-visually-hidden">
            Each team&apos;s decision and market fairness
          </caption>
          <thead>
            <tr>
              <th scope="col">Team</th>
              <th scope="col" className={own.sendsCol}>
                Sends
              </th>
              <th scope="col">Decision</th>
              <th scope="col">Market fairness</th>
            </tr>
          </thead>
          <tbody>
            {(summary.perTeam || []).map((row) => {
              const t = byId.get(row.rosterId);
              return (
                <tr key={row.rosterId} data-summary-team={row.rosterId}>
                  <th scope="row">{row.teamName || nameOf(row.rosterId)}</th>
                  <td className={`${styles.wrap} ${own.sendsCol}`}>
                    {(t?.gives || [])
                      .map(
                        (a) =>
                          `${a.label || a.assetId} → ${nameOf(a.toRosterId)}${
                            isPricedLeg(a) ? "" : ` (${shortStateWords(a)})`
                          }`,
                      )
                      .join(", ") || "—"}
                  </td>
                  <td>
                    {t?.categoryText || row.category}
                    {t && untrustedLegs(t).length ? (
                      <span className={styles.muted} data-testid="multi-team-summary-withheld">
                        {" "}
                        — withheld, not determinable: {shortLegReasons(untrustedLegs(t))}
                      </span>
                    ) : null}
                  </td>
                  <td>{FAIRNESS_STATE_WORDS[row.fairness] || "Unable to determine"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {Array.isArray(summary.lines) && summary.lines.length ? (
        <p className={styles.lead} data-testid="multi-team-summary-lines">
          {summary.lines.join(" ")}
        </p>
      ) : null}
      <p className={styles.note} data-testid="multi-team-overall-fairness">
        <strong>All teams fair? </strong>
        {OVERALL_FAIRNESS_WORDS[overall.reasonCode] || "Unknown."} There is no single verdict for
        the whole trade: each team gets its own decision, and a trade can help more than one team.
      </p>
      {cons.balanced === true ? (
        <p className={styles.note}>
          {cons.assetsSent} assets move; every one leaves exactly one team and reaches exactly one
          other, worth {formatValue(cons.pricedRawSent)} in raw board value on both sides.
        </p>
      ) : null}
      {summary.nonConservedNote ? <p className={styles.note}>{summary.nonConservedNote}</p> : null}
    </section>
  );
}

export default function MultiTeamWarRoom({
  sides,
  teams,
  bindings,
  leagueKey = "",
  useTeamContext = true,
  onTeamContextChange,
  perspectiveRosterId = null,
  onReset,
  onFinal,
  overrideCount = 0,
}) {
  const rosterIds = useMemo(() => (bindings || []).map((b) => b?.rosterId ?? null), [bindings]);
  const ledger = useMemo(
    () => buildMultiTeamLedger({ sides, bindings: rosterIds, teams }),
    [sides, rosterIds, teams],
  );
  const request = ledger.ok ? ledger.request : null;
  const key = useMemo(
    () => multiRequestKey(request, { leagueKey, useTeamContext }),
    [request, leagueKey, useTeamContext],
  );
  const nameById = useMemo(() => {
    const m = new Map();
    for (const t of teams || []) {
      const rid = Number(t?.roster_id ?? t?.rosterId);
      if (Number.isInteger(rid)) m.set(rid, String(t?.name || `Team ${rid}`));
    }
    return m;
  }, [teams]);
  const nameOf = useCallback((rid) => nameById.get(rid) || `Team ${rid}`, [nameById]);

  // The user asks once; after that an edited trade re-asks by itself.
  const [armed, setArmed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState({
    status: "idle",
    payload: null,
    error: null,
    key: "",
  });
  const [perspective, setPerspective] = useState(null);
  const [open, setOpen] = useState({});
  const toggleOpen = useCallback((id) => setOpen((o) => ({ ...o, [id]: !o[id] })), []);
  const controllerRef = useRef(null);
  const generationRef = useRef(null);
  const immediateRef = useRef(false);

  useEffect(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    if (!armed || !request) {
      setState((s) =>
        s.status === "idle" ? s : { status: "idle", payload: null, error: null, key: "" },
      );
      return undefined;
    }
    setState({ status: "loading", payload: null, error: null, key });
    let timeoutId = null;
    const delay = immediateRef.current ? 0 : MULTI_DEBOUNCE_MS;
    immediateRef.current = false;
    const timer = setTimeout(async () => {
      const controller = new AbortController();
      controllerRef.current = controller;
      let timedOut = false;
      timeoutId = setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, MULTI_TIMEOUT_MS);
      const current = () => controllerRef.current === controller;
      const fail = (status, data) =>
        setState({
          status: "error",
          payload: null,
          error: { status, data },
          key,
        });
      try {
        const body = {
          teams: request.teams,
          assets: request.assets,
          useTeamContext: useTeamContext !== false,
        };
        if (leagueKey) body.leagueKey = leagueKey;
        if (Number.isInteger(perspectiveRosterId) && request.teams.includes(perspectiveRosterId)) {
          body.perspectiveRosterId = perspectiveRosterId;
        }
        if (generationRef.current) body.expectedGeneration = generationRef.current;
        const res = await fetch(MULTI_TEAM_ENDPOINT, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: controller.signal,
        });
        const data = await res.json().catch(() => ({}));
        if (!current()) return;
        if (timedOut) return fail(0, { error: "timeout" });
        if (controller.signal.aborted) return;
        if (!res.ok) return fail(res.status, data);
        if (!validMultiPayload(data, request, { leagueKey })) {
          return fail(0, { error: "invalid_analysis" });
        }
        if (typeof data.generation === "string") generationRef.current = data.generation;
        setState({ status: "ok", payload: data, error: null, key });
      } catch (err) {
        if (!current()) return;
        if (timedOut) return fail(0, { error: "timeout" });
        if (controller.signal.aborted) return;
        fail(0, { error: "network", message: String(err?.message || err) });
      } finally {
        clearTimeout(timeoutId);
      }
    }, delay);
    return () => {
      clearTimeout(timer);
      clearTimeout(timeoutId);
    };
    // `request` identity is folded into `key`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, armed, attempt]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  // Never show one trade's answer under another.
  const mine = state.key === key && key !== "";
  const status = !armed || !request ? "idle" : mine ? state.status : "loading";
  const payload = status === "ok" ? state.payload : null;

  useEffect(() => {
    if (!onFinal) return;
    onFinal(
      payload
        ? {
            key,
            payload,
            sideRosterIds: ledger.ok ? ledger.sideRosterIds : null,
          }
        : null,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payload, key]);

  const teamIds = payload ? payload.teams.map((t) => t.rosterId) : [];
  const shown = teamIds.includes(perspective)
    ? perspective
    : teamIds.includes(perspectiveRosterId)
      ? perspectiveRosterId
      : (teamIds[0] ?? null);
  const shownTeam = payload ? payload.teams.find((t) => t.rosterId === shown) : null;

  const analyze = () => {
    immediateRef.current = true;
    if (armed) setAttempt((n) => n + 1);
    else setArmed(true);
  };
  const reset = () => {
    controllerRef.current?.abort();
    setArmed(false);
    setPerspective(null);
    setState({ status: "idle", payload: null, error: null, key: "" });
    generationRef.current = null;
    onReset?.();
  };

  const toggle = (
    <SegmentedControl
      label="Analysis mode"
      options={CONTEXT_OPTIONS}
      value={useTeamContext !== false ? "team" : "asset"}
      onChange={(v) => onTeamContextChange?.(v === "team")}
      className={styles.mode}
    />
  );
  const n = (sides || []).length;
  const err = status === "error" ? state.error : null;
  const rosterWords = payload ? ROSTER_STATE_WORDS[payload.rosters?.state] : null;
  const unverifiable = payload?.ledger?.unverifiableAssetIds || [];

  return (
    <section
      className={styles.room}
      aria-labelledby="war-room-title"
      aria-busy={status === "loading" || undefined}
      data-war-room={`multi-${status}`}
    >
      <header className={styles.head}>
        <h2 id="war-room-title" className={styles.title}>
          Trade War Room — {n} teams
        </h2>
        <div className={styles.controls}>{toggle}</div>
      </header>
      <p className={styles.lead}>
        Every team in this trade gets its own answer, judged on its own roster and its own side of
        the deal at the same time. There is no single verdict for the whole trade.
      </p>
      {useTeamContext === false ? (
        <p className={styles.modeNote}>
          Asset only: roster fit, lineup impact, roster capacity and team direction are not
          included.
        </p>
      ) : null}
      {overrideCount > 0 ? (
        <p className={styles.modeNote}>
          The analysis prices every asset at its board value; your {overrideCount} edited value
          {overrideCount === 1 ? " is" : "s are"} used only by the preliminary meter above.
        </p>
      ) : null}

      {!ledger.ok ? (
        <div className={own.reasons} data-testid="multi-team-not-ready">
          <p className={styles.note}>
            <strong>Not ready to analyze yet.</strong>
          </p>
          <ul className={styles.whyList}>
            {ledger.reasons.map((r, i) => (
              <li key={`${r.code}-${r.sideIdx ?? "x"}-${i}`} data-reason={r.code}>
                {r.sideIdx != null && sides?.[r.sideIdx] ? `Side ${sides[r.sideIdx].label}: ` : ""}
                {r.text}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className={own.actions}>
        <Button
          variant="primary"
          onClick={analyze}
          disabled={!ledger.ok || status === "loading"}
          data-testid="multi-team-analyze"
        >
          {status === "loading"
            ? "Analyzing…"
            : armed && payload
              ? "Re-analyze"
              : `Analyze ${n}-team trade`}
        </Button>
        <Button variant="ghost" onClick={reset} data-testid="multi-team-reset">
          New trade
        </Button>
      </div>

      {status === "loading" ? (
        <p className={styles.pending} data-testid="multi-team-loading">
          Analyzing every team from the same roster snapshot…
        </p>
      ) : null}
      {err ? (
        <Banner tone="warning">
          <span data-testid="multi-team-error">
            No result: the analysis did not finish because {multiErrorText(err.status, err.data)}.
          </span>{" "}
          {multiErrorRetryable(err.status, err.data) ? (
            <Button size="sm" variant="ghost" onClick={() => setAttempt((x) => x + 1)}>
              Retry
            </Button>
          ) : null}
        </Banner>
      ) : null}

      {payload ? (
        <>
          {rosterWords ? (
            <Banner tone="warning">
              {rosterWords}, so who holds each asset cannot be confirmed. Every team is &ldquo;Not
              enough evidence&rdquo; until the rosters refresh.
            </Banner>
          ) : null}
          {unverifiable.length && !rosterWords ? (
            <Banner tone="info">
              Ownership could not be confirmed for {unverifiable.length} asset
              {unverifiable.length === 1 ? "" : "s"}; the teams they touch are not judged.
            </Banner>
          ) : null}
          {payload.snapshotChanged === true ? (
            <Banner tone="info">
              The board refreshed since your last analysis; these results use the latest values.
            </Banner>
          ) : null}
          <Summary payload={payload} nameOf={nameOf} />
          <div className={own.perspective}>
            <Tabs
              idPrefix="multi-team"
              label="View the trade as"
              tabs={payload.teams.map((t) => ({
                id: String(t.rosterId),
                label: t.team?.name || nameOf(t.rosterId),
              }))}
              active={String(shown)}
              onChange={(id) => setPerspective(Number(id))}
            />
            <div
              role="tabpanel"
              id={tabPanelId("multi-team", String(shown))}
              aria-labelledby={tabId("multi-team", String(shown))}
              className={own.panel}
            >
              {shownTeam ? (
                <TeamResult
                  team={shownTeam}
                  nameOf={nameOf}
                  showStrategy={false}
                  open={open}
                  toggleOpen={toggleOpen}
                />
              ) : null}
            </div>
          </div>
          <p className={styles.note}>{RECOMMENDATION_ONLY_TEXT}</p>
        </>
      ) : null}
    </section>
  );
}

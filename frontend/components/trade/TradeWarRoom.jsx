"use client";

/**
 * TradeWarRoom — the roster-aware Analyze Trade surface on /trade
 * (#792 / #1173 / #843 / #842; plain-English rework per owner directive
 * 2026-10-19 "Trade Calculator Clarity", Part 1 + the frontend of Part 4;
 * Lane 6 — PSI Direction A).
 *
 * Answers, for the selected team, at a glance:
 *   1. Would I make this trade?  — the ONE recommendation and its confidence;
 *   2. the biggest reason, and one genuinely different second reason;
 *   3. Trade value              — am I gaining or losing value?
 *      Impact on your team      — does my projected weekly lineup get better?
 *      Does it fit your roster? — is it legal, and who must be cut?
 *   4. a slot for the Value Adjustment comparison (dual-VA lane).
 * Behind disclosures: player-by-player lineup impact, the before/after
 * lineup, arguments / objections / uncertainty (and the strategy control),
 * and the exact sources, simulations and methodology.
 *
 * DISPLAY ONLY: every number is `POST /api/trade/analyze`'s, worded by
 * `lib/trade-war-room-copy.js`.  The recommendation is `analysis.decision`
 * (`src/trade/trade_decision.py`) rendered verbatim — never rebuilt from the
 * metrics shown here.  Missing renders as words, never 0.
 *
 * LOADING (Part 4): while the personalized analysis runs, the calculator's
 * own trade-value summary (`valueSummary`, the page's canonical totals) shows
 * at once — a value summary, never a provisional YES / NO.  A changed trade,
 * team, league, mode or strategy invalidates the request in flight
 * IMMEDIATELY (not when the debounce fires) and the previous trade's answer
 * is never shown under the new one.  Every request is bounded by
 * ANALYZE_TIMEOUT_MS and ends in an answer, an honest error, or a timeout —
 * each failure with Retry, which re-asks the same question.  Progress is
 * visible but deliberately not a live region (TC-E): only the final decision
 * is announced, once, by the page's verdict announcer.
 */

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Badge, Banner, Button, Panel, SegmentedControl } from "@/components/ds";
import {
  DECISION_TONES,
  STRATEGY_CHOICES,
  analyzeRequestKey,
  availabilityNote,
  comparablesSummary,
  formatPctPoint,
  formatPpg,
  formatSignedValue,
  formatValue,
  lineupHolesSummary,
  notPricedNames,
  overrideBasisNotice,
  postureSummary,
  rosterImpactRows,
  unavailableText,
  validAnalyzePayload,
} from "@/lib/trade-war-room";
import {
  ANALYSIS_ERRORS_NO_RETRY,
  POSTURE_LABELS,
  REASON_ROLE_WORDS,
  ROLE_PLAIN_WORDS,
  analysisErrorCode,
  analysisErrorText,
  argumentLine,
  assumptionLines,
  comparableReasonText,
  confidenceStatementText,
  confidenceSummary,
  decisionReasonSentences,
  incomingLineupSentences,
  listJoin,
  missingEvidenceText,
  packageModelLabel,
  partialCoverageNote,
  projectionBasisText,
  recordReasonText,
  rosterFit,
  rosterNoteLines,
  simulationExplanation,
  strategySentence,
  tradeValueSummary,
  uncertaintyLine,
  versionLabel,
  weeklyImpact,
} from "@/lib/trade-war-room-copy";
import { RECOMMENDATION_ONLY_TEXT } from "@/components/help/TradeHelp";
import styles from "./war-room.module.css";

const DEBOUNCE_MS = 700;
/** After this long the War Room says how long it has been working. */
export const SLOW_NOTICE_MS = 5_000;
/**
 * The hard ceiling on one analysis request.  Above the ~60 s the owner
 * observed a slow analysis finish in (2026-10-19), so a slow-but-working
 * request is not cut off, and below nginx's 120 s `/api/` read timeout, so the
 * user gets an honest "took too long" with Retry instead of a gateway error.
 */
export const ANALYZE_TIMEOUT_MS = 90_000;

const CONTEXT_OPTIONS = [
  { value: "team", label: "Team context" },
  { value: "asset", label: "Asset only" },
];

/** Plain names for the dimensions the analysis does not include yet. */
const DIMENSION_WORDS = {
  valueUncertainty: "Value uncertainty ranges",
  currentSeasonEquity: "Change in this season's playoff and title odds",
  strategicPosture: "Team direction",
  marketCorroboration: "Comparable real trades",
};
const DIMENSION_REASON_WORDS = {
  unaudited_model: "its model has not passed review yet, so it is left out",
  counterfactual_not_wired: "not connected to the analysis yet",
};

function humanizeKey(key) {
  const s = String(key || "")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/_/g, " ");
  return s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : "";
}

/**
 * One expandable section: the shared Panel disclosure, CONTROLLED from the
 * War Room so an open section stays open when a new answer arrives.  Its
 * body renders only while open — detail costs nothing until asked for.
 */
function Disclosure({ id, title, open, onToggle, children }) {
  const bodyId = useId();
  return (
    <Panel
      as="div"
      title={title}
      headingLevel={3}
      dense
      collapsible
      collapsed={!open}
      onToggleCollapsed={() => onToggle(id)}
      bodyId={bodyId}
      className={styles.disclosure}
      data-disclosure={id}
    >
      {open ? children : null}
    </Panel>
  );
}

function PlayerImpact({ rosterDetail, partialNote }) {
  const rows = rosterImpactRows(rosterDetail);
  const sentences = incomingLineupSentences(rosterDetail);
  return (
    <div className={styles.detailBody}>
      {partialNote ? <p className={styles.note}>{partialNote}</p> : null}
      {sentences.length ? (
        <ul className={styles.plainList} data-testid="war-room-lineup-sentences">
          {sentences.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      ) : null}
      {rows.length ? (
        // A table wider than a phone scrolls inside this region; the region is
        // focusable and named so a keyboard user can reach and scroll it.
        <div
          className={styles.tableWrap}
          role="region"
          aria-label="Lineup impact by player"
          tabIndex={0}
        >
          <table className={styles.table}>
            <caption className={styles.srOnly}>
              How often each affected player makes your best legal lineup, before and after the
              trade, as a share of simulated weeks
            </caption>
            <thead>
              <tr>
                <th scope="col">Player</th>
                <th scope="col">Change</th>
                <th scope="col" className={styles.num}>
                  Projected pts / week
                </th>
                <th scope="col" className={styles.num}>
                  Starts now
                </th>
                <th scope="col" className={styles.num}>
                  Starts after
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={`${p.role}-${p.playerId}`} data-role={p.role}>
                  <th scope="row" className={styles.playerCell}>
                    <span className={styles.playerName}>{p.name}</span>
                    {p.position ? <span className={styles.playerPos}>{p.position}</span> : null}
                    {availabilityNote(p) ? (
                      <span className={styles.playerPos} data-testid="war-room-availability">
                        {availabilityNote(p)}
                      </span>
                    ) : null}
                  </th>
                  <td className={styles.wrap}>{ROLE_PLAIN_WORDS[p.role] || p.role}</td>
                  <td className={styles.num}>{formatPpg(p.projectedPpg) ?? "No projection"}</td>
                  <td className={styles.num}>{formatPctPoint(p.lineupEntryPctBefore) ?? "—"}</td>
                  <td className={styles.num}>{formatPctPoint(p.lineupEntryPctAfter) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className={styles.note}>No affected player has a measured lineup share.</p>
      )}
    </div>
  );
}

function BeforeAfter({ rosterDetail }) {
  const d = rosterDetail || {};
  const before = d.before || {};
  const after = d.after || {};
  const depthB = d.depth?.before || {};
  const depthA = d.depth?.after || {};
  const holes = lineupHolesSummary(d);
  const hb = d.lineupHoles?.before || {};
  const ha = d.lineupHoles?.after || {};
  const cell = (v) => formatPpg(v) ?? "—";
  return (
    <div className={styles.detailBody}>
      <div
        className={styles.tableWrap}
        role="region"
        aria-label="Your lineup before and after"
        tabIndex={0}
      >
        <table className={styles.table}>
          <caption className={styles.srOnly}>
            Your projected lineup before and after the trade
          </caption>
          <thead>
            <tr>
              <th scope="col">Measure</th>
              <th scope="col" className={styles.num}>
                Now
              </th>
              <th scope="col" className={styles.num}>
                After
              </th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">Projected lineup points per week</th>
              <td className={styles.num}>{cell(before.expectedLineupPpg)}</td>
              <td className={styles.num}>{cell(after.expectedLineupPpg)}</td>
            </tr>
            <tr>
              <th scope="row">Points left on your bench per week</th>
              <td className={styles.num}>{cell(before.redundantPpg)}</td>
              <td className={styles.num}>{cell(after.redundantPpg)}</td>
            </tr>
            <tr>
              <th scope="row">Points lost if one starter misses a week (average)</th>
              <td className={styles.num}>{cell(depthB.meanLossPpg)}</td>
              <td className={styles.num}>{cell(depthA.meanLossPpg)}</td>
            </tr>
            {holes ? (
              <tr data-testid="war-room-lineup-holes">
                <th scope="row">
                  Empty starting slots per week
                  {holes.bySlotAfter ? (
                    <span className={styles.rowNote}> After the trade: {holes.bySlotAfter}.</span>
                  ) : null}
                  {holes.noEligible.length ? (
                    <span className={styles.rowNote}>
                      {" "}
                      Slots no player can fill: {listJoin(holes.noEligible)}.
                    </span>
                  ) : null}
                  {holes.onlyUnprojected.length ? (
                    <span className={styles.rowNote}>
                      {" "}
                      Slots only unprojected players can fill: {listJoin(holes.onlyUnprojected)}.
                    </span>
                  ) : null}
                </th>
                <td className={styles.num}>{cell(hb.emptySlotsPerWeek)}</td>
                <td className={styles.num}>{cell(ha.emptySlotsPerWeek)}</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <p className={styles.note}>
        Trade shape: {d.shape?.playersIn ?? 0} player{d.shape?.playersIn === 1 ? "" : "s"} in,{" "}
        {d.shape?.playersOut ?? 0} out.
      </p>
    </div>
  );
}

function Arguments({ analysis, showStrategy }) {
  const decision = analysis.decision || {};
  const strategy = decision.strategy;
  // The biggest uncertainty leads its list here, once -- it is not repeated
  // beside the confidence line at a glance.  A line carrying an internal code
  // reads as its plain clause instead.
  const rosterLens = analysis.lenses?.roster;
  const uncertain = [
    ...new Set(
      [analysis.topUncertainty, ...(analysis.uncertainty || [])]
        .map((x) => uncertaintyLine(x, { rosterLens }))
        .filter(Boolean),
    ),
  ];
  // Every line ends in a period; injury designations read in words.
  const band = analysis.lenses?.market?.detail?.band || null;
  const argued = (xs) => [
    ...new Set((xs || []).map((x) => argumentLine(x, { band })).filter(Boolean)),
  ];
  const lists = [
    { key: "for", title: "Points in favor", items: argued(analysis.reasonsFor) },
    { key: "against", title: "Points against", items: argued(analysis.reasonsAgainst) },
    { key: "uncertain", title: "What is uncertain", items: uncertain },
  ].filter((l) => Array.isArray(l.items) && l.items.length);
  return (
    <div className={styles.detailBody}>
      {lists.length ? (
        lists.map((l) => (
          <section key={l.key} className={styles.detailSection}>
            <h4 className={styles.detailTitle}>{l.title}</h4>
            <ul className={styles.plainList} data-list={l.key}>
              {l.items.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </section>
        ))
      ) : (
        <p className={styles.note}>The analysis listed no further arguments.</p>
      )}
      {showStrategy ? (
        <section className={styles.detailSection} data-testid="decision-strategy">
          <h4 className={styles.detailTitle}>Strategy</h4>
          <p>
            {strategySentence(strategy)} Your strategy only matters when trade value and your lineup
            point different ways; change it with the Strategy control above.
          </p>
        </section>
      ) : null}
    </div>
  );
}

function Methodology({ analysis, raw }) {
  const decision = analysis.decision || {};
  const bands = decision.bands || {};
  const confidenceStatement = confidenceStatementText(decision.confidence, {
    rosterLens: analysis.lenses?.roster,
    evidenceLens: analysis.lenses?.evidence,
    decision,
  });
  const bandsVersion = versionLabel(bands.version);
  const engineVersion = versionLabel(decision.version);
  const primary = decision.primaryReason;
  const isPrimary = (r) =>
    !!primary && r.component === primary.component && r.text === primary.text;
  const market = analysis.lenses?.market?.detail || {};
  const roster = analysis.lenses?.roster?.detail || {};
  const basis = roster.basis || {};
  const assumptions = assumptionLines(roster.assumptions, basis);
  const feasDetail = analysis.lenses?.feasibility?.detail || {};
  const rosterNotes = rosterNoteLines(feasDetail.notes, feasDetail);
  const ts = roster.teamStrength;
  const posture = postureSummary(analysis.lenses?.posture);
  const comps = comparablesSummary(analysis.lenses?.comparables);
  // Every comparable reason line in plain words (a line that would show a
  // code is dropped).
  const compRows = (comps.rows || []).map((r) => ({
    ...r,
    reasons: r.reasons.map(comparableReasonText).filter(Boolean),
  }));
  const notPriced = notPricedNames(analysis, raw);
  return (
    <div className={styles.detailBody}>
      <section className={styles.detailSection}>
        <h4 className={styles.detailTitle}>How the recommendation is made</h4>
        <p>
          One fixed rule table, not a weighted score. Trade value and the impact on your lineup each
          point for, against or neither; your strategy decides only when they disagree. A near tie
          with complete evidence is “No — too close”, and missing information gives “Not enough
          evidence” instead of a guess.
        </p>
        <p data-testid="decision-bands">
          Fairness bands{bandsVersion ? `, ${bandsVersion}` : ""} (
          {String(bands.status || "").toLowerCase()}): a gap is fair under {bands.absoluteMinimum}{" "}
          points or {bands.slightPct}% of the larger adjusted package.
        </p>
        {Array.isArray(decision.reasons) && decision.reasons.length ? (
          <div data-testid="decision-record">
            {/* The engine's record, with its numbers, in plain words: band
                labels and posture codes worded, never an axis key. */}
            <p>
              The decision engine&apos;s own record of its reasons
              {engineVersion ? ` (${engineVersion})` : ""}:
            </p>
            <ul className={styles.plainList}>
              {decision.reasons.map((r) => (
                <li key={`${r.component}-${r.text}`} data-stance={r.stance}>
                  {isPrimary(r) ? <strong>Deciding reason: </strong> : null}
                  {recordReasonText(r, { strategy: decision.strategy })}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {confidenceStatement ? (
          <p data-testid="decision-confidence-statement">
            Confidence: {confidenceStatement} Confidence is a label set by the weakest part of the
            evidence — never a probability.
          </p>
        ) : null}
      </section>
      <section className={styles.detailSection}>
        <h4 className={styles.detailTitle}>Trade value</h4>
        <p>
          Package Value Adjustment: {packageModelLabel(market.packageModel)}. Adjusted totals: you
          receive {formatValue(market.receivingAdjusted) ?? "—"} and send{" "}
          {formatValue(market.sendingAdjusted) ?? "—"}. Every asset is priced at its board value, so
          value overrides typed in the builder are not applied here, and fit with your roster never
          changes an asset&apos;s value.
        </p>
        {notPriced.length ? (
          <p>
            Not priced: {notPriced.join(", ")} — unknown, not worth 0, so left out of the totals.
          </p>
        ) : null}
      </section>
      {basis.source ? (
        <section className={styles.detailSection}>
          <h4 className={styles.detailTitle}>Lineup simulation</h4>
          <p data-testid="war-room-simulation-explained">{simulationExplanation(roster)}</p>
          <p data-testid="war-room-projection-basis">{projectionBasisText(basis)}</p>
          {assumptions.length ? (
            <ul className={styles.plainList} data-testid="war-room-assumptions">
              {assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
      {/* The roster-capacity owner's notes, in plain words (`rosterNoteLines`):
          facts about this trade's roster sit in the fit row; how the check was
          made is listed here.  The backend's own prose is never shown. */}
      {rosterNotes.detail.length ? (
        <section className={styles.detailSection}>
          <h4 className={styles.detailTitle}>How the roster fit was checked</h4>
          <ul className={styles.plainList} data-testid="war-room-roster-notes">
            {rosterNotes.detail.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {ts ? (
        <section className={styles.detailSection}>
          <h4 className={styles.detailTitle}>Team Strength (context, not a vote)</h4>
          <p>
            {formatValue(ts.before) ?? "—"} → {formatValue(ts.after) ?? "—"} (
            {formatSignedValue(ts.delta) ?? "—"}). It adds up the same player values the trade value
            uses, so it explains your roster but is not counted again.
          </p>
        </section>
      ) : null}
      {posture.available ? (
        <section className={styles.detailSection}>
          <h4 className={styles.detailTitle}>Team direction (context, not a vote)</h4>
          <p>
            <strong>{posture.headline}</strong>
            {posture.confidence ? ` — ${posture.confidence} of the classification` : ""}.{" "}
            {posture.timing}. {posture.ownFirst}.
          </p>
          <ul className={styles.plainList} aria-label="Posture split">
            {posture.split.map((p) => (
              <li key={p.label}>
                {POSTURE_LABELS[p.label] || p.label}: {p.pct ?? "—"}
              </li>
            ))}
          </ul>
          <p>
            Read from the same playoff odds, roster strength and age evidence the rest of the
            analysis uses, so it explains the recommendation but is never counted in it. Its
            parameters are declared priors, not fitted.
          </p>
        </section>
      ) : null}
      {comps.available ? (
        <section className={styles.detailSection}>
          <h4 className={styles.detailTitle}>Comparable real trades</h4>
          {comps.rows.length ? (
            <ul className={styles.plainList}>
              {compRows.map((r) => (
                <li key={r.key}>
                  <strong>{r.date}</strong>
                  {r.similarity ? ` — ${r.similarity}` : ""}
                  {r.reasons.length ? `: ${r.reasons.join("; ")}` : ""}
                </li>
              ))}
            </ul>
          ) : (
            <p>{comps.emptyText}</p>
          )}
          <p>
            What managers actually traded in similar packages. Reference only — never a price, not
            counted in the recommendation, and it does not change its confidence.
            {comps.scanCapped ? " Only the most recent matching trades were searched." : ""}
          </p>
        </section>
      ) : null}
      <section className={styles.detailSection}>
        <h4 className={styles.detailTitle}>Not included yet</h4>
        <ul className={styles.plainList}>
          {posture.available || analysis.teamContext?.mode === "asset_only" ? null : (
            <li key="strategicPosture">
              <strong>Team direction</strong> — {posture.reasonText}
            </li>
          )}
          {comps.available ? null : (
            <li key="marketCorroboration">
              <strong>Comparable real trades</strong> — {comps.reasonText}
            </li>
          )}
          {(analysis.unavailableDimensions || []).map((d) => (
            <li key={d.dimension}>
              <strong>{DIMENSION_WORDS[d.dimension] || humanizeKey(d.dimension)}</strong> —{" "}
              {DIMENSION_REASON_WORDS[d.reason] || "not included yet"}
            </li>
          ))}
        </ul>
      </section>
      <p className={styles.note}>{RECOMMENDATION_ONLY_TEXT}</p>
    </div>
  );
}

export default function TradeWarRoom({
  request,
  leagueKey = "",
  useTeamContext = true,
  onTeamContextChange,
  overrideCount = 0,
  teamName = "",
  sideChoiceNeeded = false,
  chosenSide = null,
  onChooseSide,
  onDecision,
  // The calculator's own canonical totals for this trade, in the market
  // lens's shape (`valueSummaryFromSideTotals`): shown at once while the
  // analysis runs.  `null` when unknown — never a 0.
  valueSummary = null,
  // How many sides the trade has.  The decision engine answers two-team
  // trades only; 3+ gets an explanation, never a fabricated YES / NO.
  sideCount = 2,
  // Optional element rendered at the Value Adjustment comparison slot, right
  // under the at-a-glance rows (the dual-VA lane's ValueAdjustmentComparison,
  // built by the page from per-side values the War Room does not hold).
  vaSlot = null,
}) {
  const basisNotice = overrideBasisNotice(overrideCount);
  const multi = sideCount > 2;
  // Owner decision 2: the strategy is inferred unless the user overrides it;
  // the override travels as `teamGoal` and the engine echoes it back.
  const [goalChoice, setGoalChoice] = useState("auto");
  const teamGoal = goalChoice === "auto" ? null : goalChoice;
  // Which detail sections are open — kept here so an open section stays open
  // across a new answer.
  const [open, setOpen] = useState({});
  const toggleOpen = useCallback((id) => setOpen((o) => ({ ...o, [id]: !o[id] })), []);
  // TC-A / UX audit P0-5: when roster evidence does not say which side is
  // the team's, the War Room ASKS — it never analyses an assumed side.
  const sideChooser = (
    <div className={styles.note} role="group" aria-label="Which side is your team">
      <p className={styles.note} data-testid="war-room-side-choice">
        {chosenSide != null
          ? `Analysing Side ${chosenSide === 0 ? "A" : "B"} as ${teamName || "your team"} (you chose this).`
          : `Which side is ${teamName || "your team"}? Neither side holds more of its roster, so the War Room will not guess.`}
      </p>
      <Button
        size="sm"
        variant={chosenSide === 0 ? "primary" : "ghost"}
        onClick={() => onChooseSide?.(0)}
      >
        I give Side A
      </Button>{" "}
      <Button
        size="sm"
        variant={chosenSide === 1 ? "primary" : "ghost"}
        onClick={() => onChooseSide?.(1)}
      >
        I give Side B
      </Button>
      {chosenSide != null ? (
        <>
          {" "}
          <Button size="sm" variant="ghost" onClick={() => onChooseSide?.(null)}>
            Use roster evidence
          </Button>
        </>
      ) : null}
    </div>
  );
  const [state, setState] = useState({ status: "idle", payload: null, error: null, key: "" });
  const controllerRef = useRef(null);
  // Retry (TC-E): re-asks the SAME question; the request key and the
  // abort / sequence rule are unchanged.
  const [attempt, setAttempt] = useState(0);
  // When the current request actually left (after the debounce), for the
  // truthful "N seconds so far" notice.
  const [startedAt, setStartedAt] = useState(null);
  const [now, setNow] = useState(0);
  const key = useMemo(
    () => analyzeRequestKey(request, leagueKey, useTeamContext, teamGoal),
    [request, leagueKey, useTeamContext, teamGoal],
  );
  const ready = Boolean(
    !multi &&
    request &&
    (request.playersIn.length || request.picksIn.length) &&
    (request.playersOut.length || request.picksOut.length),
  );

  useEffect(() => {
    // A new question invalidates the one in flight NOW, not when the debounce
    // fires: an answer for the previous trade can never land under this one.
    controllerRef.current?.abort();
    controllerRef.current = null;
    setStartedAt(null);
    if (!ready) {
      setState({ status: "idle", payload: null, error: null, key: "" });
      return undefined;
    }
    setState({ status: "loading", payload: null, error: null, key });
    let timeoutId = null;
    const timer = setTimeout(async () => {
      const controller = new AbortController();
      controllerRef.current = controller;
      let timedOut = false;
      timeoutId = setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, ANALYZE_TIMEOUT_MS);
      setStartedAt(Date.now());
      const current = () => controllerRef.current === controller;
      const fail = (error) => setState({ status: "error", payload: null, error, key });
      try {
        const body = {
          teamName: request.teamName,
          playersIn: request.playersIn,
          playersOut: request.playersOut,
          picksIn: request.picksIn,
          picksOut: request.picksOut,
          pickAssetIdsIn: request.pickAssetIdsIn || [],
          pickAssetIdsOut: request.pickAssetIdsOut || [],
          useTeamContext: useTeamContext !== false,
        };
        if (leagueKey) body.leagueKey = leagueKey;
        if (teamGoal) body.teamGoal = teamGoal;
        const res = await fetch("/api/trade/analyze", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: controller.signal,
        });
        const data = await res.json().catch(() => ({}));
        if (!current()) return;
        if (timedOut) return fail("timeout");
        if (controller.signal.aborted) return;
        if (!res.ok) return fail(analysisErrorCode(res.status, data));
        if (!validAnalyzePayload(data, { leagueKey, useTeamContext }))
          return fail("invalid_analysis");
        setState({ status: "ok", payload: data, error: null, key });
      } catch (err) {
        if (!current()) return;
        if (timedOut) return fail("timeout");
        if (controller.signal.aborted) return;
        fail(String(err?.message || err));
      } finally {
        clearTimeout(timeoutId);
        if (current()) setStartedAt(null);
      }
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      clearTimeout(timeoutId);
    };
    // `request` identity is folded into `key`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ready, attempt]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  // The state belongs to THIS question only.  On the render where the trade
  // changes, the old state is still in place for one frame; never show it.
  const mine = state.key === key;
  const status = !ready ? "idle" : mine ? state.status : "loading";
  const answer = status === "ok" ? state.payload : null;
  const loading = status === "loading";

  useEffect(() => {
    if (!loading || startedAt == null) return undefined;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [loading, startedAt]);
  const elapsedMs = loading && startedAt != null ? Math.max(0, now - startedAt) : 0;

  // TC-D: the page echoes THIS decision in its sticky desktop column and the
  // mobile verdict bar.  Reported, never recomputed — and only for the trade
  // on screen: while a new answer computes, nothing is reported.
  const reportedDecision = answer?.analysis?.decision || null;
  // The served decision's run id (its receipt in the server's decision log),
  // so a Trade Desk save can carry this answer (TC-B2 / TCM-G18).
  const reportedRunId = answer?.analysis?.decisionRunId || null;
  const hasTeamOrTrade = Boolean(request || teamName);
  useEffect(() => {
    if (!onDecision) return;
    if (multi) {
      onDecision({ status: "multi", decision: null });
    } else if (ready) {
      onDecision({ status, decision: reportedDecision, runId: reportedRunId });
    } else {
      onDecision({
        status: sideChoiceNeeded ? "side-choice" : hasTeamOrTrade ? "idle" : "no-team",
        decision: null,
      });
    }
  }, [
    onDecision,
    multi,
    ready,
    status,
    reportedDecision,
    reportedRunId,
    sideChoiceNeeded,
    hasTeamOrTrade,
  ]);

  const title = (
    <h2 id="war-room-title" className={styles.title}>
      Trade War Room
    </h2>
  );

  if (multi) {
    return (
      <section className={styles.room} aria-labelledby="war-room-title" data-war-room="multi">
        <header className={styles.head}>{title}</header>
        <p className={styles.lead} data-testid="war-room-multi-team-limit">
          No YES / NO is given for this {sideCount}-team trade. The decision engine can only judge
          your side of a two-team trade, so it cannot account for every side here. The result above
          compares each team&apos;s net trade value.
        </p>
        {vaSlot}
      </section>
    );
  }

  const toggle = (
    <SegmentedControl
      label="Analysis mode"
      options={CONTEXT_OPTIONS}
      value={useTeamContext !== false ? "team" : "asset"}
      onChange={(v) => onTeamContextChange?.(v === "team")}
      className={styles.mode}
    />
  );
  // An INPUT, so it lives with the mode control and never disappears while a
  // new answer computes (a control that unmounts under the pointer drops
  // keyboard focus).  Team context only: Asset-only uses no strategy.
  const strategyControl =
    useTeamContext !== false ? (
      <div className={styles.control}>
        <span className={styles.controlLabel} aria-hidden="true">
          Strategy
        </span>
        <SegmentedControl
          label="Strategy"
          options={STRATEGY_CHOICES}
          value={goalChoice}
          onChange={setGoalChoice}
          className={styles.mode}
        />
      </div>
    ) : null;

  if (!ready) {
    return (
      <section className={styles.room} aria-labelledby="war-room-title" data-war-room="idle">
        <header className={styles.head}>
          {title}
          {toggle}
        </header>
        {sideChoiceNeeded ? (
          sideChooser
        ) : (
          <p className={styles.note}>
            {/* A selected team with no request yet is an incomplete or
                side-ambiguous trade (tradeRequestForTeam answers null rather
                than assume a side), never "no team". */}
            {request || teamName
              ? "Add assets to both sides to see what this trade does to your roster."
              : "Pick your team to see what this trade does to your roster."}
          </p>
        )}
        {/* The Value Adjustment comparison works from the builder's own
            values, so it stays available before a team or side is known. */}
        {vaSlot}
      </section>
    );
  }

  const failed = status === "error";
  const analysis = answer?.analysis || null;
  const decision = analysis?.decision || null;
  const teamLabel = answer?.team?.name || request.teamName;
  const confidence = decision
    ? confidenceSummary(decision.confidence, {
        rosterLens: analysis.lenses?.roster,
        evidenceLens: analysis.lenses?.evidence,
        decision,
      })
    : null;
  // Each reason and gap as its plain sentence; one with nothing plain to say
  // is skipped, never rendered empty.
  const reasons = decision ? decisionReasonSentences(decision, { analysis }) : [];
  const missing = (decision?.missingEvidence || [])
    .map((g, i) => ({ key: `${g?.code || "gap"}-${i}`, sentence: missingEvidenceText(g) }))
    .filter((g) => g.sentence);
  const showStrategy = useTeamContext !== false;

  // ── At a glance ─────────────────────────────────────────────────────────
  const marketLens = analysis?.lenses?.market;
  const value = analysis
    ? tradeValueSummary(marketLens?.available ? marketLens.detail : null)
    : tradeValueSummary(valueSummary);
  // Where the shown trade value comes from, said truthfully in every case:
  // the summary is EXACTLY the calculator headline's totals (overrides
  // included); the analysis prices every asset at its board value.
  const summaryUnpriced = Array.isArray(valueSummary?.unpriced) ? valueSummary.unpriced : null;
  const valueSource =
    analysis || !value
      ? null
      : [
          valueSummary?.overridesApplied
            ? "The calculator's totals above, including your value overrides."
            : "The calculator's totals above.",
          failed
            ? "The personalized analysis did not finish."
            : valueSummary?.overridesApplied
              ? "The personalized analysis, still running, prices every asset at its board value, so its figure can differ."
              : "The personalized analysis is still running.",
        ].join(" ");
  const notPriced = analysis ? notPricedNames(analysis, answer) : [];
  const valueMissing = analysis
    ? unavailableText(marketLens?.unavailableReason)
    : summaryUnpriced
      ? `No total yet: ${listJoin(summaryUnpriced)} ${
          summaryUnpriced.length === 1 ? "has" : "have"
        } no value on the board (unknown, not zero).`
      : failed
        ? "Unavailable — the analysis did not finish."
        : "Waiting for the analysis.";
  const impact = analysis ? weeklyImpact(analysis.lenses?.roster) : null;
  const fit = analysis ? rosterFit(analysis.lenses?.feasibility) : null;
  const fitNotes = analysis
    ? rosterNoteLines(
        analysis.lenses?.feasibility?.detail?.notes,
        analysis.lenses?.feasibility?.detail,
      ).fit
    : [];
  const pendingWord = failed ? "Unavailable — the analysis did not finish." : null;

  const rosterLens = analysis?.lenses?.roster;
  const rosterDetail = rosterLens?.detail || {};
  const rosterMeasured = typeof rosterDetail.ppg === "number";
  const partial = rosterLens?.unavailableReason === "partial_projection_coverage";

  return (
    <section
      className={styles.room}
      aria-labelledby="war-room-title"
      aria-busy={loading || undefined}
      data-war-room={status}
    >
      <header className={styles.head}>
        {title}
        <div className={styles.controls}>
          {toggle}
          {strategyControl}
        </div>
      </header>
      {useTeamContext === false ? (
        <p className={styles.modeNote}>
          Asset only: roster fit, lineup impact and roster capacity are not included in this
          analysis.
        </p>
      ) : null}
      {chosenSide != null ? sideChooser : null}
      {/* The basis notice describes the ANALYSIS's numbers (board values, no
          overrides).  While it runs, or after it fails, the shown trade value
          is the calculator's own (overrides included), so the notice would
          contradict it: it appears with the analysis only. */}
      {basisNotice && analysis ? (
        <p className={styles.modeNote} data-testid="war-room-basis-notice">
          {basisNotice}
        </p>
      ) : null}

      {/* ── Would I make this trade? ── */}
      <div className={styles.verdict} data-decision={decision?.headline}>
        <p className={styles.eyebrow}>Recommendation for {teamLabel}</p>
        {decision ? (
          <>
            <p className={styles.verdictLine}>
              {/* Screen-reader name for the answer (TC-E): "Final decision: YES —
                  MAKE THE TRADE", not a bare badge. */}
              <span className="ds-visually-hidden">Final decision: </span>
              <Badge
                tone={DECISION_TONES[decision.headline]}
                className={styles.verdictBadge}
                data-testid="decision-headline"
              >
                {decision.headlineText}
              </Badge>
            </p>
            {decision.subtext ? <p className={styles.verdictNote}>{decision.subtext}</p> : null}
            <p className={styles.confidence} data-testid="decision-confidence">
              {confidence?.level ? <strong>{confidence.level}.</strong> : null}
              {confidence?.level && confidence?.detail ? " " : null}
              {confidence?.detail}
            </p>
          </>
        ) : loading ? (
          // Visible progress, deliberately NOT a live region (TC-E design
          // choice): only the final decision is announced, once, by the
          // page's verdict announcer.  Never a provisional YES / NO.
          <>
            <p className={styles.pending}>Analyzing this trade…</p>
            {elapsedMs >= SLOW_NOTICE_MS ? (
              <p className={styles.note} data-testid="war-room-slow">
                Still working — {Math.floor(elapsedMs / 1000)} seconds so far. If it cannot finish
                within {ANALYZE_TIMEOUT_MS / 1000} seconds it will stop and say so.
              </p>
            ) : null}
          </>
        ) : failed ? (
          <Banner tone="warning">
            <span data-testid="war-room-error">
              No recommendation yet: the personalized analysis did not finish because{" "}
              {analysisErrorText(state.error)}. The trade value below is unaffected.
            </span>{" "}
            {/* A lasting incompatibility is not fixed by trying again. */}
            {ANALYSIS_ERRORS_NO_RETRY.has(state.error) ? null : (
              <Button size="sm" variant="ghost" onClick={() => setAttempt((n) => n + 1)}>
                Retry
              </Button>
            )}
          </Banner>
        ) : null}
      </div>

      {/* ── What's the biggest reason? ── */}
      {reasons.length ? (
        <div className={styles.why}>
          <h3 className={styles.sectionTitle}>Why</h3>
          <ul className={styles.whyList} data-testid="decision-reasons">
            {reasons.map(({ role, reason, sentence }) => (
              <li key={role} data-role={role} data-stance={reason.stance}>
                <span className={styles.whyRole}>{REASON_ROLE_WORDS[role]}:</span> {sentence}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {missing.length ? (
        <div className={styles.why}>
          <h3 className={styles.sectionTitle}>What is missing</h3>
          <ul className={styles.whyList} data-testid="decision-missing">
            {missing.map((g) => (
              <li key={g.key}>{g.sentence}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* ── Am I gaining or losing value / does it help my lineup / does it fit? ── */}
      <h3 className="ds-visually-hidden">This trade at a glance</h3>
      <dl className={styles.glance}>
        <div className={styles.glanceRow} data-lens="market">
          <dt className={styles.glanceLabel}>Trade value</dt>
          <dd className={styles.glanceValue}>
            {value ? (
              <p className={styles.glanceAnswer} data-testid="war-room-trade-value">
                {value.sentence}
              </p>
            ) : (
              <p className={styles.muted}>{valueMissing}</p>
            )}
            {valueSource ? <p className={styles.note}>{valueSource}</p> : null}
            {notPriced.length ? (
              <p className={styles.note} data-testid="war-room-not-priced">
                Left out of the totals: {listJoin(notPriced)} — no value on the board (unknown, not
                zero).
              </p>
            ) : null}
          </dd>
        </div>
        <div className={styles.glanceRow} data-lens="roster">
          <dt className={styles.glanceLabel}>Impact on your team</dt>
          <dd className={styles.glanceValue}>
            {impact?.sentence ? (
              <>
                <p className={styles.glanceAnswer} data-testid="war-room-weekly-impact">
                  {impact.sentence}
                </p>
                {impact.note ? <p className={styles.note}>{impact.note}</p> : null}
              </>
            ) : (
              <p className={styles.muted}>{impact?.unavailable || pendingWord || "Calculating…"}</p>
            )}
          </dd>
        </div>
        <div className={styles.glanceRow} data-lens="feasibility">
          <dt className={styles.glanceLabel}>Does it fit your roster?</dt>
          <dd className={styles.glanceValue}>
            {fit?.sentence ? (
              <p className={styles.glanceAnswer} data-testid="war-room-roster-fit">
                {fit.sentence}
              </p>
            ) : (
              <p className={styles.muted}>{fit?.unavailable || pendingWord || "Checking…"}</p>
            )}
            {fit?.spots ? <p className={styles.note}>{fit.spots}</p> : null}
            {fitNotes.map((n) => (
              <p key={n} className={styles.note} data-testid="war-room-fit-note">
                {n}
              </p>
            ))}
          </dd>
        </div>
      </dl>

      {/* Value Adjustment comparison slot — dual-VA lane mounts ValueAdjustmentComparison here */}
      {vaSlot}

      {analysis ? (
        <div className={styles.disclosures}>
          {rosterMeasured && (rosterLens?.available || partial) ? (
            <>
              <Disclosure
                id="players"
                title="Lineup impact, player by player"
                open={Boolean(open.players)}
                onToggle={toggleOpen}
              >
                <PlayerImpact
                  rosterDetail={rosterDetail}
                  partialNote={partialCoverageNote(rosterLens)}
                />
              </Disclosure>
              <Disclosure
                id="lineup"
                title="Your lineup before and after"
                open={Boolean(open.lineup)}
                onToggle={toggleOpen}
              >
                <BeforeAfter rosterDetail={rosterDetail} />
              </Disclosure>
            </>
          ) : null}
          <Disclosure
            id="arguments"
            title="Arguments, objections and uncertainty"
            open={Boolean(open.arguments)}
            onToggle={toggleOpen}
          >
            <Arguments analysis={analysis} showStrategy={showStrategy} />
          </Disclosure>
          <Disclosure
            id="method"
            title="Sources, simulations and methodology"
            open={Boolean(open.method)}
            onToggle={toggleOpen}
          >
            <Methodology analysis={analysis} raw={answer} />
          </Disclosure>
        </div>
      ) : null}
    </section>
  );
}

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
 *   * per team: the ONE decision (YES / NO / NO — TOO CLOSE / NOT ENOUGH
 *     EVIDENCE) and its category, the market-fairness band as a SEPARATELY
 *     labelled answer (C4), what it sends and receives with destinations and
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
  return "No value (unknown, not zero)";
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

/** The package totals, straight from the market lens (raw, VA, adjusted, gap). */
function PackageTotals({ detail }) {
  if (!detail) return null;
  const n = (v) => (typeof v === "number" ? formatValue(v) : "—");
  const va = (v) => (typeof v === "number" && Math.round(v) !== 0 ? `+${formatValue(v)}` : "none");
  return (
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
          <tr>
            <th scope="row">Sends</th>
            <td className={styles.num}>{n(detail.sendingValue)}</td>
            <td className={styles.num}>{va(detail.sendingValueAdjustment)}</td>
            <td className={styles.num}>{n(detail.sendingAdjusted)}</td>
          </tr>
          <tr>
            <th scope="row">Receives</th>
            <td className={styles.num}>{n(detail.receivingValue)}</td>
            <td className={styles.num}>{va(detail.receivingValueAdjustment)}</td>
            <td className={styles.num}>{n(detail.receivingAdjusted)}</td>
          </tr>
        </tbody>
      </table>
    </div>
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
              <span className={own.assetValue}>{valueWords(a)}</span>
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
  const value = tradeValueSummary(market?.available ? market.detail : null);
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
            {value ? (
              <p className={styles.glanceAnswer}>{value.sentence}</p>
            ) : (
              <p className={styles.muted}>
                No total: an asset in this team&apos;s part of the trade has no value (unknown, not
                zero).
              </p>
            )}
            {market?.available ? <PackageTotals detail={market.detail} /> : null}
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
                      .map((a) => `${a.label || a.assetId} → ${nameOf(a.toRosterId)}`)
                      .join(", ") || "—"}
                  </td>
                  <td>{t?.categoryText || row.category}</td>
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
